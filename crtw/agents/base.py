"""ReviewAgent base class — explicit RRR cycle.

Research  -> Reason  -> Review
   |           |             |
gather     analyze       dedupe +
evidence   evidence    severity
                          calibrate +
                          drop low-confidence
                                noise

Each phase is a real method. Subclasses override the parts they need.
"""
from __future__ import annotations

import logging
import time
import traceback
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from crtw.agents.llm import LLMProvider, NullProvider, get_default_provider
from crtw.contracts import (
    Finding,
    StageResult,
    StageStatus,
    utcnow_iso,
)
from crtw.tools.adapters import (
    CoverageAdapter,
    SecretScanAdapter,
    StaticAnalysisAdapter,
    TestRunnerAdapter,
)

log = logging.getLogger(__name__)


class ReviewAgent(ABC):
    """Abstract base agent. Every concrete agent has a stable ``agent_id``,
    a ``name``, and a run method that the orchestrator calls.

    The RRR cycle is split into three overridable phases. The orchestrator
    only ever calls ``run()``; ``run()`` calls each phase and packages the
    output as a ``StageResult``.
    """

    agent_id: str = "S0-AGI3-000-AGENT"
    name: str = "base"

    def __init__(
        self,
        llm: Optional[LLMProvider] = None,
        adapters: Optional[dict[str, Any]] = None,
    ):
        self.llm = llm or get_default_provider()
        # Allow agents to opt-in to specific adapters.
        self.adapters = adapters or self._default_adapters()
        self.started_at: float = 0.0
        self.finished_at: float = 0.0

    # ------------------------------------------------------------------
    # Adapter registry — subclasses can override
    # ------------------------------------------------------------------

    def _default_adapters(self) -> dict[str, Any]:
        return {
            "test_runner": TestRunnerAdapter(),
            "static_analysis": StaticAnalysisAdapter(),
            "coverage": CoverageAdapter(),
            "secret_scan": SecretScanAdapter(),
        }

    # ------------------------------------------------------------------
    # Public entrypoint used by the orchestrator
    # ------------------------------------------------------------------

    def run(self, target: str, *, timeout: int = 60,
            prior_results: Optional[dict[str, "StageResult"]] = None) -> StageResult:
        """Run the full RRR cycle and return a StageResult.

        Stage isolation means we catch any exception here and turn it into a
        status=error StageResult. The orchestrator never sees an unhandled
        raise from an agent.

        ``prior_results`` is an optional dict of {stage_name: StageResult}
        from stages that finished in earlier dependency levels. Agents that
        consume upstream data (e.g. DebuggingAgent reading test results) can
        inspect this in their ``research()`` via ``self._prior_results``.
        """
        self.started_at = time.time()
        started_iso = utcnow_iso()
        self._prior_results: dict[str, "StageResult"] = dict(prior_results or {})
        try:
            evidence = self.research(target)
            findings = self.reason(evidence)
            findings = self.review(findings)
            self.finished_at = time.time()
            status = StageStatus.PASSED if not any(
                f.severity.value in ("BLOCKER", "CRITICAL") for f in findings
            ) else StageStatus.FAILED
            return StageResult(
                stage=self.name,
                agent_id=self.agent_id,
                status=status,
                findings=findings,
                duration_ms=int((self.finished_at - self.started_at) * 1000),
                started_at=started_iso,
                finished_at=utcnow_iso(),
                metadata={"evidence_keys": list(evidence.keys())},
            )
        except Exception as e:  # noqa: BLE001 — stage isolation
            self.finished_at = time.time()
            log.exception("agent %s crashed", self.agent_id)
            return StageResult(
                stage=self.name,
                agent_id=self.agent_id,
                status=StageStatus.ERROR,
                duration_ms=int((self.finished_at - self.started_at) * 1000),
                started_at=started_iso,
                finished_at=utcnow_iso(),
                error=f"{type(e).__name__}: {e}",
                metadata={"traceback": traceback.format_exc().splitlines()[-6:]},
            )

    # ------------------------------------------------------------------
    # RRR — Research / Reason / Review
    # ------------------------------------------------------------------

    def research(self, target: str) -> dict[str, Any]:
        """Gather raw evidence about the target.

        Subclasses call into ``self.adapters`` and accumulate a dict of
        adapter outputs. Returning a dict of ``ToolOutput`` keeps the contract
        simple.

        The base implementation also seeds ``evidence["prior_stages"]`` from
        ``self._prior_results`` (set by ``run()`` when the orchestrator passes
        upstream stage outputs).
        """
        evidence: dict[str, Any] = {"target": target, "adapters": {}, "prior_stages": {}}
        prior = getattr(self, "_prior_results", None) or {}
        for stage_name, stage_result in prior.items():
            evidence["prior_stages"][stage_name] = stage_result.model_dump()
        for adapter_name, adapter in self.adapters.items():
            try:
                if hasattr(adapter, "is_available") and not adapter.is_available():
                    evidence["adapters"][adapter_name] = {"available": False}
                    continue
                out = adapter.run(target)
                evidence["adapters"][adapter_name] = out.model_dump()
            except Exception as e:  # noqa: BLE001
                evidence["adapters"][adapter_name] = {"error": f"{type(e).__name__}: {e}"}
        return evidence

    def reason(self, evidence: dict[str, Any]) -> list[Finding]:
        """Analyze evidence and emit Finding objects. Subclasses override this."""
        return []

    def review(self, findings: list[Finding]) -> list[Finding]:
        """Dedupe + severity-calibrate + drop low-confidence noise.

        Common behaviour shared by all agents:
        - drop findings with confidence < min_confidence
        - dedupe by (file, line, title) keeping the highest severity
        - enforce a stable severity ranking so reviewers don't disagree wildly
        """
        min_confidence = 0.4
        # Drop low-confidence noise.
        filtered = [f for f in findings if f.confidence >= min_confidence]
        # Dedupe: same (file, line, title) -> keep highest severity.
        deduped: dict[tuple, Finding] = {}
        sev_rank = {"BLOCKER": 5, "CRITICAL": 4, "MAJOR": 3, "MINOR": 2, "INFO": 1}
        for f in filtered:
            key = (f.file or "", f.line or 0, f.title)
            existing = deduped.get(key)
            if existing is None or sev_rank.get(f.severity.value, 0) > sev_rank.get(existing.severity.value, 0):
                deduped[key] = f
        return list(deduped.values())