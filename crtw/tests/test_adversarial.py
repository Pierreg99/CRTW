"""Adversarial tests for the CRTW orchestrator.

These tests are intentionally written to FAIL if the system is broken.
They cover boundary conditions and edge cases not (or only partially) tested
by the original suite. They do NOT fix the system — they only assert it.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from crtw.agents.base import ReviewAgent
from crtw.contracts import (
    Finding,
    GateVerdict,
    SEVERITY_WEIGHTS,
    Severity,
    StageStatus,
)
from crtw.orchestrator import Orchestrator, compute_gate, topo_order
from crtw.report import write_reports


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_finding(sev, file="x.py", line=1, title="t", confidence=1.0):
    return Finding(
        severity=sev,
        stage="t",
        agent_id="t",
        file=file,
        line=line,
        title=title,
        confidence=confidence,
    )


def _base_cfg():
    return {
        "gate": {
            "severity_weights": {k.value: v for k, v in SEVERITY_WEIGHTS.items()},
            "block_threshold": 10,
            "review_threshold": 5,
            "block_on_any_blocker": True,
            "review_on_any_critical_or_major": True,
        }
    }


# ---------------------------------------------------------------------------
# Boundary conditions on the gate verdict
# ---------------------------------------------------------------------------


class GateBoundaryTests(unittest.TestCase):
    def test_score_equals_block_threshold_via_minor(self):
        # 10 MINOR * 1 = 10 — exactly == block_threshold should BLOCK.
        findings = [_mk_finding(Severity.MINOR) for _ in range(10)]
        d = compute_gate(findings, _base_cfg())
        self.assertEqual(d.weighted_score, 10)
        self.assertEqual(
            d.verdict,
            GateVerdict.BLOCKED,
            f"score==block_threshold (10) MUST yield BLOCKED, got {d.verdict.value}",
        )

    def test_score_one_below_block_threshold(self):
        # 9 MINOR * 1 = 9 — one below block_threshold — should be NEEDS_REVIEW
        # (still >= review_threshold=5), NOT blocked.
        findings = [_mk_finding(Severity.MINOR) for _ in range(9)]
        d = compute_gate(findings, _base_cfg())
        self.assertEqual(d.weighted_score, 9)
        self.assertNotEqual(
            d.verdict,
            GateVerdict.BLOCKED,
            f"score=9 (one below block_threshold=10) MUST NOT block; got {d.verdict.value}",
        )
        self.assertEqual(d.verdict, GateVerdict.NEEDS_REVIEW)

    def test_score_equals_review_threshold(self):
        # 5 MINOR = 5 — exactly == review_threshold should NEEDS_REVIEW.
        findings = [_mk_finding(Severity.MINOR) for _ in range(5)]
        d = compute_gate(findings, _base_cfg())
        self.assertEqual(d.weighted_score, 5)
        self.assertEqual(
            d.verdict,
            GateVerdict.NEEDS_REVIEW,
            f"score==review_threshold (5) MUST yield NEEDS_REVIEW, got {d.verdict.value}",
        )

    def test_score_one_below_review_threshold(self):
        # 4 MINOR = 4 — one below review_threshold — should PASS.
        findings = [_mk_finding(Severity.MINOR) for _ in range(4)]
        d = compute_gate(findings, _base_cfg())
        self.assertEqual(d.weighted_score, 4)
        self.assertEqual(
            d.verdict,
            GateVerdict.PASSED,
            f"score=4 (one below review_threshold=5) MUST pass, got {d.verdict.value}",
        )


# ---------------------------------------------------------------------------
# Robustness of gate computation against weird / hostile findings
# ---------------------------------------------------------------------------


class GateRobustnessTests(unittest.TestCase):
    def test_unknown_severity_via_model_construct_does_not_crash_gate(self):
        # Build a Finding that bypasses Pydantic validation by using
        # model_construct (no validator). severity=None must NOT crash the
        # gate computation (the user's spec).
        bad = Finding.model_construct(
            id="f-bad",
            severity=None,           # type: ignore[arg-type]
            stage="t",
            agent_id="t",
            file="a.py",
            line=1,
            title="bad",
            detail="",
            evidence="",
            remediation="",
            confidence=1.0,
            tags=[],
        )
        good = _mk_finding(Severity.MAJOR)
        # Should not raise.
        try:
            d = compute_gate([bad, good], _base_cfg())
        except Exception as e:  # noqa: BLE001
            self.fail(f"compute_gate crashed on finding with severity=None: {type(e).__name__}: {e}")
        # The good finding is MAJOR (weight 3). Even if the bad finding is
        # skipped or zero-weighted, the run is non-blocking.
        self.assertIsNotNone(d)
        self.assertEqual(d.verdict, GateVerdict.NEEDS_REVIEW)


# ---------------------------------------------------------------------------
# Finding serialization round-trip
# ---------------------------------------------------------------------------


class FindingSerializationTests(unittest.TestCase):
    def test_finding_with_none_file_and_none_line_round_trips(self):
        f = _mk_finding(Severity.MAJOR, file=None, line=None)
        # dump_json must produce valid JSON with nulls, not crash.
        raw = f.model_dump_json()
        obj = json.loads(raw)
        self.assertIsNone(obj["file"])
        self.assertIsNone(obj["line"])
        # Round-trip back to Finding.
        restored = Finding.model_validate_json(raw)
        self.assertIsNone(restored.file)
        self.assertIsNone(restored.line)


# ---------------------------------------------------------------------------
# Orchestrator behaviour under hostile inputs
# ---------------------------------------------------------------------------


class _NoopAdaptersAgent(ReviewAgent):
    """Minimal agent: no adapter runs, research() returns an empty dict."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.adapters = {}

    def research(self, target: str):
        return {"target": target, "adapters": {}, "prior_stages": {}}


