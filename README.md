# AgentTrace

**Observability and debugging for autonomous financial agents.**

Understand not only what an agent did, but why, with what information,
and where failures occurred.

AgentTrace is an open-source observability and debugging framework that makes
autonomous financial-agent decisions reproducible, auditable and diagnosable.

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
.venv/bin/agenttrace demo
.venv/bin/agenttrace analyze latest
.venv/bin/agenttrace serve
# Open http://127.0.0.1:8765
```

```python
from agenttrace import AgentTrace

with AgentTrace(redact=["credential"]) as trace:
    with trace.decision(agent="yield-agent", version="1.4.2") as t:
        t.capture_context({"apy": 0.067, "liquidity": 21_000_000})
        t.capture_decision({"action": "SUPPLY", "asset": "USDC", "amount": 25_000})
        t.capture_policy({"approved": True})
        t.capture_simulation({"success": True, "mode": "synthetic"})
        t.capture_execution({"status": "success", "mode": "synthetic"})
    print(t.trace_id)
```

```text
Agent → Trace → Data → Retrieval → Decision → Policy
                                                ↓
                                           Simulation
                                                ↓
                                            Execution
                                                ↓
                                            Post-mortem
```

## Why AgentTrace?

PnL tells you what happened. A trace preserves the inputs, retrieved evidence,
structured decision factors, policy checks, simulation and execution results
that help investigate it. A negative outcome does not automatically imply an
agent error. AgentTrace does not evaluate whether a financial decision was
objectively right.

## Trace Anatomy

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
agenttrace list
agenttrace show latest
agenttrace replay latest --adapter deterministic
agenttrace diff TRACE_A TRACE_B
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

## Failure Analysis

```bash
agenttrace analyze latest
agenttrace analyze latest --json
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
agenttrace counterfactual latest --adapter deterministic \
  --feature context.liquidity --value 10000000
agenttrace counterfactual latest --adapter deterministic \
  --feature context.liquidity --low 1000000 --high 30000000
agenttrace why-change TRACE_A TRACE_B --adapter deterministic
```

Counterfactuals change one input at a time. The chosen adapter must reproduce the
original trace (both traces for `why-change`). A single sufficient change is
reported as a driver conditional on the recorded state. Interactions may require
several changes together. Boundary search returns a numerical bracket under a
monotonic-transition assumption; equal endpoints do not prove insensitivity.
Changing a policy input reruns the **agent**, not the policy or execution system.
The engine does not fabricate counterfactual returns.

## Regression Testing

```bash
agenttrace eval --baseline agent-v1 --candidate agent-v2 --dataset scenarios/
agenttrace eval --baseline agent-v1 --candidate agent-v2 --fail-on-regression
agenttrace run --dataset scenarios/ --adapter deterministic
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
findings and download standalone HTML post-mortems. Every read verifies trace,
snapshot, span and artifact hashes. An empty database has an explicit empty state.

```bash
agenttrace serve --port 8765
agenttrace export latest --format json --output trace.json
agenttrace export latest --format html --output postmortem.html
```

To rebuild the dashboard (Node 22+):

```bash
cd dashboard
npm ci
npm run build
```

Production assets are bundled; the running dashboard needs no CDN or npm service.
For UI development, run the collector server and `npm run dev` in `dashboard/`.

## Demo

`agenttrace demo` records $100,000 of synthetic USDC: a $25,000 proposal passes,
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
with AgentTrace(redact=["credential"]) as trace:
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
python3 -m unittest discover -s tests -v
python3 -m agenttrace demo
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [ROADMAP.md](docs/ROADMAP.md).
Licensed under MIT.
