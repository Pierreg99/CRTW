"""Code Review Agent — AGI-3 S3-AGI3-010-REVIEWER.

Performs AST-based detection of:
    * complexity hotspots (long functions measured via AST node count)
    * missing error handling on risky calls (network/file ops)
    * bare `except:` clauses
    * mutable default arguments
    * unused imports
    * missing type hints on public functions
    * dead code (unreachable / unreachable-by-return)
    * TODO / FIXME / XXX markers
    * swallowed exceptions (try/except/pass)

These detections are real: they walk the AST, compute evidence, and emit
``Finding`` objects with file:line evidence.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Iterable

from crtw.agents.base import ReviewAgent
from crtw.contracts import Finding, Severity


RISKY_CALL_NAMES = {
    "open", "requests.get", "requests.post", "requests.put", "requests.delete",
    "urlopen", "subprocess.run", "subprocess.Popen", "Popen", "socket.socket",
    "connect", "connect_ex",
}

SWALLOW_NAMES = {"pass", "...", "continue"}


def _function_node_count(node: ast.AST) -> int:
    """Total descendant AST nodes for a function (proxy for cyclomatic complexity)."""
    return sum(1 for _ in ast.walk(node))


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _has_return_annotation(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return node.returns is not None


def _all_args_annotated(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = node.args
    all_args = list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)
    if args.vararg and not args.vararg.annotation:
        return False
    if args.kwarg and not args.kwarg.annotation:
        return False
    for a in all_args:
        if a.annotation is None:
            return False
    return True


def _find_swallowed(body: list[ast.stmt]) -> bool:
    """Detect `except SomeError: pass` or `except: pass/continue`."""
    for stmt in body:
        if isinstance(stmt, ast.Try):
            for handler in stmt.handlers:
                if handler.body and all(
                    isinstance(s, (ast.Pass, ast.Expr)) or \
                    (isinstance(s, ast.Continue) and len(handler.body) == 1)
                    for s in handler.body
                ):
                    # empty body / pass-only
                    if any(isinstance(s, ast.Pass) for s in handler.body) and len(handler.body) == 1:
                        return True
    return False


def _collect_calls(node: ast.AST) -> Iterable[ast.Call]:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            yield sub


def _call_name(call: ast.Call) -> str:
    """Resolve a Call node to a fully-qualified dotted name when possible."""
    cur = call.func
    parts: list[str] = []
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


class CodeReviewAgent(ReviewAgent):
    agent_id = "S3-AGI3-010-REVIEWER"
    name = "review"

    def __init__(self, **kw):
        super().__init__(**kw)
        # Reviewer does not strictly need the test runner.
        self.adapters.pop("test_runner", None)
        self.adapters.pop("coverage", None)

    # ------------------------------------------------------------------
    # RRR.Research: walk every Python file in target.
    # ------------------------------------------------------------------

    def research(self, target: str) -> dict[str, Any]:
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

    # ------------------------------------------------------------------
    # RRR.Reason: emit findings.
    # ------------------------------------------------------------------

    def reason(self, evidence: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        for path, blob in evidence.get("files", {}).items():
            tree = blob.get("ast")
            if tree is None:
                # Record syntax errors as findings.
                if blob.get("syntax_error"):
                    out.append(Finding(
                        severity=Severity.MAJOR,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=path,
                        title="SyntaxError prevents AST analysis",
                        detail=blob["syntax_error"],
                        evidence=blob["syntax_error"],
                        remediation="Fix the syntax error so this module can be imported.",
                        confidence=0.9,
                        tags=["ast", "syntax"],
                    ))
                continue
            out.extend(self._check_file(path, tree))

        # Optional: forward static-analysis diagnostics into findings.
        sa = evidence.get("adapters", {}).get("static_analysis", {})
        for d in sa.get("data", {}).get("diagnostics", []):
            sev = self._diagnostic_severity(d)
            if sev is None:
                continue
            out.append(Finding(
                severity=sev,
                stage=self.name,
                agent_id=self.agent_id,
                file=d.get("file"),
                line=d.get("line"),
                title=f"{d.get('code', 'linter')}: {d.get('message', '')[:60]}",
                detail=d.get("message", ""),
                evidence=f"{d.get('file')}:{d.get('line')}",
                remediation="See linter documentation.",
                confidence=0.8,
                tags=["linter", d.get("tool", "")],
            ))

        return out

    # ------------------------------------------------------------------
    # Per-file checks
    # ------------------------------------------------------------------

    def _check_file(self, path: str, tree: ast.Module) -> list[Finding]:
        out: list[Finding] = []
        text = Path(path).read_text(encoding="utf-8", errors="replace")

        # TODO / FIXME / XXX markers — INFO.
        for ln_no, line in enumerate(text.splitlines(), 1):
            m = re.search(r"#\s*(TODO|FIXME|XXX|HACK)\b(.*)$", line)
            if m:
                out.append(Finding(
                    severity=Severity.INFO,
                    stage=self.name,
                    agent_id=self.agent_id,
                    file=path,
                    line=ln_no,
                    title=f"{m.group(1).upper()} marker",
                    detail=m.group(2).strip() or "(no message)",
                    evidence=line.strip(),
                    remediation="Resolve or convert into a tracked issue.",
                    confidence=0.9,
                    tags=["todo"],
                ))

        # Walk top-level + nested definitions.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.extend(self._check_function(path, node))
            elif isinstance(node, ast.ClassDef):
                out.extend(self._check_class(path, node))
            elif isinstance(node, ast.ExceptHandler):
                out.extend(self._check_except(path, node))

        # Top-level imports + mutable defaults (single-pass over modules).
        out.extend(self._check_module_imports(tree, path))
        out.extend(self._check_mutable_defaults(tree, path))
        out.extend(self._check_swallowed(tree, path))

        # Risky calls without try/except (heuristic).
        out.extend(self._check_risky_calls(tree, path))

        return out

    # --- per-function ---

    def _check_function(self, path: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> list[Finding]:
        out: list[Finding] = []
        node_count = _function_node_count(fn)
        if node_count > 80:
            sev = Severity.MAJOR if node_count < 150 else Severity.CRITICAL
            out.append(Finding(
                severity=sev,
                stage=self.name,
                agent_id=self.agent_id,
                file=path,
                line=fn.lineno,
                title=f"Long function: {fn.name} ({node_count} AST nodes)",
                detail=(
                    f"Function `{fn.name}` has {node_count} AST nodes which is a "
                    "complexity hotspot. Consider splitting it."
                ),
                evidence=f"{path}:{fn.lineno}:def {fn.name}",
                remediation="Extract helper functions; lower cyclomatic complexity.",
                confidence=0.8,
                tags=["complexity"],
            ))

        if _is_public(fn.name) and not fn.name.startswith("test_") and not _all_args_annotated(fn):
            missing = [
                a.arg for a in (list(fn.args.posonlyargs) + list(fn.args.args) + list(fn.args.kwonlyargs))
                if a.annotation is None
            ]
            out.append(Finding(
                severity=Severity.MINOR,
                stage=self.name,
                agent_id=self.agent_id,
                file=path,
                line=fn.lineno,
                title=f"Missing type hints on public function `{fn.name}`",
                detail=f"Missing annotations for: {', '.join(missing) or 'return'}",
                evidence=f"def {fn.name}({', '.join(a.arg for a in fn.args.args)})",
                remediation="Add type annotations to arguments and return.",
                confidence=0.7,
                tags=["typing"],
            ))

        if _is_public(fn.name) and not fn.name.startswith("test_") and not _has_return_annotation(fn) and fn.returns is None:
            out.append(Finding(
                severity=Severity.INFO,
                stage=self.name,
                agent_id=self.agent_id,
                file=path,
                line=fn.lineno,
                title=f"Missing return annotation on `{fn.name}`",
                detail="Public function has no return type annotation.",
                evidence=f"def {fn.name}(...)",
                remediation="Add a return annotation.",
                confidence=0.6,
                tags=["typing"],
            ))

        # dead code: statements after a top-level `return`/`raise` are unreachable.
        if isinstance(fn, ast.FunctionDef):
            for i, stmt in enumerate(fn.body):
                if isinstance(stmt, (ast.Return, ast.Raise)):
                    for j, after in enumerate(fn.body[i + 1:], start=i + 1):
                        if isinstance(after, (ast.Pass, ast.Expr)) and not getattr(after, "value", None):
                            continue
                        out.append(Finding(
                            severity=Severity.MINOR,
                            stage=self.name,
                            agent_id=self.agent_id,
                            file=path,
                            line=after.lineno,
                            title=f"Unreachable code after return/raise in `{fn.name}`",
                            detail=f"Statement after `{'return' if isinstance(stmt, ast.Return) else 'raise'}` on line {stmt.lineno}.",
                            evidence=f"{path}:{after.lineno}",
                            remediation="Remove unreachable code.",
                            confidence=0.9,
                            tags=["dead-code"],
                        ))
                        break
                    break

        return out

    def _check_class(self, path: str, cls: ast.ClassDef) -> list[Finding]:
        out: list[Finding] = []
        for node in ast.walk(cls):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out.extend(self._check_function(path, node))
        return out

    # --- bare except ---

    def _check_except(self, path: str, handler: ast.ExceptHandler) -> list[Finding]:
        out: list[Finding] = []
        if handler.type is None:
            out.append(Finding(
                severity=Severity.CRITICAL,
                stage=self.name,
                agent_id=self.agent_id,
                file=path,
                line=handler.lineno,
                title="Bare `except:` swallows all exceptions",
                detail="A bare `except:` catches BaseException including KeyboardInterrupt and SystemExit.",
                evidence=f"{path}:{handler.lineno}: bare except",
                remediation="Catch a specific exception class (e.g. `except ValueError:`).",
                confidence=0.95,
                tags=["error-handling", "bare-except"],
            ))
        return out

    # --- mutable defaults ---

    def _check_mutable_defaults(self, tree: ast.Module, path: str) -> list[Finding]:
        out: list[Finding] = []
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for default in fn.args.defaults + fn.args.kw_defaults:
                d = default
                if d is None:
                    continue
                if isinstance(d, (ast.List, ast.Dict, ast.Set)):
                    out.append(Finding(
                        severity=Severity.CRITICAL,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=path,
                        line=fn.lineno,
                        title=f"Mutable default argument in `{fn.name}`",
                        detail="Mutable defaults are shared between calls and cause subtle state-leak bugs.",
                        evidence=f"def {fn.name}(...)",
                        remediation="Use `None` as the default and create the mutable inside the function.",
                        confidence=0.99,
                        tags=["mutable-default"],
                    ))
                    break
        return out

    # --- unused imports (best-effort, second pass) ---

    def _check_module_imports(self, tree: ast.Module, path: str) -> list[Finding]:
        out: list[Finding] = []
        imported: dict[str, int] = {}
        future_imports: set[str] = set()  # names imported from __future__
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported[alias.asname or alias.name.split(".")[0]] = node.lineno
            elif isinstance(node, ast.ImportFrom):
                if node.module == "__future__":
                    # All `from __future__ import X` are magic directives
                    # that affect how the compiler parses code, not
                    # runtime names. Skip them to avoid false positives.
                    for alias in node.names:
                        if alias.name != "*":
                            future_imports.add(alias.asname or alias.name)
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    imported[alias.asname or alias.name] = node.lineno
        used: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                used.add(node.id)
            elif isinstance(node, ast.Attribute):
                base = node
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name):
                    used.add(base.id)
        for name, ln in imported.items():
            if name not in used:
                if name in future_imports:
                    continue
                out.append(Finding(
                    severity=Severity.MINOR,
                    stage=self.name,
                    agent_id=self.agent_id,
                    file=path,
                    line=ln,
                    title=f"Unused import: `{name}`",
                    detail=f"Imported but never referenced.",
                    evidence=f"line {ln}: import {name}",
                    remediation="Remove the unused import.",
                    confidence=0.9,
                    tags=["unused-import"],
                ))
        return out

    # --- swallowed exceptions ---

    def _check_swallowed(self, tree: ast.Module, path: str) -> list[Finding]:
        out: list[Finding] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                if not handler.body:
                    out.append(Finding(
                        severity=Severity.MAJOR,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=path,
                        line=handler.lineno,
                        title="Empty `except` block",
                        detail="Exception caught but body is empty.",
                        evidence=f"{path}:{handler.lineno}",
                        remediation="Log the exception or re-raise.",
                        confidence=0.95,
                        tags=["swallowed"],
                    ))
                    continue
                if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                    out.append(Finding(
                        severity=Severity.MAJOR,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=path,
                        line=handler.lineno,
                        title="Swallowed exception (`except: pass`)",
                        detail="Exception caught and silently dropped.",
                        evidence=f"{path}:{handler.lineno}",
                        remediation="Log or re-raise; do not silently ignore exceptions.",
                        confidence=0.95,
                        tags=["swallowed"],
                    ))
        return out

    # --- risky calls without try/except ---

    def _check_risky_calls(self, tree: ast.Module, path: str) -> list[Finding]:
        out: list[Finding] = []
        guard_nodes = [n for n in ast.walk(tree) if isinstance(n, (ast.Try, ast.With))]
        for call in _collect_calls(tree):
            name = _call_name(call)
            if not any(name == r or name.endswith("." + r) for r in ("open", "requests.get", "requests.post", "urlopen")):
                continue
            guarded = False
            for gn in guard_nodes:
                for sub in ast.walk(gn):
                    if sub is call:
                        guarded = True
                        break
                if guarded:
                    break
            if not guarded:
                out.append(Finding(
                    severity=Severity.MAJOR,
                    stage=self.name,
                    agent_id=self.agent_id,
                    file=path,
                    line=call.lineno,
                    title=f"Unguarded risky call: `{name}()`",
                    detail="Network or file operation without a try/except or with-context guard.",
                    evidence=f"{path}:{call.lineno}: {name}",
                    remediation="Wrap in try/except (and handle the specific exception class) or use a `with` context.",
                    confidence=0.7,
                    tags=["error-handling"],
                ))
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _diagnostic_severity(d: dict[str, Any]) -> Severity | None:
        code = (d.get("code") or "").upper()
        if "E9" in code or "F821" in code or "F811" in code:
            return Severity.MAJOR
        if "E" in code and not code.endswith("E9"):
            return Severity.MINOR
        if "F401" in code:  # unused
            return Severity.MINOR
        if "F" in code:
            return Severity.MINOR
        return Severity.INFO

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