class _HealthyAgent(_NoopAdaptersAgent):
    agent_id = "adv:healthy"
    name = "healthy"

    def reason(self, evidence):
        return [_mk_finding(Severity.MINOR, title="ok")]


class _CrashAgent(_NoopAdaptersAgent):
    agent_id = "adv:crash"
    name = "crash"

    def reason(self, evidence):
        raise RuntimeError("agent exploded")


class _FailNTimesAgent(_NoopAdaptersAgent):
    """Fails N times then succeeds."""

    agent_id = "adv:failN"
    name = "failn"
    attempts = 0

    def reason(self, evidence):
        type(self).attempts += 1
        if type(self).attempts <= self.fail_n:
            # RuntimeError with "connection" so _is_transient_error fires.
            raise ConnectionError(f"connection refused attempt {type(self).attempts}")
        return [_mk_finding(Severity.MINOR, title="recovered")]


class _HangAgent(_NoopAdaptersAgent):
    """Sleeps far longer than the configured timeout."""

    agent_id = "adv:hang"
    name = "hang"

    def reason(self, evidence):
        time.sleep(self.hang_s)
        return []


def _cfg_for(stages, **overrides):
    cfg = {
        "stages": stages,
        "gate": {"severity_weights": dict(SEVERITY_WEIGHTS),
                 "block_threshold": 100, "review_threshold": 100,
                 "block_on_any_blocker": True,
                 "review_on_any_critical_or_major": True},
        "orchestration": {"max_workers": 4, "retry_backoff_base_s": 0.0},
    }
    for k, v in overrides.items():
        cfg[k] = v
    return cfg


