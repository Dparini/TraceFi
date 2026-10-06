# TraceFi

**Decision provenance, failure attribution and counterfactual debugging for financial agents.**

A financial agent supplied $50,000 USDC to a protocol. Days later, the position
lost $2,341. PnL records the loss. TraceFi reconstructs the decision:

- Which market and portfolio state did the agent see?
- What retrieved evidence informed the proposed action?
- Did the risk policy approve it, and what did simulation predict?
- Does the evidence point to a data, retrieval, reasoning, policy, simulation
  or execution failure—or a negative market outcome?
- **What input would have changed the financial decision?**

TraceFi preserves that provenance, identifies failure evidence and reruns the
recorded state with one input changed at a time. It makes autonomous
financial-agent decisions reproducible, auditable and diagnosable.

Local SQLite storage. Offline deterministic demos. No required LLM, subscription,
financial API or real capital.

## Quick Start

This repository is an installable **0.1 development release**. It has not been
published to PyPI; install the local checkout rather than an unrelated package
with the same name.

```bash
# Python 3.10+
python3 -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install -e .
.venv/bin/tracefi demo
.venv/bin/tracefi analyze latest
.venv/bin/tracefi serve
# Open http://127.0.0.1:8765
```

```python
from tracefi import TraceFi

with TraceFi(redact=["credential"]) as trace:
    with trace.decision(agent="yield-agent", version="1.4.2") as t:
        t.capture_context({"apy": 0.067, "liquidity": 21_000_000})
        t.capture_decision({"action": "SUPPLY", "asset": "USDC", "amount": 25_000})
        t.capture_policy({"approved": True})
        t.capture_simulation({"success": True, "mode": "synthetic"})
        t.capture_execution({"status": "success", "mode": "synthetic"})
    print(t.trace_id)
```

```text
FINANCIAL AGENT
      │
      ▼
DECISION PROVENANCE
      ├── market state
      ├── portfolio state
      ├── retrieved evidence
      ├── proposed action
      ├── risk policy
      ├── simulation
      └── execution
              │
              ▼
       FAILURE ATTRIBUTION
       data · retrieval · reasoning · policy
       simulation · execution · market outcome
              │
              ▼
    COUNTERFACTUAL DEBUGGING
    "What input would have changed the financial decision?"
```

## Why TraceFi?

A financial decision depends on market freshness, available liquidity, portfolio
allocation and risk constraints. A useful investigation connects those inputs
to the proposed action, the controls it passed and the observed execution.

**Provenance** preserves the state and evidence available at decision time.
**Failure attribution** distinguishes observed inconsistencies from likely
causes, retaining multiple findings and unknowns. **Counterfactual debugging**
tests whether a different yield, liquidity level or other recorded input would
have changed the proposal.

A negative outcome does not automatically imply an agent error. TraceFi does
not determine whether a financial decision was objectively right.

## Financial Decision Provenance

Each trace has a UUID-based ID, schema and canonicalization versions, UTC wall
clock timestamps, monotonic durations, redacted snapshots, a proposal and spans.
Store the actual state used by the agent, including configurations:

```python
with trace.decision(
    agent="yield-agent", version="1",
    portfolio={"USDC": 100_000},
    agent_config={"version": "1", "min_liquidity": 12_400_000},
    policy_config={"max_exposure": 0.35},
) as t:
    with t.span("market-data", kind="data") as span:
        span.log({"source": "local-dataset", "records": 42})
    t.capture_context(market_state)
    t.capture_retrieval(retrieved_evidence)
    proposal = agent.decide(market_state)
    t.capture_decision(proposal)
    t.capture_policy(policy.check(proposal))
    t.capture_simulation(simulator.run(proposal))
    t.capture_execution(executor.execute(proposal))
```

Nested spans retain parent IDs. Captures create typed spans automatically. Inputs
are copied at capture time; context cannot be replaced after a proposal is
captured. There is at most one proposal per trace; replay requires a proposal. Exceptions are recorded by
type and re-raised; their potentially sensitive messages are never persisted.
The SDK observes your checks and executions: it does **not** enforce a policy
on your executor. The example and scenario runners do enforce their policy.

