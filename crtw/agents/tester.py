"""Test Engineering Agent — AGI-3 S3-AGI3-009-TESTER.

Runs the test suite, converts raw failures into structured Findings, flags
coverage gaps and missing tests, and flags tests without assertions (suspect
flaky / no-op tests).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from crtw.agents.base import ReviewAgent
from crtw.contracts import Finding, Severity


class TestEngineeringAgent(ReviewAgent):
    agent_id = "S3-AGI3-009-TESTER"
    name = "test"

    def __init__(self, **kw):
        super().__init__(**kw)
        # Tester mostly uses test_runner + coverage.
        self.adapters.pop("secret_scan", None)
        self.adapters.pop("static_analysis", None)

    def reason(self, evidence: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        out.extend(self._findings_from_runner(evidence))
        out.extend(self._findings_from_coverage(evidence))
        out.extend(self._findings_no_assertions(evidence))
        out.extend(self._findings_missing_tests(evidence))
        return out

    # --- test runner output ---

    def _findings_from_runner(self, evidence: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        runner = evidence.get("adapters", {}).get("test_runner", {})
        data = runner.get("data") or {}
        if not data and not runner.get("available", True):
            return [Finding(
                severity=Severity.MAJOR,
                stage=self.name,
                agent_id=self.agent_id,
                title="Test runner unavailable",
                detail=runner.get("reason", "test runner did not run"),
                evidence=runner.get("reason", ""),
                remediation="Install pytest or unittest (stdlib).",
                confidence=0.9,
                tags=["test-runner"],
            )]
        collected = data.get("collected", 0)
        failures = data.get("failures", []) or []
        errors = data.get("errors_list", []) or []

        if collected == 0:
            out.append(Finding(
                severity=Severity.MAJOR,
                stage=self.name,
                agent_id=self.agent_id,
                title="No tests collected",
                detail="pytest/unittest did not discover any tests in the target.",
                evidence=str(data.get("returncode", "")),
                remediation="Add at least one test_* function / class.",
                confidence=0.95,
                tags=["tests", "missing"],
            ))

        for f in failures:
            out.append(Finding(
                severity=Severity.CRITICAL,
                stage=self.name,
                agent_id=self.agent_id,
                file=f.get("file"),
                line=f.get("line"),
                title=f"Test failure: {f.get('test', '?')}",
                detail=f.get("message", "") or "Test failed",
                evidence="\n".join(f.get("traceback") or [])[:600],
                remediation="Read the traceback, fix the production code or the test expectation.",
                confidence=0.95,
                tags=["tests", "failure"],
            ))

        for e in errors:
            out.append(Finding(
                severity=Severity.CRITICAL,
                stage=self.name,
                agent_id=self.agent_id,
                file=e.get("file"),
                line=e.get("line"),
                title=f"Test error: {e.get('test', '?')}",
                detail=e.get("message", "") or "Test errored during collection",
                evidence="\n".join(e.get("traceback") or [])[:600],
                remediation="Fix the collection/import error.",
                confidence=0.95,
                tags=["tests", "error"],
            ))

        return out

    # --- coverage ---

    def _findings_from_coverage(self, evidence: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        cov = evidence.get("adapters", {}).get("coverage", {})
        if not cov.get("available", True):
            return out
        data = cov.get("data") or {}
        pct = data.get("percent")
        if pct is None:
            return out
        if pct < 50.0:
            out.append(Finding(
                severity=Severity.MAJOR,
                stage=self.name,
                agent_id=self.agent_id,
                title=f"Low test coverage: {pct:.1f}%",
                detail=f"Coverage below 50% threshold. Add tests for uncovered branches.",
                evidence=f"coverage: {pct:.1f}%",
                remediation="Add tests for uncovered modules.",
                confidence=0.9,
                tags=["coverage"],
            ))
        elif pct < 80.0:
            out.append(Finding(
                severity=Severity.MINOR,
                stage=self.name,
                agent_id=self.agent_id,
                title=f"Coverage below 80%: {pct:.1f}%",
                detail="Coverage between 50-80%.",
                evidence=f"coverage: {pct:.1f}%",
                remediation="Improve coverage on critical modules.",
                confidence=0.7,
                tags=["coverage"],
            ))
        return out

    # --- no-assertion tests ---

    def _findings_no_assertions(self, evidence: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        target = evidence.get("target")
        if not target:
            return out
        target_path = Path(target).resolve()
        # Collect candidate test files (test_*.py or *_test.py).
        for f in target_path.rglob("test_*.py"):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(text, filename=str(f))
            except (OSError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test_"):
                    continue
                body_src = ast.unparse(node) if hasattr(ast, "unparse") else ""
                # Match either the ``assert`` statement OR any unittest-style
                # assertion method call (``self.assertEqual(...)``,
                # ``assertRaises(...)``, ``assertTrue(...)``, etc.).
                if not re.search(
                    r"(?:\bassert\b)|(?:(?:^|\W)assert[A-Z]\w*\s*\()",
                    body_src,
                ):
                    out.append(Finding(
                        severity=Severity.MAJOR,
                        stage=self.name,
                        agent_id=self.agent_id,
                        file=str(f),
                        line=node.lineno,
                        title=f"Test `{node.name}` has no assertions",
                        detail="Tests with no `assert` always pass — flaky / no-op test.",
                        evidence=f"def {node.name}(...)",
                        remediation="Add at least one `assert ...` to validate behaviour.",
                        confidence=0.85,
                        tags=["tests", "no-assertion"],
                    ))
        return out

    # --- untested public functions ---

    def _findings_missing_tests(self, evidence: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        target = evidence.get("target")
        if not target:
            return out
        target_path = Path(target).resolve()

        # Gather public symbols defined in non-test modules. Only top-level
        # functions and module-level ALL_CAPS / public names count; local
        # variables inside functions are excluded (they aren't public API).
        public_symbols: set[str] = set()
        for f in target_path.rglob("*.py"):
            if "/tests/" in str(f) or f.name.startswith("test_") or f.name.endswith("_test.py"):
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8", errors="replace"), filename=str(f))
            except (OSError, SyntaxError):
                continue
            for node in tree.body:  # top-level only
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if not node.name.startswith("_"):
                        public_symbols.add(node.name)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and not tgt.id.startswith("_"):
                            public_symbols.add(tgt.id)
                elif isinstance(node, ast.ClassDef):
                    if not node.name.startswith("_"):
                        public_symbols.add(node.name)

        # Gather references in test files.
        tested_symbols: set[str] = set()
        for f in target_path.rglob("*.py"):
            if not (f.name.startswith("test_") or f.name.endswith("_test.py")):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for name in public_symbols:
                if re.search(rf"\b{re.escape(name)}\b", text):
                    tested_symbols.add(name)

        untested = public_symbols - tested_symbols
        for name in sorted(untested):
            out.append(Finding(
                severity=Severity.MAJOR,
                stage=self.name,
                agent_id=self.agent_id,
                file=str(target_path),
                title=f"Untested public symbol: `{name}`",
                detail="No test references this public symbol.",
                evidence=f"public symbol `{name}` not referenced in any test_*.py",
                remediation="Add a unit test that exercises this function.",
                confidence=0.6,
                tags=["tests", "coverage-gap"],
            ))
        return out