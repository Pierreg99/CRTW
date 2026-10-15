"""Orchestrator — the workflow runner.

Responsibilities:
    * Load workflow.yaml.
    * Topologically order stages by dependency.
    * Execute independent stages in parallel (ThreadPoolExecutor).
    * Per-stage timeout enforcement.
    * Retry with exponential backoff (transient errors only).
    * Stage isolation: a stage that crashes becomes a StageResult(status=error),
      the run continues.
    * Compute the gate verdict.
"""
from __future__ import annotations

import concurrent.futures as cf
import importlib
import logging
import time
import traceback
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

import yaml

from crtw.contracts import (
    Finding,
    GateDecision,
    GateVerdict,
    SEVERITY_WEIGHTS,
    StageResult,
    StageStatus,
    WorkflowRun,
    new_run_id,
    utcnow_iso,
)

log = logging.getLogger(__name__)


# =============================================================================
# Config loading
# =============================================================================


DEFAULT_CONFIG: dict[str, Any] = {
    "workflow": {"name": "crtw", "version": "0.0.0"},
    "stages": [],
    "adapters": {},
    "gate": {
        "severity_weights": {k.value: v for k, v in SEVERITY_WEIGHTS.items()},
        "block_threshold": 10,
        "review_threshold": 5,
        "block_on_any_blocker": True,
        "review_on_any_critical_or_major": True,
    },
    "orchestration": {"max_workers": 4, "retry_backoff_base_s": 0.5},
}


def load_config(path: Optional[str] = None) -> dict[str, Any]:
    cfg = {k: (dict(v) if isinstance(v, dict) else v) for k, v in DEFAULT_CONFIG.items()}
    cfg["adapters"] = dict(cfg.get("adapters", {}))
    if Path(path).exists():
        with open(path) as f:
            user_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, user_cfg)
    return cfg


def _deep_merge(a: Any, b: Any) -> Any:
    if not isinstance(b, dict):
        return b
    out = dict(a) if isinstance(a, dict) else {}
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# =============================================================================
# Topological sort
# =============================================================================


