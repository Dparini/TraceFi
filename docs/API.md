# API and payload contract

```python
TraceFi(db=".tracefi/traces.sqlite3", redact=(), storage=None)
trace.decision(agent, version="unknown", model=None, portfolio=None,
               agent_config=None, policy_config=None)
```

`TraceFi` and decision contexts are context managers. Closing the collector
closes its storage. Capture only JSON-compatible values, finite numbers, `Decimal`
and timezone-aware `datetime` values. Canonicalization converts Decimal and
number values to JSON numbers, normalizes timestamp values and copies inputs.
Lists preserve order. Unsupported objects fail explicitly.

`capture_context`, `capture_decision`, `capture_policy`, `capture_simulation`,
`capture_execution`, `capture_retrieval` and `capture_outcome` create typed spans
and retain the last corresponding observation. Context is frozen after the
first proposal; another proposal requires another trace. Use spans for multiple
tool calls or checks. Active context use is required; contexts are single-use.

```python
with t.span("retrieve-protocols", kind="retrieval") as span:
    span.log({"source": "offline-snapshot", "records": 8})
```

`trace.secret(value)` wraps sensitive values recursively. It is not a decorator.
Default keys: `api_key`, `private_key`, `authorization`, `password`, `secret`,
`access_token`, `refresh_token`. Case, hyphens and underscores are ignored.
Captured observations must be JSON objects; `None` is not a proposal.
Custom keys extend defaults. Avoid configuring redaction for schema/control
fields such as `context_hash` or `trace_id`.

## Adapter input

```json
{
  "context": {"apy": 0.067, "liquidity": 21000000, "price": 1, "oracle_age_seconds": 20},
  "portfolio": {"USDC": 100000},
  "agent_configuration": {"version": "1"},
  "policy_configuration": {"max_exposure": 0.35}
}
```

The agent must receive this state to reproduce the example semantics. For an
existing agent that expects only market state, write an adapter which extracts
`state["context"]` and restores the other dependencies. Retrieval actually used
by an agent must be present in context; the separate retrieval observation
records sources, inclusion/omission and untrusted provenance. Retrieval is not
implicitly added to replay state.

```python
class MyAdapter:
    def decide(self, state):
        return my_agent.decide(state["context"])

def make_adapter():
    return MyAdapter()
# tracefi replay TRACE_ID --adapter my_module:make_adapter
```

## Detector fields

- Data: `context.oracle_age_seconds` versus
  `policy_configuration.max_oracle_age_seconds` (default 300), `context.price`,
  `context.conflicting_sources`.
- Retrieval: string lists `available_features`, `included_features`,
  `required_features`; `untrusted_data` objects with `source`, `content` and
  explicit boolean `suspicious`.
- Proposal: `action`, `asset`, finite nonnegative `amount`, optional `protocol`,
  structured `rationale.factors`.
- Policy: `approved`, `should_reject`, optional `reasons`; configured
  `max_exposure` is interpreted as supply amount / recorded asset balance.
- Simulation: `success`, optional numeric `predicted_effect`, `effect_tolerance`.
- Execution: `status` (`success`, `blocked`, `failed`, `reverted`), optional
  boolean `success` and numeric `actual_effect`.
- Outcome: optional numeric `pnl`, optional observational metadata.

Checks are about these fields, not arbitrary financial correctness. The example
policy assumes a single proposal's exposure; it does not calculate cumulative
portfolio, correlated exposure, slippage or withdrawal balances.

Trace status is `error` for a captured exception, `failed` for failed execution,
`rejected` for a rejected policy and otherwise `success` (completed context).
Thus success does not guarantee all stages were captured. Analysis displays
coverage separately.

## CLI exit codes

0: completed command or matching replay. 1: replay divergence or opt-in eval
regression failure. 2: input/storage/adapter operation error. Database selection
is a global flag: `tracefi --db /path/traces.sqlite3 demo`.

## Integrity and extension boundaries

`SQLiteStorage.get(id, verify=True)` verifies by default; turning verification
off is an explicit low-level diagnostic escape hatch. Public CLI and dashboard
never turn it off. SHA-256 is over canonical redacted snapshots, not original
secret-dependent state. Use the actual trusted adapter and pinned environment;
the recorded agent version alone cannot identify Python source or model weights.

## Dashboard financial experiments

`GET /api/traces/{id}/counterfactual?adapter=deterministic&feature=context.liquidity&value=10000000`
returns a one-variable proposal experiment. The adapter must reproduce the
original recorded proposal. Supported inputs are `context.apy`,
`context.liquidity`, `context.price` and `context.oracle_age_seconds`; the feature
must already be recorded and its alternative value must be a finite number.
The HTTP API accepts only the built-in deterministic adapter. Other models use
explicit trusted CLI adapters. Invalid or unreproducible experiments return 422.
No policy, execution, PnL or original trace is changed.
