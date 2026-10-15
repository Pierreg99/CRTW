# CRTW — Code Review + Testing Workflow

CRTW is an executable multi-agent workflow that performs automated code review
and testing. It is fully offline by default, has no required third-party
dependencies, and degrades gracefully when optional tools (pytest, mypy, ruff,
bandit, coverage) are missing.

The whole pipeline is declarative (driven by `crtw/workflow.yaml`) and ships
with **four agents**, **four tooling adapters**, and a real orchestrator that
honors stage dependencies with topological ordering, parallel fan-out,
timeouts, retries, and stage isolation.

---

## Architecture

```
                 workflow.yaml
                     │
                     ▼
   ┌─────────────────────────────────┐
   │       Orchestrator              │
   │   ┌─────────────────────────┐   │
   │   │  topo_sort(stages)      │   │
   │   │  ThreadPoolExecutor     │   │
   │   │  per-stage timeout      │   │
   │   │  retry w/ backoff       │   │
   │   └─────────────────────────┘   │
   └─────────────────────────────────┘
       │              │            │
       ▼              ▼            ▼
   security        review       test         debug
       │              │            │             │
   ToolAdapters:   ToolAdapters: ToolAdapters:
   secret_scan    static_analysis test_runner (test input)
                                    coverage
       │              │            │
       ▼              ▼            ▼
   Gate Verdict  ─►  Report  ─►  run-<id>.json + <id>.md
```

### Agent Roster

| Agent ID | Stage | Detects |
|---|---|---|
| `S6-AGI3-037-SECURITYAUDITOR` | security | hardcoded secrets, `eval/exec`, `pickle.loads`, `shell=True + f-string`, `verify=False`, MD5/SHA1 for passwords, SQL string concat, path traversal |
| `S3-AGI3-010-REVIEWER` | review | complexity hotspots, bare `except:`, mutable defaults, unused imports, missing type hints, dead code, TODO/FIXME, swallowed exceptions, unguarded risky calls |
| `S3-AGI3-009-TESTER` | test | failing tests, low coverage, no-assertion tests, untested public symbols |
| `S6-AGI3-014-DEBUGGER` | debug | root-cause extraction from tracebacks, product vs test bug classification, failure grouping |

### Tooling Adapters

| Adapter | Optional deps | Behavior when missing |
|---|---|---|
| `TestRunnerAdapter` | `pytest` (preferred) or stdlib `unittest` | falls back to unittest; if neither can run, returns `available=False` |
| `StaticAnalysisAdapter` | `mypy`, `ruff`, `flake8`, `pyflakes` | always emits an AST fallback for unused imports + syntax errors |
| `CoverageAdapter` | `coverage` | returns `available=False` with a helpful reason |
| `SecretScanAdapter` | none | always available; pure-regex |

All adapters are **uniform** (`is_available()` + `run(target)`) and never
crash the run if the tool is missing.

---

## Quickstart

```bash
# Scan a directory
python -m crtw.cli --target ./your_pkg

# CI mode — exit 1 on BLOCKED
python -m crtw.cli --target ./your_pkg --fail-on-blocked

# Just one stage
python -m crtw.cli --target ./your_pkg --stages security,review

# Dump JSON
python -m crtw.cli --target ./your_pkg --json

# Verbose logs
python -m crtw.cli --target ./your_pkg -v
```

The CLI prints a console summary and writes two artifacts into
`crtw/reports/`:

- `run-<id>.json` — machine-readable `WorkflowRun`.
- `<id>.md` — human-readable Markdown report grouped by file, with a
  banner-style gate verdict.

### Self-check fixtures

`crtw/selfcheck/flawed/` deliberately exhibits every detection the agents
should make. `crtw/selfcheck/clean/` is the opposite — it should produce
no blocker or critical findings.

```bash
python -m crtw.cli --target crtw/selfcheck/flawed
python -m crtw.cli --target crtw/selfcheck/clean
```

---

## CLI Reference

| Flag | Meaning |
|---|---|
| `--target PATH` (required) | File or directory to review. |
| `--config PATH` | Path to `workflow.yaml`. Override-able. |
| `--output-dir PATH` | Directory for reports (default: `crtw/reports`). |
| `--json` | Print the full `WorkflowRun` JSON to stdout. |
| `--fail-on-blocked` | Exit code `1` when the gate verdict is `BLOCKED`. |
| `--stages a,b,c` | Whitelist of stages to execute. |
| `--verbose` / `-v` | DEBUG-level logging. |

