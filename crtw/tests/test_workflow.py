"""Unit tests for the orchestration logic.

These run with stdlib ``unittest`` — no extra deps.
"""
from __future__ import annotations

import tempfile
import unittest
from typing import Any

from crtw.agents.base import ReviewAgent
from crtw.contracts import (
    Finding,
    GateVerdict,
    SEVERITY_WEIGHTS,
    StageResult,
    StageStatus,
    utcnow_iso,
)
from crtw.orchestrator import (
    Orchestrator,
    compute_gate,
    load_config,
    topo_order,
)


# =============================================================================
# Helpers
# =============================================================================


def _finding(sev: str, file: str = "x.py", line: int = 1, title: str = "t",
             confidence: float = 1.0) -> Finding:
    from crtw.contracts import Severity
    return Finding(
        severity=Severity(sev),
        stage="t",
        agent_id="t",
        file=file,
        line=line,
        title=title,
        confidence=confidence,
    )


# A target dir used by the isolation tests. Empty so adapters are harmless.
TMP_TARGET = tempfile.mkdtemp(prefix="crtw-test-")


# =============================================================================
# Gate verdict tests — threshold boundaries
# =============================================================================


class GateVerdictTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "gate": {
                "severity_weights": {k: v for k, v in SEVERITY_WEIGHTS.items()},
                "block_threshold": 10,
                "review_threshold": 5,
                "block_on_any_blocker": True,
                "review_on_any_critical_or_major": True,
            }
        }

    def test_passed_when_only_minor(self):
        # 4 MINOR findings = 4 * 1 = 4 < 5
        findings = [_finding("MINOR") for _ in range(4)]
        d = compute_gate(findings, self.cfg)
        self.assertEqual(d.verdict, GateVerdict.PASSED)
        self.assertEqual(d.weighted_score, 4)

    def test_review_threshold_boundary_minor(self):
        # 5 MINOR = score 5 -> needs_review
        findings = [_finding("MINOR") for _ in range(5)]
        d = compute_gate(findings, self.cfg)
        self.assertEqual(d.verdict, GateVerdict.NEEDS_REVIEW)
        self.assertEqual(d.weighted_score, 5)

    def test_block_on_any_blocker(self):
        # One BLOCKER alone should BLOCK even at low weight.
        findings = [_finding("BLOCKER")]
        d = compute_gate(findings, self.cfg)
        self.assertEqual(d.verdict, GateVerdict.BLOCKED)
        self.assertIn(findings[0], d.blocking_findings)

    def test_review_threshold_boundary_major(self):
        # 1 MAJOR + 1 MINOR -> 3+1=4 -> needs_review (MAJOR triggers review_on_any).
        findings = [_finding("MAJOR"), _finding("MINOR")]
        d = compute_gate(findings, self.cfg)
        self.assertEqual(d.verdict, GateVerdict.NEEDS_REVIEW)
        self.assertEqual(d.weighted_score, 4)

    def test_block_threshold(self):
        # 2 CRITICAL = 2*5 = 10 -> block_threshold met
        findings = [_finding("CRITICAL"), _finding("CRITICAL")]
        d = compute_gate(findings, self.cfg)
        self.assertEqual(d.verdict, GateVerdict.BLOCKED)
        self.assertEqual(d.weighted_score, 10)

    def test_no_blocker_but_below_review_threshold(self):
        # 1 CRITICAL only = 5 score -> needs_review (>= review_threshold)
        d = compute_gate([_finding("CRITICAL")], self.cfg)
        self.assertEqual(d.verdict, GateVerdict.NEEDS_REVIEW)

    def test_info_is_zero_weight(self):
        d = compute_gate([_finding("INFO") for _ in range(100)], self.cfg)
        self.assertEqual(d.weighted_score, 0)
        self.assertEqual(d.verdict, GateVerdict.PASSED)


# =============================================================================
# Stage isolation tests
# =============================================================================


