"""Pydantic contracts for CRTW.

All shared data types live here. Stages -> Orchestrator -> Report all speak
these models so nothing passes naked dicts around.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class Severity(str, enum.Enum):
    BLOCKER = "BLOCKER"
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


SEVERITY_ORDER = {
    Severity.BLOCKER: 0,
    Severity.CRITICAL: 1,
    Severity.MAJOR: 2,
    Severity.MINOR: 3,
    Severity.INFO: 4,
}


SEVERITY_WEIGHTS = {
    Severity.BLOCKER: 10,
    Severity.CRITICAL: 5,
    Severity.MAJOR: 3,
    Severity.MINOR: 1,
    Severity.INFO: 0,
}


class Finding(BaseModel):
    id: str = Field(default_factory=lambda: f"f-{uuid.uuid4().hex[:8]}")
    severity: Severity
    stage: str
    agent_id: str
    file: Optional[str] = None
    line: Optional[int] = None
    title: str
    detail: str = ""
    evidence: str = ""
    remediation: str = ""
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, v: float) -> float:
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v


class StageStatus(str, enum.Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class StageResult(BaseModel):
    stage: str
    agent_id: str
    status: StageStatus
    findings: list[Finding] = Field(default_factory=list)
    duration_ms: int = 0
    artifacts: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GateVerdict(str, enum.Enum):
    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class GateDecision(BaseModel):
    verdict: GateVerdict
    weighted_score: int
    counts: dict[str, int] = Field(default_factory=dict)
    blocking_findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    thresholds: dict[str, Any] = Field(default_factory=dict)


class WorkflowRun(BaseModel):
    run_id: str
    target: str
    started_at: str
    finished_at: Optional[str] = None
    stages: list[StageResult] = Field(default_factory=list)
    gate: Optional[GateDecision] = None
    artifacts: list[str] = Field(default_factory=list)
    config_path: Optional[str] = None
    config_overrides: dict[str, Any] = Field(default_factory=dict)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


# -----------------------------------------------------------------------------
# Tool adapter output (used by tools/adapters.py and the agents).
# -----------------------------------------------------------------------------


class ToolOutput(BaseModel):
    adapter: str
    available: bool = True
    reason: Optional[str] = None
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    raw: Optional[str] = None  # raw text output, may be redacted