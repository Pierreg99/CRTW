"""CLI entrypoint: ``python -m crtw.cli``.

Example:
    python -m crtw.cli --target ./crtw/selfcheck/flawed
    python -m crtw.cli --target ./myapp --fail-on-blocked --json --stages security,review
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from crtw.contracts import GateVerdict, WorkflowRun
from crtw.orchestrator import Orchestrator, load_config
from crtw.report import write_reports


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="crtw",
        description="Automated multi-agent code review + testing workflow.",
    )
    p.add_argument("--target", required=True, help="Path to scan (file or directory).")
    p.add_argument(
        "--config",
        default=str(Path(__file__).parent / "workflow.yaml"),
        help="Path to workflow.yaml (default: %(default)s)",
    )
    p.add_argument(
        "--output-dir",
        default=str(Path(__file__).parent / "reports"),
        help="Directory for JSON + Markdown reports (default: %(default)s)",
    )
    p.add_argument("--json", action="store_true", help="Print the JSON WorkflowRun to stdout.")
    p.add_argument(
        "--fail-on-blocked",
        action="store_true",
        help="Exit 1 if the gate verdict is BLOCKED. Useful for CI.",
    )
    p.add_argument(
        "--stages",
        default=None,
        help="Comma-separated whitelist of stage names to execute (default: all).",
    )
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging.")
    return p


def _console_summary(run: WorkflowRun) -> str:
    g = run.gate
    bar = {
        GateVerdict.PASSED: "[PASSED]",
        GateVerdict.NEEDS_REVIEW: "[NEEDS REVIEW]",
        GateVerdict.BLOCKED: "[BLOCKED]",
    }[g.verdict]
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"CRTW run {run.run_id}  target={run.target}")
    lines.append(f"Gate: {bar} score={g.weighted_score}")
    lines.append(
        "Counts: "
        + " ".join(f"{s}={g.counts.get(s,0)}" for s in ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"))
    )
    lines.append(f"Summary: {g.summary}")
    lines.append("-" * 72)
    for s in run.stages:
        lines.append(f"  [{s.status.value:7}] {s.stage:10} ({s.agent_id}) — "
                     f"{len(s.findings)} findings / {s.duration_ms}ms")
        if s.error:
            lines.append(f"      error: {s.error}")
        for f in sorted(s.findings, key=lambda x: x.severity.value)[:10]:
            lines.append(f"      - {f.severity.value:8} {f.title}  ({f.file}:{f.line})")
        if len(s.findings) > 10:
            lines.append(f"      ... and {len(s.findings) - 10} more")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    stages_filter = None
    if args.stages:
        stages_filter = [s.strip() for s in args.stages.split(",") if s.strip()]

    orch = Orchestrator(cfg)
    run = orch.run(args.target, stages_filter=stages_filter)
    json_path, md_path = write_reports(run, args.output_dir)

    print(_console_summary(run))
    print(f"Reports:")
    print(f"  - JSON:       {json_path}")
    print(f"  - Markdown:   {md_path}")

    if args.json:
        print("--- JSON ---")
        print(json.dumps(json.loads(run.model_dump_json()), indent=2))

    if args.fail_on_blocked and run.gate and run.gate.verdict == GateVerdict.BLOCKED:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())