class _NoopAdaptersAgent(ReviewAgent):
    """Test agent base that does NOT run any adapters (research is no-op)."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.adapters = {}  # explicit: no adapter runs

    def research(self, target: str):
        return {"target": target, "adapters": {}}


class CrashingAgent(_NoopAdaptersAgent):
    agent_id = "test:crash"
    name = "crash"

    def reason(self, evidence):
        raise RuntimeError("agent exploded")


class HealthyAgent(_NoopAdaptersAgent):
    agent_id = "test:healthy"
    name = "healthy"

    def reason(self, evidence):
        return [_finding("MINOR", title="ok")]


class FlakyAgent(_NoopAdaptersAgent):
    """Fails first run, succeeds on retry. Used by retry test."""
    agent_id = "test:flaky"
    name = "flaky"
    attempts = 0

    def reason(self, evidence):
        type(self).attempts += 1
        if type(self).attempts == 1:
            raise ConnectionError("connection refused")
        return []


class StageIsolationTests(unittest.TestCase):
    def test_crashing_stage_yields_run(self):
        cfg = {
            "stages": [
                {"name": "healthy", "agent": "crtw.tests.test_workflow:HealthyAgent",
                 "depends_on": [], "timeout_s": 10, "retries": 0},
                {"name": "crash", "agent": "crtw.tests.test_workflow:CrashingAgent",
                 "depends_on": [], "timeout_s": 10, "retries": 0},
            ],
            "gate": {"severity_weights": dict(SEVERITY_WEIGHTS),
                     "block_threshold": 100, "review_threshold": 100,
                     "block_on_any_blocker": True, "review_on_any_critical_or_major": True},
            "orchestration": {"max_workers": 2, "retry_backoff_base_s": 0.0},
        }
        orch = Orchestrator(cfg)
        run = orch.run(TMP_TARGET)
        self.assertEqual(len(run.stages), 2)
        statuses = {s.stage: s.status for s in run.stages}
        self.assertEqual(statuses["healthy"], StageStatus.PASSED)
        self.assertEqual(statuses["crash"], StageStatus.ERROR)
        # Gate should still be there even though a stage crashed.
        self.assertIsNotNone(run.gate)

    def test_retries_with_transient_error(self):
        # Reset shared counter (other tests in this module may have used it).
        FlakyAgent.attempts = 0
        cfg = {
            "stages": [
                {"name": "flaky", "agent": "crtw.tests.test_workflow:FlakyAgent",
                 "depends_on": [], "timeout_s": 10, "retries": 1},
            ],
            "gate": {"severity_weights": dict(SEVERITY_WEIGHTS),
                     "block_threshold": 100, "review_threshold": 100,
                     "block_on_any_blocker": True, "review_on_any_critical_or_major": True},
            "orchestration": {"max_workers": 1, "retry_backoff_base_s": 0.0},
        }
        orch = Orchestrator(cfg)
        run = orch.run(TMP_TARGET)
        self.assertEqual(run.stages[0].status, StageStatus.PASSED)
        # 2 attempts: first ConnectionError, second succeeds.
        self.assertEqual(FlakyAgent.attempts, 2)


# =============================================================================
# Topological order tests
# =============================================================================


class TopoOrderTests(unittest.TestCase):
    def test_independent_levels(self):
        stages = [
            {"name": "a", "depends_on": []},
            {"name": "b", "depends_on": []},
            {"name": "c", "depends_on": ["a"]},
            {"name": "d", "depends_on": ["b", "a"]},
        ]
        levels = topo_order(stages)
        names_at_level = [{s["name"] for s in lvl} for lvl in levels]
        self.assertIn({"a", "b"}, names_at_level)
        flat = [s["name"] for lvl in levels for s in lvl]
        self.assertLess(flat.index("a"), flat.index("c"))
        self.assertLess(flat.index("a"), flat.index("d"))
        self.assertLess(flat.index("b"), flat.index("d"))

    def test_unknown_dependency(self):
        stages = [{"name": "a", "depends_on": ["x"]}]
        with self.assertRaises(ValueError):
            topo_order(stages)

    def test_cycle_detected(self):
        stages = [
            {"name": "a", "depends_on": ["b"]},
            {"name": "b", "depends_on": ["a"]},
        ]
        with self.assertRaises(ValueError):
            topo_order(stages)


# =============================================================================
# Dedupe + severity calibration in review()
# =============================================================================


class ReviewTests(unittest.TestCase):
    def test_dedupe_keeps_highest_severity(self):
        agent = HealthyAgent()
        findings = [
            _finding("MINOR", file="x.py", line=1, title="dup"),
            _finding("MAJOR", file="x.py", line=1, title="dup"),
            _finding("INFO", file="x.py", line=1, title="dup"),
        ]
        out = agent.review(findings)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].severity.value, "MAJOR")

    def test_low_confidence_dropped(self):
        agent = HealthyAgent()
        findings = [
            _finding("MINOR", title="noise", confidence=0.3),
            _finding("MAJOR", title="real", confidence=0.8),
        ]
        out = agent.review(findings)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].title, "real")

    def test_distinct_titles_kept(self):
        agent = HealthyAgent()
        findings = [
            _finding("MAJOR", title="a"),
            _finding("MAJOR", title="b"),
        ]
        out = agent.review(findings)
        self.assertEqual(len(out), 2)


# =============================================================================
# Config loading
# =============================================================================


class ConfigLoadTests(unittest.TestCase):
    def test_load_default_when_no_path(self):
        cfg = load_config("/nonexistent/path.yaml")
        self.assertIn("stages", cfg)
        self.assertIn("gate", cfg)

    def test_load_real_config(self):
        cfg = load_config("crtw/workflow.yaml")
        self.assertGreaterEqual(len(cfg["stages"]), 4)
        self.assertEqual(cfg["gate"]["block_threshold"], 10)


if __name__ == "__main__":
    unittest.main()