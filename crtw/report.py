"""Report generators.

Produces:
    * ``run-<id>.json`` — machine-readable WorkflowRun.
    * ``<id>.md`` — human-readable Markdown with summary table, per-stage
      breakdown, gate verdict banner, and artifact paths.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from crtw.contracts import (
    Finding,
    GateVerdict,
    SEVERITY_ORDER,
    StageResult,
    WorkflowRun,
)


def write_reports(run: WorkflowRun, output_dir: str | Path) -> tuple[Path, Path]:
    """Write JSON + Markdown. Returns (json_path, md_path)."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"run-{run.run_id}.json"
    md_path = out_dir / f"{run.run_id}.md"

    # JSON
    json_path.write_text(run.model_dump_json(indent=2), encoding="utf-8")

    # Markdown
    md_path.write_text(render_markdown(run), encoding="utf-8")

    return json_path, md_path


def render_markdown(run: WorkflowRun) -> str:
    gate = run.gate
    severity_to_color = {
        "BLOCKER": "🔴",
        "CRITICAL": "🟠",
        "MAJOR": "🟡",
        "MINOR": "🔵",
        "INFO": "⚪",
    }

    lines: list[str] = []
    lines.append(f"# CRTW Run `{run.run_id}`")
    lines.append("")
    lines.append(f"- **Target**: `{run.target}`")
    lines.append(f"- **Started**: `{run.started_at}`")
    lines.append(f"- **Finished**: `{run.finished_at}`")
    lines.append("")

    # ---- Banner ----
    banner = {
        GateVerdict.PASSED: "## ✅ GATE: PASSED",
        GateVerdict.NEEDS_REVIEW: "## ⚠️ GATE: NEEDS REVIEW",
        GateVerdict.BLOCKED: "## ⛔ GATE: BLOCKED",
    }[gate.verdict]
    lines.append(banner)
    lines.append("")
    lines.append(f"**Summary:** {gate.summary}")
    lines.append("")
    counts = gate.counts
    lines.append("| Severity | Count |")
    lines.append("|----------|------:|")
    for sev in ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"):
        lines.append(f"| {sev} | {counts.get(sev, 0)} |")
    lines.append(f"| **Weighted score** | **{gate.weighted_score}** |")
    lines.append("")
    lines.append(
        f"Thresholds: block ≥ {gate.thresholds.get('block_threshold')}, "
        f"review ≥ {gate.thresholds.get('review_threshold')}"
    )
    lines.append("")

    # ---- Per-stage breakdown ----
    lines.append("## Stages")
    lines.append("")
    lines.append("| Stage | Status | Findings | Duration |")
    lines.append("|-------|--------|----------:|---------:|")
    for s in run.stages:
        lines.append(
            f"| `{s.stage}` | {s.status.value} | "
            f"{len(s.findings)} | {s.duration_ms}ms |"
        )
    lines.append("")
    for s in run.stages:
        lines.extend(_render_stage(s))
        lines.append("")

    # ---- Findings grouped by file ----
    lines.append("## Findings by File")
    lines.append("")
    grouped: dict[str, list[Finding]] = defaultdict(list)
    for f in [f for s in run.stages for f in s.findings]:
        grouped[f.file or "(global)"].append(f)

    if not grouped:
        lines.append("_No findings._")
    else:
        for fpath in sorted(grouped):
            lines.append(f"### `{fpath}`")
            lines.append("")
            fs = sorted(
                grouped[fpath],
                key=lambda x: (SEVERITY_ORDER[x.severity], x.line or 0, x.title),
            )
            lines.append("| Sev | Line | Title | Stage | Confidence |")
            lines.append("|-----|-----:|-------|-------|-----------:|")
            for f in fs:
                lines.append(
                    f"| {severity_to_color[f.severity.value]} {f.severity.value} | "
                    f"{f.line or '-'} | {f.title} | `{f.stage}` | {f.confidence:.2f} |"
                )
            lines.append("")
            for f in fs:
                lines.extend(_render_finding_detail(f))
                lines.append("")

    # ---- Blocking findings ----
    if gate.blocking_findings:
        lines.append("## Blocking findings")
        lines.append("")
        for f in gate.blocking_findings:
            lines.append(f"- **[{f.severity.value}]** {f.title}  — `{f.file}:{f.line}`")
            lines.append(f"  - {f.detail}")
        lines.append("")

    # ---- Artifacts ----
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- JSON: `{run.run_id}.json`")
    lines.append(f"- Markdown: `{run.run_id}.md`")
    for s in run.stages:
        for a in s.artifacts:
            lines.append(f"- Stage `{s.stage}` artifact: `{a}`")
    lines.append("")
    return "\n".join(lines)


def _render_stage(s: StageResult) -> list[str]:
    out: list[str] = []
    out.append(f"### Stage `{s.stage}` — {s.status.value}")
    if s.error:
        out.append("")
        out.append(f"- **Error:** `{s.error}`")
    if s.findings:
        out.append("")
        out.append("Findings:")
        for f in sorted(s.findings, key=lambda x: (SEVERITY_ORDER[x.severity], x.line or 0)):
            out.append(f"  - [{f.severity.value}] {f.title} (`{f.file}:{f.line}`)")
    return out


def _render_finding_detail(f: Finding) -> list[str]:
    out: list[str] = []
    out.append(f"<details><summary><strong>{f.severity.value}</strong> — {f.title}</summary>")
    out.append("")
    out.append(f"- **Stage:** `{f.stage}` ({f.agent_id})")
    if f.file:
        out.append(f"- **Location:** `{f.file}:{f.line or '?'}`")
    if f.detail:
        out.append(f"- **Detail:** {f.detail}")
    if f.evidence:
        out.append("- **Evidence:**")
        out.append("")
        out.append("```")
        out.append(f.evidence.strip())
        out.append("```")
    if f.remediation:
        out.append(f"- **Remediation:** {f.remediation}")
    if f.tags:
        out.append(f"- **Tags:** `{', '.join(f.tags)}`")
    out.append("")
    out.append("</details>")
    return out