---

## Gate Policy

`workflow.yaml` ships a default policy:

```yaml
gate:
  severity_weights: { BLOCKER: 10, CRITICAL: 5, MAJOR: 3, MINOR: 1, INFO: 0 }
  block_threshold: 10
  review_threshold: 5
  block_on_any_blocker: true
  review_on_any_critical_or_major: true
```

Verdict logic (in `crtw/orchestrator.py::compute_gate`):

```
score = sum(severity_weight * count)
verdict = BLOCKED if any BLOCKER or score >= block_threshold
       else NEEDS_REVIEW if any CRITICAL/MAJOR or score >= review_threshold
       else PASSED
```

Override these via `workflow.yaml` or your own YAML file passed to `--config`.

---

## Adding a Custom Agent

Subclass `ReviewAgent` and implement the `reason(evidence)` method (and
optionally `review(...)` if you have custom dedupe/calibration logic).

```python
# crtw/myplugin.py
from crtw.agents.base import ReviewAgent
from crtw.contracts import Finding, Severity

class MyAgent(ReviewAgent):
    agent_id = "S7-AGI3-123-MYAGENT"
    name = "myagent"

    def __init__(self, **kw):
        super().__init__(**kw)
        # Pick which adapters you need:
        self.adapters.pop("test_runner", None)

    def reason(self, evidence):
        out = []
        for f in self._iter_files(evidence["target"]):
            # ... analyse f ...
            out.append(Finding(
                severity=Severity.MAJOR,
                stage=self.name,
                agent_id=self.agent_id,
                file=str(f),
                title="my new check",
                detail="...",
                confidence=0.9,
            ))
        return out
```

Then add a stage entry to `workflow.yaml`:

```yaml
stages:
  - name: myagent
    agent: crtw.myplugin:MyAgent
    depends_on: []
    timeout_s: 30
    retries: 0
    adapters: []
```

---

## Wiring in a Real LLM Provider

The system ships with `NullProvider` (offline, returns empty suggestions) so
the workflow works with **zero** network access.

To swap in a real provider:

```python
# crtw/my_llm.py
from crtw.agents.llm import LLMProvider, LLMRequest, LLMResponse

class MyProvider:
    name = "my-llm"

    def complete(self, request: LLMRequest) -> LLMResponse:
        # call your model here
        return LLMResponse(text="...", provider=self.name)
```

Then either set the env var:

```bash
export CRTW_LLM_PROVIDER=crtw.my_llm:MyProvider
python -m crtw.cli --target ./...
```

or pass it programmatically via `Orchestrator(..., llm_provider=...)`.

Subclasses of `ReviewAgent` can use `self.llm.complete(...)` to enrich any
Finding with `remediation` text, summaries, or to ask the model to suggest
patches. The deterministic AST/regex/static-analysis checks remain the source
of truth and never depend on the LLM being online.

---

## File Tree

```
crtw/
├── __init__.py
├── workflow.yaml          # declarative workflow spec
├── contracts.py           # Pydantic models
├── orchestrator.py        # runner + gate
├── report.py              # JSON + Markdown generation
├── agents/
│   ├── __init__.py
│   ├── base.py            # ReviewAgent RRR cycle
│   ├── llm.py             # LLMProvider protocol + NullProvider
│   ├── reviewer.py        # S3-AGI3-010-REVIEWER
│   ├── tester.py          # S3-AGI3-009-TESTER
│   ├── security.py        # S6-AGI3-037-SECURITYAUDITOR
│   └── debugger.py        # S6-AGI3-014-DEBUGGER
├── tools/
│   ├── __init__.py
│   └── adapters.py        # TestRunner / StaticAnalysis / Coverage / SecretScan
├── selfcheck/
│   ├── flawed/            # broken module + planted failing test
│   └── clean/             # clean module + passing test
├── tests/
│   └── test_workflow.py   # unit tests (stdlib)
└── reports/               # generated at runtime
```

---

## Running the tests

```bash
python -m unittest crtw.tests.test_workflow -v
```

No pytest is required. Tests cover:

- Gate verdict at each threshold boundary.
- Stage isolation (a stage that raises still yields a complete run).
- Topological ordering + cycle / unknown-dep detection.
- Finding dedupe + severity calibration in `ReviewAgent.review()`.
- Config loading.