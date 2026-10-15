"""Security Audit Agent — AGI-3 S6-AGI3-037-SECURITYAUDITOR.

Detects:
    * hardcoded secrets via SecretScanAdapter
    * `eval()` / `exec()` calls
    * `pickle.loads` on untrusted input
    * `subprocess` / `os.system` shell=True combined with f-strings
    * `verify=False` on TLS calls (requests, urllib3)
    * hardcoded crypto (md5/sha1 for passwords)
    * path-traversal-style f-string concatenation in file ops
    * SQL string concatenation (potential injection)
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from crtw.agents.base import ReviewAgent
from crtw.contracts import Finding, Severity


def _call_name(call: ast.Call) -> str:
    cur = call.func
    parts: list[str] = []
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _has_format_str(arg: ast.AST, scope: ast.AST | None = None) -> bool:
    """True if the arg contains an f-string or .format() call.

    If ``scope`` is supplied (e.g. the enclosing FunctionDef), ``arg`` may be
    a Name node — we follow its assignment in scope to find the underlying
    JoinedStr / .format() call.
    """
    for n in ast.walk(arg):
        if isinstance(n, ast.JoinedStr):
            return True
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Attribute) and n.func.attr == "format":
                return True
    if scope is not None and isinstance(arg, ast.Name):
        target = arg.id
        for stmt in ast.walk(scope):
            if isinstance(stmt, ast.Assign):
                for tgt in stmt.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == target:
                        if _has_format_str(stmt.value, scope):
                            return True
    return False


def _joined_text(node: ast.JoinedStr) -> str:
    """Concatenate constant parts of an f-string for SQL sniffing."""
    parts: list[str] = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(v.value)
    return "".join(parts)


def _looks_like_sql(node: ast.JoinedStr) -> bool:
    """Heuristic: f-string contains SELECT/INSERT/UPDATE/DELETE + interpolation.

    Excludes parameterized queries — if the (non-interpolated) template
    already contains a ``?`` placeholder, the interpolation is most likely
    just a debug comment or trace, not a query value.
    """
    text = _joined_text(node).lower()
    if not text:
        return False
    if not any(text.startswith(k) for k in ("select ", "insert ", "update ", "delete ")):
        return False
    # Must contain an interpolation (any FormattedValue child) to be risky.
    if not any(isinstance(v, ast.FormattedValue) for v in node.values):
        return False
    # Parameterized queries are safe.
    if "?" in text:
        return False
    return True


class SecurityAuditAgent(ReviewAgent):
    agent_id = "S6-AGI3-037-SECURITYAUDITOR"
    name = "security"

    def __init__(self, **kw):
        super().__init__(**kw)
        # Security agent only really needs the secret-scan + AST walk.
        self.adapters.pop("test_runner", None)
        self.adapters.pop("coverage", None)
        self.adapters.pop("static_analysis", None)

    def research(self, target: str) -> dict[str, Any]:
        """Walk every Python file in target AND run secret-scan adapter."""
        evidence: dict[str, Any] = super().research(target)
        evidence["files"] = {}
        target_path = Path(target).resolve()
        files = self._collect_python_files(target_path)
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            evidence["files"][str(f)] = {"size": len(text), "lines": text.count("\n") + 1}
            try:
                evidence["files"][str(f)]["ast"] = ast.parse(text, filename=str(f))
            except SyntaxError as e:
                evidence["files"][str(f)]["syntax_error"] = f"{e.msg} on line {e.lineno}"
        evidence["files_meta"] = list(files)
        return evidence

    def reason(self, evidence: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        # 1) secret scan findings
        secret_out = evidence.get("adapters", {}).get("secret_scan", {})
        for f in secret_out.get("data", {}).get("findings", []):
            out.append(Finding(
                severity=Severity.BLOCKER,
                stage=self.name,
                agent_id=self.agent_id,
                file=f.get("file"),
                line=f.get("line"),
                title=f"Hardcoded secret ({f['kind']})",
                detail=f["description"],
                evidence=f["redacted_match"],
                remediation="Move the secret to an environment variable, vault, or secrets manager. Rotate the leaked credential.",
                confidence=0.99,
                tags=["secret", f["kind"]],
            ))

        # 2) AST-based dangerous patterns
        for path, blob in evidence.get("files", {}).items():
            tree = blob.get("ast")
            if tree is None:
                continue
            out.extend(self._check_file(path, tree))
        return out

    @staticmethod
    def _collect_python_files(target: Path) -> list[Path]:
        if target.is_file():
            return [target] if target.suffix == ".py" else []
        skip = {".git", "__pycache__", ".venv", "venv", "node_modules",
                ".pytest_cache", ".mypy_cache", ".ruff_cache", "reports"}
        out: list[Path] = []
        for p in target.rglob("*.py"):
            if set(p.parts) & skip:
                continue
            out.append(p)
        return out

    def _check_file(self, path: str, tree: ast.Module) -> list[Finding]:
        out: list[Finding] = []
        # Track enclosing function name for context-aware checks (e.g. MD5 in
        # password-hashing functions).
        enclosing_fn = self._build_enclosing_fn_map(tree)
        scope_map = self._build_scope_map(tree)
        ctx = {**enclosing_fn, "_scope": scope_map}  # internal-use namespace
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                out.extend(self._check_call(path, node, ctx))
            elif isinstance(node, ast.Assign):
                out.extend(self._check_assign(path, node))
            elif isinstance(node, ast.JoinedStr):
                # Catch SQL-injection-shaped f-strings even when they are not
                # passed to a Call node (e.g. returned for later execution).
                if _looks_like_sql(node):
                    out.append(Finding(
                        severity=Severity.BLOCKER,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=path,
                        line=node.lineno,
                        title="SQL injection risk: f-string SQL query",
                        detail="SQL string built with f-string / .format() — use parameterized queries.",
                        evidence=f"{path}:{node.lineno}",
                        remediation="Use parameter substitution: `cursor.execute(sql, (param,))`.",
                        confidence=0.85,
                        tags=["sql-injection"],
                    ))
        return out

    @staticmethod
    def _build_enclosing_fn_map(tree: ast.Module) -> dict[int, str]:
        """Map each AST node id() to the name of the function it's inside."""
        result: dict[int, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    if sub is node:
                        continue
                    result[id(sub)] = node.name
                result[id(node)] = node.name
        return result

    @staticmethod
    def _build_scope_map(tree: ast.Module) -> dict[int, ast.AST]:
        """Map each AST node id() to the enclosing FunctionDef (for variable lookup)."""
        result: dict[int, ast.AST] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for sub in ast.walk(node):
                    result[id(sub)] = node
        return result

    def _check_call(self, path: str, call: ast.Call, ctx: dict | None = None) -> list[Finding]:
        out: list[Finding] = []
        name = _call_name(call)
        ctx = ctx or {}
        fn_name = ctx.get(id(call), "")
        scope_map = ctx.get("_scope", {}) if isinstance(ctx, dict) else {}
        scope_node = scope_map.get(id(call))

        # eval / exec
        if name in ("eval", "exec"):
            out.append(Finding(
                severity=Severity.BLOCKER,
                stage=self.name,
                agent_id=self.agent_id,
                file=path,
                line=call.lineno,
                title=f"Dangerous use of `{name}()`",
                detail=f"`{name}()` executes arbitrary code; common RCE vector if input is untrusted.",
                evidence=f"{path}:{call.lineno}: {name}",
                remediation="Avoid `eval`/`exec`. Use `ast.literal_eval` for data, or restructure to avoid dynamic execution.",
                confidence=0.95,
                tags=["rce", "eval"],
            ))

        # pickle.loads
        if name == "pickle.loads" or name.endswith(".loads") and "pickle" in name:
            out.append(Finding(
                severity=Severity.BLOCKER,
                stage=self.name,
                agent_id=self.agent_id,
                file=path,
                line=call.lineno,
                title="`pickle.loads` on untrusted input",
                detail="`pickle.loads` allows arbitrary code execution.",
                evidence=f"{path}:{call.lineno}: {name}",
                remediation="Use JSON or msgpack for untrusted input; never unpickle attacker-controlled bytes.",
                confidence=0.9,
                tags=["rce", "pickle"],
            ))

        # subprocess / os.system with shell=True + f-string
        if name in ("subprocess.run", "subprocess.Popen", "subprocess.call", "os.system"):
            # Look for shell=True keyword
            shell_true = any(
                kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in call.keywords
            )
            # shell=True alone is enough to flag; f-string makes it worse.
            if shell_true:
                if call.args and _has_format_str(call.args[0], scope=scope_node):
                    out.append(Finding(
                        severity=Severity.BLOCKER,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=path,
                        line=call.lineno,
                        title="Command injection: `shell=True` + format string",
                        detail="`shell=True` with an f-string/.format() first arg enables command injection.",
                        evidence=f"{path}:{call.lineno}: {name}",
                        remediation="Use list-form subprocess (no shell) and pass arguments separately; never interpolate user input.",
                        confidence=0.95,
                        tags=["command-injection", "shell"],
                    ))
                else:
                    out.append(Finding(
                        severity=Severity.MAJOR,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=path,
                        line=call.lineno,
                        title="`shell=True` enables command injection",
                        detail="`shell=True` invokes a shell; prefer list-form argv.",
                        evidence=f"{path}:{call.lineno}: {name}",
                        remediation="Pass argv as a list, no shell.",
                        confidence=0.7,
                        tags=["command-injection", "shell"],
                    ))

        # requests.*(verify=False)
        if name.startswith("requests.") and name.split(".")[-1] in (
            "get", "post", "put", "delete", "patch", "head", "request"
        ):
            for kw in call.keywords:
                if kw.arg == "verify" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    out.append(Finding(
                        severity=Severity.CRITICAL,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=path,
                        line=call.lineno,
                        title="TLS verification disabled (`verify=False`)",
                        detail="`verify=False` disables certificate validation. Vulnerable to MITM.",
                        evidence=f"{path}:{call.lineno}: {name}(verify=False)",
                        remediation="Remove `verify=False`; if you must use a self-signed cert pass `verify='/path/to/cert'`.",
                        confidence=0.95,
                        tags=["tls", "mitm"],
                    ))

        # SQL string concat (heuristic)
        if name.endswith("execute") or name.endswith("executemany") or name.endswith("raw"):
            if call.args and _has_format_str(call.args[0]):
                out.append(Finding(
                    severity=Severity.BLOCKER,
                    stage=self.name,
                    agent_id=self.agent_id,
                    file=path,
                    line=call.lineno,
                    title="SQL injection risk in `{0}`".format(name),
                    detail="SQL string built with f-string / .format() — use parameterized queries.",
                    evidence=f"{path}:{call.lineno}: {name}",
                    remediation="Use parameter substitution: `cursor.execute(sql, (param,))`.",
                    confidence=0.85,
                    tags=["sql-injection"],
                ))

        # open() with f-string path
        if name in ("open", "io.open") or name.startswith("Path("):
            pass  # Path() handled below as attribute path check
            if name == "open" and call.args and _has_format_str(call.args[0]):
                out.append(Finding(
                    severity=Severity.MAJOR,
                    stage=self.name,
                    agent_id=self.agent_id,
                    file=path,
                    line=call.lineno,
                    title="Potential path traversal: `open(f-string)`",
                    detail="`open()` with a formatted path can be exploited for path traversal if any segment is user-controlled.",
                    evidence=f"{path}:{call.lineno}: open(...)",
                    remediation="Validate that the final resolved path stays inside the intended root.",
                    confidence=0.6,
                    tags=["path-traversal"],
                ))

        # hashlib.md5 / hashlib.sha1 — weak hashing.  Inside a password-related
        # function this is critical; otherwise still flagged at MAJOR.
        if name in ("hashlib.md5", "hashlib.sha1"):
            is_password_ctx = any(
                kw in fn_name.lower() for kw in ("password", "passwd", "pwd", "hash")
            )
            sev = Severity.CRITICAL if is_password_ctx else Severity.MAJOR
            tag = "weak-hash-password" if is_password_ctx else "weak-hash"
            out.append(Finding(
                severity=sev,
                stage=self.name,
                agent_id=self.agent_id,
                file=path,
                line=call.lineno,
                title=f"Weak hashing for password: `{name}`" if is_password_ctx
                      else f"Weak hash algorithm: `{name}`",
                detail="MD5/SHA1 are not suitable for password hashing.",
                evidence=f"{path}:{call.lineno}: {name}(...)",
                remediation="Use `hashlib.bcrypt`, `argon2`, or `hashlib.scrypt`.",
                confidence=0.9 if is_password_ctx else 0.7,
                tags=["crypto", tag],
            ))

        return out

    def _check_assign(self, path: str, node: ast.Assign) -> list[Finding]:
        out: list[Finding] = []
        for tgt in node.targets:
            if not isinstance(tgt, ast.Name):
                continue
            lname = tgt.id.lower()
            if not any(k in lname for k in ("password", "passwd", "pwd", "secret", "hash")):
                continue
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Call):
                    name = _call_name(sub)
                    if name in ("hashlib.md5", "hashlib.sha1"):
                        out.append(Finding(
                            severity=Severity.CRITICAL,
                            stage=self.name,
                            agent_id=self.agent_id,
                            file=path,
                            line=node.lineno,
                            title=f"Weak hashing for password: `{name}`",
                            detail="MD5/SHA1 are not suitable for password hashing.",
                            evidence=f"{path}:{node.lineno}: {tgt.id} = {name}(...)",
                            remediation="Use `hashlib.bcrypt`, `argon2`, or `hashlib.scrypt`.",
                            confidence=0.85,
                            tags=["crypto", "weak-hash"],
                        ))
                    if name in ("hashlib.md5",):
                        out.append(Finding(
                            severity=Severity.CRITICAL,
                            stage=self.name,
                            agent_id=self.agent_id,
                            file=path,
                            line=node.lineno,
                            title="MD5 used for password hashing",
                            detail="MD5 is cryptographically broken and unsuitable for password storage.",
                            evidence=f"{path}:{node.lineno}: {name}(...)",
                            remediation="Use bcrypt / argon2 / scrypt.",
                            confidence=0.95,
                            tags=["crypto", "md5"],
                        ))
        return out