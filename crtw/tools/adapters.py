"""Tool adapters for CRTW.

Every adapter follows the same protocol so agents can call them uniformly:

    adapter = TestRunnerAdapter()
    if adapter.is_available():
        out = adapter.run(target)
        out.data  # parsed, structured
        out.artifacts  # paths
        out.raw  # raw output (may be redacted)

Tools that are missing degrade to available=False with a clear reason. The
orchestrator must never crash because of a missing tool.
"""
from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from crtw.contracts import ToolOutput


# =============================================================================
# Helpers
# =============================================================================


def _which(prog: str) -> Optional[str]:
    return shutil.which(prog)


def _run(
    cmd: list[str],
    cwd: Optional[str] = None,
    timeout: int = 120,
    env: Optional[dict[str, str]] = None,
) -> tuple[int, str, str]:
    """Run a subprocess, cap duration, capture stdout+stderr.

    Returns (returncode, stdout, stderr).
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            timeout=timeout,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", (e.stderr or "") + f"\n[timeout after {timeout}s]"
    except FileNotFoundError as e:
        return 127, "", f"[command not found: {e.filename}]"


# =============================================================================
# Adapter protocol
# =============================================================================


@dataclass
class ToolAdapter:
    name: str
    enabled: bool = True

    def is_available(self) -> bool:
        raise NotImplementedError

    def run(self, target: str, *, timeout: int = 60) -> ToolOutput:
        raise NotImplementedError


# =============================================================================
# TestRunnerAdapter — pytest or unittest
# =============================================================================


class TestRunnerAdapter:
    name = "test_runner"

    def __init__(self, prefer: str = "pytest", pytest_args: Optional[list[str]] = None):
        self.prefer = prefer
        self.pytest_args = list(pytest_args or [])

    # ------------- availability -------------

    def is_available(self) -> bool:
        # Either pytest OR unittest works; pytest preferred when both present.
        if self.prefer == "pytest" and _which("pytest"):
            return True
        if _which("pytest"):
            return True
        # unittest is in stdlib so always available
        return True

    # ------------- entry point -------------

    def run(self, target: str, *, timeout: int = 120) -> ToolOutput:
        target_path = Path(target).resolve()
        if not target_path.exists():
            return ToolOutput(
                adapter=self.name,
                available=False,
                reason=f"target does not exist: {target_path}",
            )

        if _which("pytest") and self.prefer == "pytest":
            return self._run_pytest(target_path, timeout=timeout)
        if _which("pytest"):
            return self._run_pytest(target_path, timeout=timeout)
        return self._run_unittest(target_path, timeout=timeout)

    # ------------- pytest backend -------------

    def _run_pytest(self, target: Path, *, timeout: int) -> ToolOutput:
        # Use a JSON report via pytest -- if pytest-json-report is available;
        # otherwise parse plain output. We do NOT require it.
        cmd = ["pytest", "-q", "--tb=short", str(target)]
        cmd += self.pytest_args
        # ignore deprecation noise
        env = os.environ.copy()
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        env.setdefault("PYTHONUNBUFFERED", "1")

        rc, out, err = _run(cmd, cwd=str(target_path.parent), timeout=timeout, env=env)
        combined = out + err
        parsed = self._parse_pytest_text(combined, rc)
        return ToolOutput(
            adapter=self.name,
            available=True,
            data=parsed,
            raw=combined,
        )

    @staticmethod
    def _parse_pytest_text(text: str, rc: int) -> dict[str, Any]:
        """Extract pass/fail/error counts + per-test failure details from pytest
        short-traceback output. No external deps required."""
        summary: dict[str, Any] = {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "collected": 0,
            "failures": [],   # list of dicts: test, file, line, message, traceback
            "errors_list": [],  # collection errors
            "returncode": rc,
            "duration_s": None,
        }

        # ----- "collected N items" -----
        m_collected = re.search(r"collected\s+(\d+)\s+items?", text)
        if m_collected:
            summary["collected"] = int(m_collected.group(1))

        # ----- count line: e.g. "5 passed, 1 failed, 2 errors in 0.12s" -----
        m = re.search(
            r"(?P<counts>(?:\d+ (?:passed|failed|error|errors|warning|warnings)\s*[,+]?\s*)+)"
            r"(?:in (?P<dur>[\d.]+)s)?",
            text,
        )
        if m:
            counts_blob = m.group("counts")
            for kind in ("passed", "failed", "error", "errors",
                         "skipped", "warning", "warnings"):
                mm = re.search(rf"(\d+)\s+{kind}", counts_blob)
                if mm:
                    n = int(mm.group(1))
                    if kind == "error":
                        summary["errors"] += n
                    elif kind == "errors":
                        summary["errors"] += n
                    elif kind == "warning":
                        pass
                    elif kind == "warnings":
                        pass
                    else:
                        summary[kind] += n
            if m.group("dur"):
                try:
                    summary["duration_s"] = float(m.group("dur"))
                except Exception:
                    pass

        # ----- per-failure blocks: "FAILED tests/test_x.py::test_y - AssertionError: ..." -----
        # Find each "FAILED " or "ERROR " header, then grab the next short tb.
        fail_headers = list(re.finditer(
            r"^(?:FAILED|ERROR)\s+([^\s:]+(?:::[^,\n]+)?)\s*(?:-\s*(.*))?$",
            text,
            flags=re.MULTILINE,
        ))
        for i, hm in enumerate(fail_headers):
            test_id = hm.group(1)
            short_msg = (hm.group(2) or "").strip()
            # The traceback region runs until the next FAILED/ERROR header or
            # blank-line separated summary section.
            start = hm.end()
            end = fail_headers[i + 1].start() if i + 1 < len(fail_headers) else len(text)
            block = text[start:end].strip()

            file_line = TestRunnerAdapter._extract_file_line(block, test_id)
            assertion = TestRunnerAdapter._extract_assertion_message(block, short_msg)

            entry = {
                "test": test_id,
                "file": file_line[0],
                "line": file_line[1],
                "message": assertion,
                "traceback": block.splitlines()[-12:],
            }
            if hm.group(0).startswith("ERROR"):
                summary["errors_list"].append(entry)
            else:
                summary["failures"].append(entry)

        # collection errors: lines like "ERROR tests/test_x.py - ..." appear before summary
        if not summary["errors_list"]:
            for m in re.finditer(r"^ERROR\s+([^\s]+)\s*$", text, flags=re.MULTILINE):
                summary["errors_list"].append({
                    "test": m.group(1),
                    "file": m.group(1),
                    "line": None,
                    "message": "collection error",
                    "traceback": [],
                })

        return summary

    @staticmethod
    def _extract_file_line(block: str, test_id: str) -> tuple[Optional[str], Optional[int]]:
        # Three formats we might encounter in the traceback block:
        #   pytest --tb=short:    /path/to/file.py:42: in test_foo
        #                         > /path/to/file.py:42(SomeClass.test_foo)
        #   Python native traceback: File "/path/to/file.py", line 42, in test_foo
        #   assertion pinpoint:        assert produce_one() == 2
        # First, try Python's native format (most reliable here):
        m = re.search(
            r'File\s+"(?P<file>[^"]+\.py)",\s+line\s+(?P<line>\d+)',
            block,
        )
        if m:
            return m.group("file"), int(m.group("line"))
        # Then pytest's short-tb format:
        m = re.search(
            r"^(>\s*)?(?P<file>[^\s:]+\.py):(?P<line>\d+)(?::|\s)",
            block,
            flags=re.MULTILINE,
        )
        if m:
            return m.group("file"), int(m.group("line"))
        # Fall back: pull file/line out of the test_id itself (file::test)
        if "::" in test_id and test_id.endswith(".py") is False:
            file_part = test_id.split("::")[0]
            if file_part.endswith(".py") and os.path.exists(file_part):
                return file_part, None
        return None, None

    @staticmethod
    def _extract_assertion_message(block: str, header_msg: str) -> str:
        # Look for explicit "AssertionError: <msg>" first.
        m = re.search(r"^AssertionError(?::\s*(.*))?$", block, flags=re.MULTILINE)
        if m and m.group(1):
            return m.group(1).strip()
        # pytest short-tb: lines starting with "E "
        m = re.search(r"^E\s+(.*)$", block, flags=re.MULTILINE)
        if m:
            return m.group(1).strip()
        # Bare "AssertionError" (no message) — pull the assert line as context.
        if re.search(r"^AssertionError\s*$", block, flags=re.MULTILINE):
            m = re.search(r"^\s*(assert\s+.+)$", block, flags=re.MULTILINE)
            if m:
                return m.group(1).strip()
        if header_msg:
            return header_msg
        return ""

    # ------------- unittest backend -------------

    def _run_unittest(self, target: Path, *, timeout: int) -> ToolOutput:
        """Run the test suite via stdlib ``unittest``.

        First tries ``unittest discover`` (finds ``unittest.TestCase``
        subclasses). If that discovers 0 tests, falls back to a custom runner
        that also wraps plain ``def test_*`` functions as
        ``unittest.FunctionTestCase`` instances — this is the common
        pytest-style convention that stdlib unittest does not pick up
        natively.
        """
        cmd = [sys.executable, "-m", "unittest", "discover", "-v",
               "-s", str(target), "-t", str(target.parent)]
        rc, out, err = _run(cmd, cwd=str(target.parent), timeout=timeout)
        combined = out + err
        parsed = self._parse_unittest_text(combined, rc)

        # Fallback: if standard discover found nothing, scan the target for
        # plain test functions and run them as FunctionTestCase instances.
        if parsed["collected"] == 0:
            fb = self._run_unittest_functiontestcase(target, timeout=timeout)
            if fb.data.get("collected", 0):
                parsed = fb.data
                combined = combined + "\n--- FunctionTestCase fallback ---\n" + (fb.raw or "")
                rc = rc or fb.data.get("returncode", 0)

        return ToolOutput(
            adapter=self.name,
            available=True,
            data=parsed,
            raw=combined,
        )

    def _run_unittest_functiontestcase(self, target: Path, *, timeout: int) -> ToolOutput:
        """Boot a child interpreter that walks ``target`` for plain test
        functions and runs them as ``unittest.FunctionTestCase``.

        Output goes to stderr via ``TextTestRunner(verbosity=2)`` in the same
        format ``unittest discover -v`` would produce, so the existing parser
        handles it unchanged.
        """
        # Inline bootstrap script. ``repr()`` of the strings makes the script
        # safe against injection from user-controlled paths (quotes are escaped
        # by repr itself).
        script = (
            "import sys, os, unittest\n"
            "target = " + repr(str(target)) + "\n"
            "top = " + repr(str(target.parent)) + "\n"
            "sys.path.insert(0, top)\n"
            "loader = unittest.TestLoader()\n"
            "suite = unittest.TestSuite()\n"
            "imported = 0\n"
            "for root, dirs, files in os.walk(target):\n"
            "    dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__', '.venv', 'venv', 'node_modules')]\n"
            "    for fn in files:\n"
            "        if not (fn.startswith('test_') and fn.endswith('.py')):\n"
            "            continue\n"
            "        path = os.path.join(root, fn)\n"
            "        rel_mod = os.path.relpath(path, top).replace(os.sep, '.')[:-3]\n"
            "        try:\n"
            "            mod = __import__(rel_mod, fromlist=['*'])\n"
            "        except Exception:\n"
            "            continue\n"
            "        imported += 1\n"
            "        suite.addTests(loader.loadTestsFromModule(mod))\n"
            "        for name in dir(mod):\n"
            "            if not name.startswith('test_'):\n"
            "                continue\n"
            "            obj = getattr(mod, name)\n"
            "            if isinstance(obj, type) and issubclass(obj, unittest.TestCase):\n"
            "                continue\n"
            "            if not callable(obj):\n"
            "                continue\n"
            "            suite.addTest(unittest.FunctionTestCase(obj))\n"
            "if imported == 0:\n"
            "    sys.stderr.write('Ran 0 tests in 0.000s\\nNO TESTS RAN\\n')\n"
            "    sys.exit(0)\n"
            "runner = unittest.TextTestRunner(verbosity=2, stream=sys.stderr, buffer=True)\n"
            "result = runner.run(suite)\n"
            "sys.exit(0 if result.wasSuccessful() else 1)\n"
        )
        rc, out, err = _run(
            [sys.executable, "-c", script],
            cwd=str(target.parent),
            timeout=timeout,
        )
        # TextTestRunner writes to the stream we passed (stderr); keep both.
        combined = out + err
        parsed = self._parse_unittest_text(combined, rc)
        return ToolOutput(
            adapter=self.name,
            available=True,
            data=parsed,
            raw=combined,
        )

    @staticmethod
    def _parse_unittest_text(text: str, rc: int) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "skipped": 0,
            "collected": 0,
            "failures": [],
            "errors_list": [],
            "returncode": rc,
            "duration_s": None,
        }
        # Final summary: "Ran 5 tests in 0.001s"
        m = re.search(r"Ran\s+(\d+)\s+tests?\s+in\s+([\d.]+)s", text)
        if m:
            summary["collected"] = int(m.group(1))
            try:
                summary["duration_s"] = float(m.group(2))
            except Exception:
                pass

        # OK / FAILED (errors=) line — e.g. "FAILED (failures=1)" or
        # "FAILED (failures=1, errors=2)" or "OK (skipped=1)".
        m = re.search(r"^(?:OK|FAILED)\s*\(([^)]*)\)\s*$", text, flags=re.MULTILINE)
        if m:
            tail = m.group(1)
            for part in tail.split(","):
                part = part.strip()
                if not part:
                    continue
                kv = part.split("=")
                if len(kv) != 2:
                    continue
                label, count = kv[0].strip(), kv[1].strip()
                if not count.isdigit():
                    continue
                n = int(count)
                base = label.rstrip("s")  # "failures" -> "failure"
                if base in ("failure", "fail"):
                    summary["failed"] = n
                elif base in ("error",):
                    summary["errors"] = n
                elif base == "skipped":
                    summary["skipped"] = n

        # Traceback headers
        # FAIL: test_x (mod.Tests)
        # ERROR: test_y (mod.Tests)
        # The FunctionTestCase fallback emits:
        #   FAIL: unittest.case.FunctionTestCase (test_name)
        #   <docstring line, possibly>
        for m in re.finditer(
            r"^(FAIL|ERROR):\s+([^\n]+?)\s*$",
            text,
            flags=re.MULTILINE,
        ):
            kind = m.group(1).lower()
            label_text = m.group(2).strip()
            # Strip a trailing docstring line if present (FunctionTestCase prints
            # the function's docstring after the FAIL header).
            # Two common shapes:
            #   "test_x (mod.Class)"
            #   "unittest.case.FunctionTestCase (test_name)" + docstring line
            # We only use the first line, so label_text is already single-line.
            m2 = re.match(r"^(\S+?)\s*\(([^)]+)\)\s*$", label_text)
            if m2:
                first_part = m2.group(1)
                in_parens = m2.group(2)
                # If the first_part looks like "unittest.case.FunctionTestCase",
                # then in_parens is the test name.
                if first_part.endswith("FunctionTestCase"):
                    test_name = in_parens
                    cls = first_part
                else:
                    test_name = first_part
                    cls = in_parens
            else:
                # No parentheses — fallback.
                test_name = label_text
                cls = label_text
            block_start = m.end()
            block_end_m = re.search(
                r"^(?:FAIL|ERROR):\s+", text[block_start:], flags=re.MULTILINE,
            )
            block_end = block_start + (block_end_m.start() if block_end_m else len(text) - block_start)
            block = text[block_start:block_end].strip()
            file_line = TestRunnerAdapter._extract_file_line(block, test_name)
            assertion = TestRunnerAdapter._extract_assertion_message(block, "")
            entry = {
                "test": test_name,
                "class": cls,
                "file": file_line[0],
                "line": file_line[1],
                "message": assertion,
                "traceback": block.splitlines()[-12:],
            }
            if kind == "error":
                summary["errors_list"].append(entry)
            else:
                summary["failures"].append(entry)

        return summary


# =============================================================================
# StaticAnalysisAdapter — mypy / ruff / flake8 / pyflakes
# =============================================================================


class StaticAnalysisAdapter:
    name = "static_analysis"

    def __init__(self, tools: Optional[list[str]] = None):
        self.tools = tools or ["mypy", "pyflakes", "ruff", "flake8"]

    def is_available(self) -> bool:
        # pyflakes ships in stdlib? No, but it is optional. The adapter is
        # considered available if ANY of the configured tools is present,
        # OR we can always run a manual AST-based pass.
        for tool in self.tools:
            if _which(tool):
                return True
        # Always available — we have a built-in AST fallback.
        return True

    def run(self, target: str, *, timeout: int = 60) -> ToolOutput:
        target_path = Path(target).resolve()
        if not target_path.exists():
            return ToolOutput(
                adapter=self.name,
                available=False,
                reason=f"target does not exist: {target_path}",
            )

        diagnostics: list[dict[str, Any]] = []
        tools_used: list[str] = []

        for tool in self.tools:
            if tool == "mypy" and _which("mypy"):
                diags = self._run_mypy(target_path, timeout=timeout)
                diagnostics.extend(diags)
                tools_used.append("mypy")
            elif tool == "ruff" and _which("ruff"):
                diags = self._run_ruff(target_path, timeout=timeout)
                diagnostics.extend(diags)
                tools_used.append("ruff")
            elif tool == "flake8" and _which("flake8"):
                diags = self._run_flake8(target_path, timeout=timeout)
                diagnostics.extend(diags)
                tools_used.append("flake8")
            elif tool == "pyflakes" and _which("pyflakes"):
                diags = self._run_pyflakes(target_path, timeout=timeout)
                diagnostics.extend(diags)
                tools_used.append("pyflakes")

        # Always supplement with AST-based checks (these are what the
        # reviewer agent consumes anyway). These are cheap and never fail.
        ast_diags = self._run_ast_fallback(target_path)
        diagnostics.extend(ast_diags)
        tools_used.append("ast_fallback")

        return ToolOutput(
            adapter=self.name,
            available=True,
            data={"diagnostics": diagnostics, "tools_used": tools_used},
            raw=json.dumps(diagnostics, indent=2),
        )

    # ------------- tool backends -------------

    def _run_mypy(self, target: Path, *, timeout: int) -> list[dict[str, Any]]:
        rc, out, err = _run(["mypy", "--no-error-summary", str(target)], timeout=timeout)
        return self._parse_linter_text(out + err, code_prefix="mypy")

    def _run_ruff(self, target: Path, *, timeout: int) -> list[dict[str, Any]]:
        rc, out, err = _run(["ruff", "check", "--output-format=concise", str(target)], timeout=timeout)
        return self._parse_linter_text(out + err, code_prefix="ruff")

    def _run_flake8(self, target: Path, *, timeout: int) -> list[dict[str, Any]]:
        rc, out, err = _run(["flake8", "--format=%(path)s:%(row)d:%(col)d: [%(code)s] %(text)s", str(target)], timeout=timeout)
        return self._parse_linter_text(out + err, code_prefix="flake8")

    def _run_pyflakes(self, target: Path, *, timeout: int) -> list[dict[str, Any]]:
        rc, out, err = _run(["pyflakes", str(target)], timeout=timeout)
        return self._parse_linter_text(out + err, code_prefix="pyflakes")

    @staticmethod
    def _parse_linter_text(text: str, *, code_prefix: str) -> list[dict[str, Any]]:
        diagnostics: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Generic: path:line:col: [CODE] message
            m = re.match(
                r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s*(?:\[(?P<code>[^\]]+)\]\s*)?(?P<msg>.*)$",
                line,
            )
            if not m:
                continue
            try:
                line_no = int(m.group("line"))
            except ValueError:
                continue
            diagnostics.append({
                "file": m.group("file"),
                "line": line_no,
                "column": int(m.group("col")) if m.group("col") and m.group("col").isdigit() else None,
                "code": (code_prefix + ":" + (m.group("code") or "").strip(":")).strip(":"),
                "message": m.group("msg").strip(),
                "tool": code_prefix,
            })
        return diagnostics

    # ------------- AST fallback -------------

    def _run_ast_fallback(self, target: Path) -> list[dict[str, Any]]:
        """Cheap pure-stdlib diagnostics: unused imports, syntax errors.

        The richer AST checks live in the Reviewer agent so they can carry the
        full review stack + evidence. This fallback just covers things a linter
        would also report.
        """
        out: list[dict[str, Any]] = []
        for py_file in target.rglob("*.py"):
            try:
                src = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(src, filename=str(py_file))
            except SyntaxError as e:
                out.append({
                    "file": str(py_file),
                    "line": e.lineno or 0,
                    "column": e.offset,
                    "code": "ast-fallback:E999",
                    "message": f"SyntaxError: {e.msg}",
                    "tool": "ast_fallback",
                })
                continue
            # Unused imports via Name/Import tracking
            imported: dict[str, int] = {}
            used: set[str] = set()
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
                elif isinstance(node, ast.Name):
                    if isinstance(node.ctx, ast.Load):
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
                    out.append({
                        "file": str(py_file),
                        "line": ln,
                        "column": None,
                        "code": "ast-fallback:F401",
                        "message": f"imported but unused: {name!r}",
                        "tool": "ast_fallback",
                    })
        return out


# =============================================================================
# CoverageAdapter
# =============================================================================


class CoverageAdapter:
    name = "coverage"

    def is_available(self) -> bool:
        # coverage.py OR pytest-cov being available is the signal.
        if _which("coverage"):
            return True
        try:
            import coverage  # type: ignore  # noqa: F401
            return True
        except Exception:
            return False

    def run(self, target: str, *, timeout: int = 120) -> ToolOutput:
        if not self.is_available():
            return ToolOutput(
                adapter=self.name,
                available=False,
                reason="coverage.py not available (install coverage or pytest-cov)",
            )

        target_path = Path(target).resolve()
        with tempfile.TemporaryDirectory() as td:
            data_file = Path(td) / ".coverage"
            rc, out, err = _run(
                [sys.executable, "-m", "coverage", "run", "--data-file", str(data_file),
                 "-m", "pytest", "-q", str(target_path)],
                cwd=str(target_path.parent),
                timeout=timeout,
            )
            _, rep_out, rep_err = _run(
                [sys.executable, "-m", "coverage", "report", "--data-file", str(data_file),
                 "--format=json", f"--include={target_path}/*"],
                cwd=str(target_path.parent),
                timeout=timeout,
            )
            try:
                j = json.loads(rep_out)
            except Exception:
                return ToolOutput(
                    adapter=self.name,
                    available=True,
                    reason="coverage ran but JSON report unparseable",
                    data={"percent": None},
                    raw=out + err + rep_out + rep_err,
                )
            pct = j.get("totals", {}).get("percent_covered")
            files_cov = {
                f: {"percent": v.get("summary", {}).get("percent_covered"),
                    "missing_lines": v.get("missing_lines", [])}
                for f, v in j.get("files", {}).items()
            }
            return ToolOutput(
                adapter=self.name,
                available=True,
                data={"percent": pct, "files": files_cov, "returncode": rc},
                raw=out + err + rep_out + rep_err,
            )


# =============================================================================
# SecretScanAdapter — regex-based, redacts secrets
# =============================================================================


# Patterns are conservative — each is anchored to look like a real secret
# assignment, not random base64 in code.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("aws_access_key_id", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "AWS access key id"),
    ("aws_secret_access_key",
     re.compile(r"(?i)aws[_\-]?secret[_\-]?access[_\-]?key\s*[:=]\s*['\"]([A-Za-z0-9/+=]{40})['\"]"),
     "AWS secret access key"),
    ("private_key_block",
     re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
     "PEM private key block"),
    ("generic_api_token",
     re.compile(r"(?i)(?:api[_\-]?token|access[_\-]?token|auth[_\-]?token)\s*[:=]\s*['\"]([A-Za-z0-9_\-]{16,})['\"]"),
     "Generic API/auth token"),
    ("hardcoded_password",
     re.compile(r"(?i)(?:password|passwd|pwd)\s*[:=]\s*['\"]([^'\"\s]{6,})['\"]"),
     "Hardcoded password"),
    ("db_connection_string",
     re.compile(r"(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis)://[^\s'\"]*:[^\s'\"]*@"),
     "DB connection string with credentials"),
    ("github_pat",
     re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b"),
     "GitHub personal access token"),
    ("slack_token",
     re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"),
     "Slack token"),
]


class SecretScanAdapter:
    name = "secret_scan"

    def __init__(self, redact: bool = True):
        self.redact = redact

    def is_available(self) -> bool:
        return True  # regex-based, always available

    def run(self, target: str, *, timeout: int = 30) -> ToolOutput:
        target_path = Path(target).resolve()
        if not target_path.exists():
            return ToolOutput(
                adapter=self.name,
                available=False,
                reason=f"target does not exist: {target_path}",
            )

        findings: list[dict[str, Any]] = []
        for f in self._iter_text_files(target_path):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for kind, regex, desc in SECRET_PATTERNS:
                    m = regex.search(line)
                    if not m:
                        continue
                    matched = m.group(0)
                    redacted = self._redact(matched)
                    findings.append({
                        "kind": kind,
                        "file": str(f),
                        "line": lineno,
                        "redacted_match": redacted,
                        "description": desc,
                    })

        return ToolOutput(
            adapter=self.name,
            available=True,
            data={"findings": findings, "count": len(findings)},
            raw=json.dumps(findings, indent=2),
        )

    @staticmethod
    def _iter_text_files(target: Path):
        if target.is_file():
            yield target
            return
        skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
                     ".pytest_cache", ".ruff_cache", "reports"}
        for p in target.rglob("*"):
            if not p.is_file():
                continue
            parts = set(p.parts)
            if parts & skip_dirs:
                continue
            if p.suffix in {".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin"}:
                continue
            yield p

    def _redact(self, value: str) -> str:
        if not self.redact:
            return "[REDACTED]"
        if len(value) <= 8:
            return "*" * len(value)
        return value[:4] + "..." + value[-4:]