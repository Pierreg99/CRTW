"""Debugging Agent — AGI-3 S6-AGI3-014-DEBUGGER.

Takes the test runner output (passed via stage inputs) and extracts root cause
information per failure, distinguishing product bugs from test bugs.

The agent looks at each failing traceback, finds the topmost frame that is NOT
inside the test module, and emits a Finding with file:line of the suspected
production-code culprit.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

from crtw.agents.base import ReviewAgent
from crtw.contracts import Finding, Severity


def _is_test_module(path: str | None) -> bool:
    if not path:
        return False
    p = path
    return (
        "/tests/" in p
        or p.endswith("test_*.py")
        or p.split("/")[-1].startswith("test_")
        or p.split("/")[-1].endswith("_test.py")
        or "/test/" in p.lower()
    )


def _first_product_frame(traceback: list[str]) -> tuple[str | None, int | None]:
    """Walk the traceback lines and return the first frame whose file is NOT
    a test module."""
    for line in traceback:
        m = re.match(r"(?:>\s*)?(?P<file>[^\s:]+\.py):(?P<line>\d+)(?::|\s|$)", line)
        if not m:
            continue
        file_ = m.group("file")
        try:
            ln = int(m.group("line"))
        except ValueError:
            continue
        if not _is_test_module(file_):
            return file_, ln
    return None, None


def _classify_bug(traceback: list[str], message: str) -> str:
    """Heuristic classification: product bug vs test bug.

    - AssertionError raised inside the test function itself (file in tests/)
      -> test bug (assertion / expectation wrong).
    - Any other exception, or AssertionError raised in product module -> product bug.
    """
    last_file = None
    for line in traceback:
        m = re.match(r"(?:>\s*)?(?P<file>[^\s:]+\.py):(?P<line>\d+)(?::|\s|$)", line)
        if m:
            last_file = m.group("file")
    if last_file and _is_test_module(last_file) and "AssertionError" in (traceback[0] if traceback else ""):
        return "test"
    return "product"


class DebuggingAgent(ReviewAgent):
    agent_id = "S6-AGI3-014-DEBUGGER"
    name = "debug"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.adapters.pop("test_runner", None)
        self.adapters.pop("coverage", None)
        self.adapters.pop("secret_scan", None)
        self.adapters.pop("static_analysis", None)

    def reason(self, evidence: dict[str, Any]) -> list[Finding]:
        out: list[Finding] = []
        failures, errors = self._collect_failures(evidence)

        if not failures and not errors:
            return out

        for fail in failures + errors:
            tb = fail.get("traceback") or []
            message = fail.get("message", "") or ""
            file_, line = _first_product_frame(tb)
            kind = _classify_bug(tb, message)

            sev = Severity.CRITICAL if kind == "product" else Severity.MAJOR
            target_file = file_ or fail.get("file")
            target_line = line or fail.get("line")
            title = f"Root cause ({kind} bug): {fail.get('test', '?')}"
            detail_lines = [
                f"Test: {fail.get('test', '?')}",
                f"Assertion/Message: {message or '(none)'}",
                f"Suspected production frame: {file_}:{line}" if file_ else "Suspected production frame: (unknown)",
                f"Classification: {kind} bug.",
            ]
            out.append(Finding(
                severity=sev,
                stage=self.name,
                agent_id=self.agent_id,
                file=target_file,
                line=target_line,
                title=title,
                detail="\n".join(detail_lines),
                evidence="\n".join(tb[-12:])[:600],
                remediation=(
                    "Inspect the failing frame in production code. "
                    "If it's a test bug, fix the assertion or test fixture."
                ),
                confidence=0.85,
                tags=["debug", kind],
            ))

        # Group related failures by message hash.
        grouped = self._group_by_message(failures + errors)
        if len(grouped) > 1:
            out.append(Finding(
                severity=Severity.MINOR,
                stage=self.name,
                agent_id=self.agent_id,
                title=f"{len(grouped)} distinct failure signatures",
                detail="Failures cluster into distinct groups; addressing the largest group first usually unblocks the rest.",
                evidence=str(list(grouped.keys())[:5]),
                remediation="Group and address failures by error signature.",
                confidence=0.7,
                tags=["debug", "grouping"],
            ))

        return out

    def _collect_failures(self, evidence: dict[str, Any]) -> tuple[list[Finding], list[Finding]]:
        """Pull (failures, errors) from the test stage's CRITICAL findings.

        Order of sources:
        1. ``evidence["prior_stages"]["test"]["findings"]`` — propagated by the
         orchestrator from the test stage's findings (preferred: findings
         already carry file/line/evidence).
        2. ``evidence["adapters"]["test_runner"]["data"]["failures"]`` —
         re-runs the adapter locally if no prior stage data is available.
        """
        prior = (evidence.get("prior_stages") or {}).get("test") or {}
        if prior:
            test_findings = prior.get("findings") or []
            crit = [
                f for f in test_findings
                if f.get("severity") in ("CRITICAL", "BLOCKER")
            ]
            if crit:
                # Synthesise failures/errors lists shaped like the adapter's.
                failures: list[dict[str, Any]] = []
                errors: list[dict[str, Any]] = []
                for f in crit:
                    entry = {
                        "test": f.get("title", "?"),
                        "file": f.get("file"),
                        "line": f.get("line"),
                        "message": f.get("detail") or f.get("title") or "",
                        "traceback": (f.get("evidence") or "").splitlines()[-12:],
                    }
                    sev = f.get("severity")
                    if sev == "BLOCKER":
                        errors.append(entry)
                    else:
                        failures.append(entry)
                return failures, errors

        runner = evidence.get("adapters", {}).get("test_runner", {}) or {}
        data = runner.get("data") or {}
        return data.get("failures", []) or [], data.get("errors_list", []) or []

    def _group_by_message(self, failures: list[dict[str, Any]]) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for f in failures + []:
            sig = (f.get("message") or "no-message").splitlines()[0][:80]
            groups.setdefault(sig, []).append(f.get("test", "?"))
        return groups