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
Custom keys extend defaults. Schema/control field names such as `context_hash`
and `trace_id` are rejected as custom redaction keys.

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
  `max_exposure` defaults to supply amount / recorded asset balance. Explicit
  `exposure_basis: total_portfolio` selects USDC post-supply protocol exposure
  using `portfolio.total_value_usdc` and `portfolio.positions` (protocol → USDC).
- Simulation: `success`, optional numeric `predicted_effect`, `effect_tolerance`.
- Execution: `status` (`success`, `blocked`, `failed`, `reverted`), optional
  boolean `success` and numeric `actual_effect`.
- Outcome: optional numeric `pnl`, optional observational metadata.

Checks are about these fields, not arbitrary financial correctness. The default example policy checks a single proposal against an asset balance.
Enhanced total-portfolio mode includes existing per-protocol positions, principal
funding and withdrawal position bounds. Neither mode calculates correlated risk
or complete transaction/slippage mechanics. Financial arithmetic refuses
nonfinite/underflowed ratios; supply thresholds use high-precision decimal comparisons.

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
Lending experiments also allow fixed `context.markets.protocol_a|protocol_b`
fields: `supply_apy`, `liquidity_usdc`, `liquidity_trend_24h`,
`oracle_age_seconds` and `transaction_cost_usdc`. A missing trend leaf can be
added to restore an omitted signal; its parent market must exist.
The HTTP API accepts only `deterministic`, `lending-v1` and `lending-v2`. Other models use
explicit trusted CLI adapters. Invalid or unreproducible experiments return 422.
No policy, execution, PnL or original trace is changed.

## Bounded JSON and numeric precision

Canonicalization sorts keys, preserves list order and Unicode scalar text,
normalizes finite numbers and timezone-qualified timestamp values, and emits
UTF-8 without whitespace. It rejects cycles, non-string keys, nonfinite values,
naive Python datetimes, surrogate characters and unsupported objects. Duplicate
JSON keys are rejected on read. Limits: depth 64, 100,000 visited nodes, 8 MiB
canonical bytes and 4,096 expanded numeric digits. Timestamp precision is at
most microseconds; additional zero fractional digits are accepted.

Hashing supports precise Decimal values; persisted snapshots must also round-trip
losslessly through the Python JSON number representation. Unrepresentable
fractional Decimals are rejected rather than silently rounded. Financial
arithmetic additionally requires numbers in the finite float range and excludes
booleans. Negative zero and numerically equivalent integral numbers canonicalize
identically; booleans and numbers remain distinct.

Counterfactuals require two matching original replays and two matching results
per intervention; repeated matches are not proof of determinism. Boundary
iterations must be integers in 1–60 and endpoints finite and strictly ordered.
Third operational decisions invalidate a binary boundary search. Dot paths only
traverse object keys in the four state roots; lists are atomic and dotted/empty
keys are rejected by why-change. Malformed analysis evidence is surfaced through
`input_errors`, and cannot support `MARKET_OUTCOME`.

## v0.1.0 operational changes

Inspection opens SQLite read-only and never creates a missing DB. Final DB
symlinks are refused. `list` adds action/amount/asset summaries from the same
verified payload, avoiding duplicate dashboard verification. Parent graphs must
reference existing spans and be acyclic. Hashes still cover the same canonical
byte format; no migration rewrites original payloads.

Export filenames are create-only, private and atomically published. Existing
files/symlinks fail rather than being overwritten. Parent directories are trusted.
Numerical search samples up to 17 points and rejects observed multiple or
non-monotonic transitions; returned diagnostics never claim proven monotonicity.
See [counterfactual assumptions](COUNTERFACTUALS.md) and [regression metrics](REGRESSION_TESTING.md).
