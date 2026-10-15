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

The `crtw.agents.llm` module ships **four providers** out of the box. Pick
one by name (env var), by FQCN (`module:Class`), or by registration.

| Name | Class | Online? | Use case |
|---|---|---|---|
| `null` | `NullProvider` | No | Default. Empty suggestion string; pipeline still produces real findings. |
| `offline-mock` | `OfflineMockProvider` | No | Heuristic templates (secrets, SQLi, MD5, RCE, shell=True, TLS) without any LLM. |
| `scripted` | `ScriptedProvider` | No | Deterministic test double; pre-load canned responses, raises `LLMStopped` when exhausted. |
| `anthropic` | `AnthropicProvider` | Yes | Real Claude API. Validates model against a prefix allowlist, tracks token + cost. |

Activate a provider by setting `CRTW_LLM_PROVIDER`:

```bash
# Heuristic offline templates (no API key, no network):
export CRTW_LLM_PROVIDER=offline-mock
python -m crtw.cli --target ./your_pkg

# Real Claude (requires ANTHROPIC_API_KEY + pip install anthropic):
export CRTW_LLM_PROVIDER=anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python -m crtw.cli --target ./your_pkg

# Module:Class form for custom providers:
export CRTW_LLM_PROVIDER=crtw.agents.llm:OfflineMockProvider
```

The default is `null` — the pipeline is fully deterministic and never breaks
if the LLM is unreachable. Any provider failure is wrapped in
`LLMStopped` and re-raised so the orchestrator can decide whether to fall
back.

### Writing your own provider

```python
# crtw/my_llm.py
from crtw.agents.llm import BaseProvider, LLMRequest, LLMResponse

class MyProvider(BaseProvider):
    name = "my-llm"

    def _complete(self, request: LLMRequest) -> LLMResponse:
        # call your model here
        return LLMResponse(text="...", provider=self.name, raw={...})
```

Activate it via env var, or register it under a short name and use that:

```python
from crtw.agents.llm import register_provider, set_default_provider
register_provider("my-llm", MyProvider)
set_default_provider(MyProvider())
```

Subclasses of `ReviewAgent` can use `self.llm.complete(...)` to enrich any
Finding with `remediation` text, summaries, or to ask the model to suggest
patches. The deterministic AST/regex/static-analysis checks remain the source
of truth and never depend on the LLM being online.

### Usage tracking

Every `BaseProvider` keeps a thread-safe counter of `requests`, `input_tokens`,
`output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`,
and an approximate `cost_usd` (using a small list-price table). The
`AnthropicProvider` populates these from the real response; offline providers
leave token counts at zero. Inspect the rollup at any time:

```python
provider = get_default_provider()
provider.complete(LLMRequest(user="...", system="..."))
print(provider.usage())
# -> {'requests': 1, 'input_tokens': 12, 'output_tokens': 7, ..., 'cost_usd': 0.0001, 'models': {...}}
```

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