See [API and data contract](docs/API.md) for exact payloads and adapter inputs.

## Replay

```bash
tracefi list
tracefi show latest
tracefi replay latest --adapter deterministic
tracefi diff TRACE_A TRACE_B
```

Replay requires an explicit adapter. It runs on the captured state and compares
the complete structured output, including the rationale, using canonical hashes.
A matching replay is evidence of reproduction, not proof of determinism.
Divergence exits with status 1. Redacted state cannot be replayed exactly and is
rejected. No transaction is replayed.

Adapters implement `decide(state)`. Built-ins are `deterministic`, `agent-v1`,
`agent-v2` and optional `ollama`. Use `--adapter my_package:factory` for a trusted
local adapter. Loading an adapter executes Python code; trace contents cannot
choose the adapter. Pin agent code, environment and model yourself.

## Failure Attribution

```bash
tracefi analyze latest
tracefi analyze latest --json
```

Rules identify stale oracle data, conflicting sources, omitted required evidence,
invalid proposal amounts, policy inconsistencies, failed execution and measurable
simulation mismatches. Suspicious untrusted inputs are observable through an
additional `ADVERSARIAL_INPUT` finding. Multiple findings are retained.

`DATA_FAILURE`, `RETRIEVAL_FAILURE`, `REASONING_FAILURE`, `POLICY_FAILURE`,
`SIMULATION_FAILURE`, `EXECUTION_FAILURE` and `MARKET_OUTCOME` form the core
failure taxonomy. Incomplete evidence remains **undetermined**. A likely
`MARKET_OUTCOME` requires recorded negative PnL, approved policy, successful
simulation and execution, and no detected failure. This is not an assurance that
all errors were ruled out. Findings distinguish observed inconsistencies from
likely interpretations, and never infer hidden chain of thought.

## Counterfactual Debugging

```bash
tracefi counterfactual latest --adapter deterministic \
  --feature context.liquidity --value 10000000
tracefi counterfactual latest --adapter deterministic \
  --feature context.liquidity --low 1000000 --high 30000000
tracefi why-change TRACE_A TRACE_B --adapter deterministic
```

Counterfactuals change one input at a time. The chosen adapter must reproduce the
original trace twice (both traces for `why-change`), and each intervention must
return the same structured output twice. Repeated matches do not prove determinism. A single sufficient change is
reported as a driver conditional on the recorded state. Interactions may require
several changes together. Boundary search returns a numerical bracket under a
monotonic-transition assumption; equal endpoints do not prove insensitivity.
Changing a policy input reruns the **agent**, not the policy or execution system.
The engine does not fabricate counterfactual returns.

## Regression Testing

```bash
tracefi eval --baseline agent-v1 --candidate agent-v2 --dataset scenarios/
tracefi eval --baseline agent-v1 --candidate agent-v2 --fail-on-regression
tracefi run --dataset scenarios/ --adapter deterministic
```

There are 30 synthetic JSON scenarios across normal, market, data, adversarial
and execution categories. Installed wheels include the same dataset. `eval`
compares agent proposals against the same scenarios with deterministic policy
checks; unsafe proposals are blocked, so reported execution policy violations are
zero by construction. `run` additionally captures synthetic execution and
explicit injected faults for post-mortem testing. Overrides are not included in
agent regression scoring. Neither command touches real funds.

Reports contain scenario counts, valid decisions, unsafe proposals, policy
violations and average proposed exposure. Exposure is not a calibrated risk
score. Return and drawdown metrics are intentionally unavailable without a
validated outcome model. `--fail-on-regression` exits with status 1 if a tracked
metric deteriorates, rather than declaring the candidate financially worse.

## Dashboard & Export