class OrchestratorHostileInputsTests(unittest.TestCase):
    def test_empty_stage_list_does_not_yield_a_run(self):
        # The spec says: Orchestrator with an empty stage list must "still
        # return a run". Current implementation raises ValueError.
        cfg = _cfg_for(stages=[])
        orch = Orchestrator(cfg)
        try:
            run = orch.run(tempfile.mkdtemp(prefix="adv-empty-"))
        except ValueError as e:
            self.fail(
                f"Orchestrator.run on empty stage list raised ValueError "
                f"instead of returning a WorkflowRun: {e}"
            )
        # If it didn't raise, the run should be valid (no stages, gate still
        # computed).
        self.assertEqual(len(run.stages), 0)
        self.assertIsNotNone(run.gate)

    def test_all_stages_crash_run_still_returned(self):
        cfg = _cfg_for(stages=[
            {"name": "c1", "agent": "crtw.tests.test_adversarial:_CrashAgent",
             "depends_on": [], "timeout_s": 5, "retries": 0},
            {"name": "c2", "agent": "crtw.tests.test_adversarial:_CrashAgent",
             "depends_on": [], "timeout_s": 5, "retries": 0},
        ])
        orch = Orchestrator(cfg)
        run = orch.run(tempfile.mkdtemp(prefix="adv-allcrash-"))
        self.assertEqual(len(run.stages), 2)
        for s in run.stages:
            self.assertEqual(s.status, StageStatus.ERROR)
        self.assertIsNotNone(run.gate)
        # Spec: when all stages crash, the verdict should NOT be PASSED —
        # silently passing on a run where no analysis happened is wrong.
        self.assertNotEqual(
            run.gate.verdict,
            GateVerdict.PASSED,
            f"all stages crashed but verdict={run.gate.verdict.value} — "
            f"a fully failed workflow cannot pass the gate",
        )

    def test_retry_two_fails_then_success(self):
        agent_cls = _FailNTimesAgent
        agent_cls.attempts = 0
        agent_cls.fail_n = 2
        cfg = _cfg_for(stages=[
            {"name": "fn", "agent": "crtw.tests.test_adversarial:_FailNTimesAgent",
             "depends_on": [], "timeout_s": 10, "retries": 2},
        ])
        orch = Orchestrator(cfg)
        run = orch.run(tempfile.mkdtemp(prefix="adv-retry-"))
        self.assertEqual(run.stages[0].status, StageStatus.PASSED)
        # 3 attempts: 2 ConnectionErrors, then a success.
        self.assertEqual(agent_cls.attempts, 3)

    def test_timeout_does_not_hang_the_run(self):
        # Hang stage for 2s with timeout=1s. Orchestrator's outer
        # future.result(timeout=timeout+30) should yield a stage-level ERROR
        # before the test process runs out of time.
        agent_cls = _HangAgent
        agent_cls.hang_s = 2
        cfg = _cfg_for(stages=[
            {"name": "hang", "agent": "crtw.tests.test_adversarial:_HangAgent",
             "depends_on": [], "timeout_s": 1, "retries": 0},
        ])
        orch = Orchestrator(cfg)
        t0 = time.time()
        run = orch.run(tempfile.mkdtemp(prefix="adv-timeout-"))
        elapsed = time.time() - t0
        # The outer buffer is +30s. So worst-case is hang_s+30+slack.
        # The run MUST return long before the natural hang_s if the timeout
        # were truly enforced inside the stage — but the only enforcement is
        # the +30s buffer, so elapsed < 35 is the system's actual contract.
        # We assert the orchestrator does not wait indefinitely.
        self.assertLess(
            elapsed, 35.0,
            f"Orchestrator hung for {elapsed:.1f}s — timeout did not enforce",
        )
        # And the run must still be valid.
        self.assertEqual(len(run.stages), 1)
        self.assertEqual(run.stages[0].status, StageStatus.ERROR)


# ---------------------------------------------------------------------------
# Report generation round-trip
# ---------------------------------------------------------------------------


class ReportRoundTripTests(unittest.TestCase):
    def test_full_run_json_round_trips(self):
        # Run a single healthy agent end-to-end and ensure the resulting JSON
        # is valid, parseable, and contains the expected structure.
        cfg = _cfg_for(stages=[
            {"name": "ok", "agent": "crtw.tests.test_adversarial:_HealthyAgent",
             "depends_on": [], "timeout_s": 10, "retries": 0},
        ])
        orch = Orchestrator(cfg)
        run = orch.run(tempfile.mkdtemp(prefix="adv-rt-"))

        with tempfile.TemporaryDirectory() as td:
            json_path, _ = write_reports(run, td)
            text = json_path.read_text()
            # Must be valid JSON.
            obj = json.loads(text)
            self.assertEqual(obj["run_id"], run.run_id)
            self.assertIsInstance(obj["stages"], list)
            self.assertGreaterEqual(len(obj["stages"]), 1)
            # gate must be present and serializable
            self.assertIn("gate", obj)
            self.assertIn(obj["gate"]["verdict"], ("passed", "needs_review", "blocked"))


# ---------------------------------------------------------------------------
# Dedupe contract
# ---------------------------------------------------------------------------


class DedupeTests(unittest.TestCase):
    def test_identical_findings_collapse_to_one(self):
        # Three findings with the same file+line+title but different
        # severities — the ReviewAgent.review() should keep the highest.
        agent = _HealthyAgent()
        findings = [
            _mk_finding(Severity.MINOR, file="dup.py", line=10, title="dup"),
            _mk_finding(Severity.MAJOR, file="dup.py", line=10, title="dup"),
            _mk_finding(Severity.CRITICAL, file="dup.py", line=10, title="dup"),
        ]
        out = agent.review(findings)
        self.assertEqual(len(out), 1, f"dedupe left {len(out)} findings, expected 1")
        self.assertEqual(out[0].severity, Severity.CRITICAL)

    def test_identical_findings_exactly_same_severity_collapse(self):
        agent = _HealthyAgent()
        findings = [
            _mk_finding(Severity.MINOR, file="dup.py", line=10, title="dup")
            for _ in range(5)
        ]
        out = agent.review(findings)
        self.assertEqual(len(out), 1)


if __name__ == "__main__":
    unittest.main()