def topo_order(stages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Return stages grouped into dependency-respecting levels.

    Each level can be executed in parallel; levels must run sequentially.
    Raises ValueError if there's a cycle.
    """
    by_name = {s["name"]: s for s in stages}
    deps = {s["name"]: list(s.get("depends_on") or []) for s in stages}

    # Detect unknown deps
    for n, d in deps.items():
        for dd in d:
            if dd not in by_name:
                raise ValueError(f"stage {n!r} depends on unknown stage {dd!r}")

    indeg = {n: len(d) for n, d in deps.items()}
    reverse = defaultdict(list)
    for n, d in deps.items():
        for dd in d:
            reverse[dd].append(n)

    levels: list[list[dict[str, Any]]] = []
    ready = deque(n for n, c in indeg.items() if c == 0)
    visited = 0
    while ready:
        level = []
        for _ in range(len(ready)):
            n = ready.popleft()
            level.append(by_name[n])
            visited += 1
            for child in reverse[n]:
                indeg[child] -= 1
                if indeg[child] == 0:
                    ready.append(child)
        levels.append(level)

    if visited != len(stages):
        raise ValueError("cycle in workflow.yaml stages")
    return levels


# =============================================================================
# Stage execution with retry + timeout
# =============================================================================


def _import_agent(spec: str):
    mod_name, _, cls_name = spec.partition(":")
    if not cls_name:
        cls_name = "Agent"
    mod = importlib.import_module(mod_name)
    cls = getattr(mod, cls_name)
    return cls


def _run_stage_once(stage_cfg: dict[str, Any], target: str,
                    prior_results: Optional[dict[str, StageResult]] = None) -> StageResult:
    """Instantiate + run the agent. Catches all exceptions for stage isolation."""
    try:
        cls = _import_agent(stage_cfg["agent"])
    except Exception as e:  # noqa: BLE001
        return StageResult(
            stage=stage_cfg["name"],
            agent_id=stage_cfg.get("agent", "?"),
            status=StageStatus.ERROR,
            error=f"agent import failed: {type(e).__name__}: {e}",
        )
    try:
        agent = cls()
    except Exception as e:  # noqa: BLE001
        return StageResult(
            stage=stage_cfg["name"],
            agent_id=stage_cfg.get("agent", "?"),
            status=StageStatus.ERROR,
            error=f"agent init failed: {type(e).__name__}: {e}",
        )

    timeout = int(stage_cfg.get("timeout_s", 60))
    try:
        return agent.run(target, timeout=timeout, prior_results=prior_results)
    except Exception as e:  # noqa: BLE001
        return StageResult(
            stage=stage_cfg["name"],
            agent_id=agent.agent_id,
            status=StageStatus.ERROR,
            error=f"{type(e).__name__}: {e}",
            metadata={"traceback": traceback.format_exc().splitlines()[-6:]},
        )


def _is_transient_error(result: StageResult) -> bool:
    """A retryable error is one with status=error AND message suggesting a
    transient failure (timeout, connection). Pure-attribute errors are not
    retried."""
    if result.status != StageStatus.ERROR:
        return False
    msg = (result.error or "").lower()
    return any(k in msg for k in ("timeout", "timed out", "connection", "temporary"))


def _run_stage_with_retries(stage_cfg: dict[str, Any], target: str,
                            backoff_base: float = 0.5,
                            prior_results: Optional[dict[str, StageResult]] = None) -> StageResult:
    retries = int(stage_cfg.get("retries", 0))
    last = _run_stage_once(stage_cfg, target, prior_results=prior_results)
    for attempt in range(1, retries + 1):
        if not _is_transient_error(last):
            break
        delay = backoff_base * (2 ** (attempt - 1))
        log.info("retrying stage %s in %.2fs (attempt %d)", stage_cfg["name"], delay, attempt + 1)
        time.sleep(delay)
        last = _run_stage_once(stage_cfg, target, prior_results=prior_results)
    return last


# =============================================================================
# Gate computation
# =============================================================================


def compute_gate(findings: list[Finding], cfg: dict[str, Any]) -> GateDecision:
    gate_cfg = cfg.get("gate", {})
    weights = {k.upper(): int(v) for k, v in gate_cfg.get("severity_weights", {}).items()}
    # fall back to canonical weights for anything missing
    for k, v in SEVERITY_WEIGHTS.items():
        weights.setdefault(k.value, int(v))

    block_threshold = int(gate_cfg.get("block_threshold", 10))
    review_threshold = int(gate_cfg.get("review_threshold", 5))
    block_on_any_blocker = bool(gate_cfg.get("block_on_any_blocker", True))
    review_on_any = bool(gate_cfg.get("review_on_any_critical_or_major", True))

    counts: dict[str, int] = defaultdict(int)
    for f in findings:
        counts[f.severity.value] += 1

    weighted = sum(weights.get(s, 0) * c for s, c in counts.items())
    blocking = [f for f in findings if f.severity.value == "BLOCKER"]

    verdict = GateVerdict.PASSED
    if block_on_any_blocker and blocking:
        verdict = GateVerdict.BLOCKED
    elif weighted >= block_threshold:
        verdict = GateVerdict.BLOCKED
    elif review_on_any and (counts.get("CRITICAL", 0) > 0 or counts.get("MAJOR", 0) > 0):
        verdict = GateVerdict.NEEDS_REVIEW
    elif weighted >= review_threshold:
        verdict = GateVerdict.NEEDS_REVIEW

    summary = (
        f"verdict={verdict.value} score={weighted} "
        f"counts=" + ", ".join(f"{k}={counts.get(k,0)}" for k in ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"))
    )

    return GateDecision(
        verdict=verdict,
        weighted_score=weighted,
        counts=dict(counts),
        blocking_findings=blocking,
        summary=summary,
        thresholds={
            "block_threshold": block_threshold,
            "review_threshold": review_threshold,
            "severity_weights": weights,
        },
    )


# =============================================================================
# Public runner
# =============================================================================


class Orchestrator:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.max_workers = int(cfg.get("orchestration", {}).get("max_workers", 4))
        self.backoff_base = float(cfg.get("orchestration", {}).get("retry_backoff_base_s", 0.5))

    def run(self, target: str, *, stages_filter: Optional[list[str]] = None) -> WorkflowRun:
        stages = list(self.cfg.get("stages", []))
        if stages_filter:
            keep = set(stages_filter)
            stages = [s for s in stages if s["name"] in keep]
            # Drop deps pointing at removed stages.
            for s in stages:
                s["depends_on"] = [d for d in s.get("depends_on", []) if d in keep]
        if not stages:
            raise ValueError("no stages to execute (check --stages filter or workflow.yaml)")

        levels = topo_order(stages)
        run_id = new_run_id()
        run = WorkflowRun(
            run_id=run_id,
            target=str(Path(target).resolve()),
            started_at=utcnow_iso(),
        )

        # prior_results maps stage_name -> StageResult from completed levels.
        # Stages in later levels see this via the orchestrator; downstream
        # agents (e.g. debug) use it as their `prior_stages` evidence.
        prior_results: dict[str, StageResult] = {}

        with cf.ThreadPoolExecutor(max_workers=self.max_workers) as pool_exec:
            for level in levels:
                futures = {
                    pool_exec.submit(
                        _run_stage_with_retries,
                        s, target, self.backoff_base, prior_results,
                    ): s
                    for s in level
                }
                for fut in cf.as_completed(futures):
                    stage_cfg = futures[fut]
                    try:
                        result = fut.result(timeout=int(stage_cfg.get("timeout_s", 60)) + 30)
                    except cf.TimeoutError:
                        result = StageResult(
                            stage=stage_cfg["name"],
                            agent_id=stage_cfg.get("agent", "?"),
                            status=StageStatus.ERROR,
                            error="stage future timed out in pool",
                        )
                    except Exception as e:  # noqa: BLE001
                        # Truly catastrophic orchestrator-level failure.
                        # Stage isolation means even THIS becomes a StageResult.
                        result = StageResult(
                            stage=stage_cfg["name"],
                            agent_id=stage_cfg.get("agent", "?"),
                            status=StageStatus.ERROR,
                            error=f"{type(e).__name__}: {e}",
                        )
                    run.stages.append(result)
                    # Make this stage's output available to later levels.
                    prior_results[stage_cfg["name"]] = result

        # Gate
        all_findings = [f for s in run.stages for f in s.findings]
        run.gate = compute_gate(all_findings, self.cfg)
        run.finished_at = utcnow_iso()
        return run