The packaged React dashboard is local and read-only. Explore traces, search and
filter status, inspect a span timeline, compare evidence to the context, view
failure attribution and test an alternative financial input in the counterfactual
tab. The dashboard experiment uses the synthetic deterministic adapter and
requires it to reproduce the trace. Other agents use explicit CLI adapters.
Download standalone HTML post-mortems for sharing. Every read verifies trace,
snapshot, span and artifact hashes. An empty database has an explicit empty state.

```bash
tracefi serve --port 8765
tracefi export latest --format json --output trace.json
tracefi export latest --format html --output postmortem.html
```

To rebuild the dashboard (Node 22+):

```bash
cd dashboard
npm ci
npm run build
```

The detail view summarizes recorded APY, protocol liquidity, USDC balance and
exposure limit alongside the provenance timeline. Missing inputs stay unknown.
Experiments never send transactions or rewrite the original trace.

Production assets are bundled; the running dashboard needs no CDN or npm service.
For UI development, run the collector server and `npm run dev` in `dashboard/`.

## Demo

`tracefi demo` records $100,000 of synthetic USDC: a $25,000 proposal passes,
then higher liquidity triggers an $80,000 proposal blocked by the 35% exposure
limit. It prints a post-mortem and a one-variable liquidity experiment.
See the [60–90 second walkthrough](docs/DEMO.md).

## Architecture

```text
Financial agent → SDK / collector → SQLite + canonical SHA-256 snapshots
                                             ↓
                                       Analysis engine
                                      ↙               ↘
                                    CLI         React timeline
```

See [ARCHITECTURE.md](ARCHITECTURE.md). The collector is synchronous and embedded;
there is no ingestion service, external backend or required container.

## Security

```python
with TraceFi(redact=["credential"]) as trace:
    with trace.decision("example") as t:
        t.capture_context({"private_key": "never-stored", "note": trace.secret("sensitive")})
```

Default secret keys are recursively redacted, case-insensitively and ignoring
hyphens/underscores. `trace.secret(value)` is an explicit value wrapper, not a
decorator. Hashes cover **redacted** stored state. This sacrifices exact replay
of secret-dependent decisions. Values embedded in arbitrary strings are not
recognized automatically; callers must wrap or remove them.

New databases have mode `0600`. Dashboard access is loopback-only with Host and
Origin checks. React and HTML exports escape untrusted content. Plain SHA-256
hashes are not signatures or protection against an attacker rewriting the whole
database. See [THREAT_MODEL.md](THREAT_MODEL.md).

## Limitations

This is a development baseline, not a claim of V1 readiness. Instrumentation can
be incomplete, adapter code can change, models can be nondeterministic, and rules
can miss errors or identify correlations rather than causes. SQLite is intended
for a single local collector; cross-thread shared collectors, distributed
collection and multi-process ingestion have not been qualified. Transactions,
LLM responses and caller inputs must fit the documented JSON contract.

Ollama is optional, requires a model installed separately, and has not been
validated by the offline CI. OpenTelemetry export, a signed integrity log,
robust statistical nondeterminism analysis, validated financial outcome metrics,
and a recorded demo video remain future work. PyPI publication requires checking
name ownership, release review and an explicit publish step.

## Development

```bash
python3 -m pip install -e ".[dev]"
ruff check tracefi tests scripts examples
ruff format --check tracefi tests scripts examples
mypy tracefi
python3 -m pytest -q
HYPOTHESIS_PROFILE=stress python3 -m pytest -q tests/test_properties.py
python3 scripts/check_install.py
python3 -m tracefi demo
```

New features are temporarily frozen while hardening. See
[README contract audit](docs/README_CONTRACTS.md),
[manual security review](docs/SECURITY_REVIEW.md),
[hardening results and remaining gates](docs/HARDENING.md),
[CONTRIBUTING.md](CONTRIBUTING.md) and [ROADMAP.md](docs/ROADMAP.md).
Licensed under MIT.

The package, SDK and CLI have been renamed to `tracefi`, `TraceFi` and `tracefi`.
Existing databases remain readable with an explicit `--db` path; their recorded
canonical identifiers and hashes are preserved. See the architecture compatibility
notes.
