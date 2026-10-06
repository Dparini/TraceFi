# Architecture

AgentTrace observes decision processes. The unit of collection is a decision
trace, not a trade, position, PnL series or hidden LLM reasoning transcript.

## Local pipeline

1. `AgentTrace.decision()` creates a single-use trace context.
2. Capture methods redact and canonicalize inputs immediately, making independent
   snapshots. Captures append typed spans; custom spans can be nested.
3. On exit, wall timestamps and monotonic durations are finalized. The collector
   hashes each state component and the combined state, then writes a complete
   trace, its spans and snapshot artifacts in one SQLite transaction.
4. Reads verify the full payload digest, component and combined hashes, and the
   redundant span/artifact rows. Analysis never silently accepts corrupted data.
5. Replay and counterfactuals invoke an explicitly selected adapter on copies of
   the captured state. They do not call the original executor.
6. CLI and dashboard consume the same storage and analysis interfaces.

The collector is the in-process SDK, deliberately avoiding an ingestion daemon.
The synchronous write means the caller knows persistence has finished when the
context exits. Storage failure raises; an application requiring fail-open
telemetry must explicitly handle it. A persistence failure during an application
exception may supersede that exception through normal Python exception chaining.

## Data contract

Trace state consists of `context`, `portfolio`, `agent_configuration` and
`policy_configuration`. Additional observations are `retrieval`, `proposal`,
`policy`, `simulation`, `execution` and `outcome`. Spans contain parent IDs,
UTC timestamps, monotonic durations, status and timestamped payload events.
Only outcome-level structured rationale is captured. Raw internal chain of
thought is outside the contract and must not be logged by callers.

Schema version 1 and canonicalization version `agenttrace-json-v1` are explicit.
The JSON format sorts string object keys, preserves array order and Unicode,
normalizes equivalent finite numbers and timezone-aware ISO timestamp values to
UTC microseconds. Naive Python datetime values, non-finite numbers, non-string dictionary
keys and unsupported objects are rejected. Object keys themselves are never
normalized. Strings outside the recognized timestamp format are ordinary text,
including timestamp-looking strings without an offset. This is a project-specific canonical format, not RFC 8785.

`context_hash`, `portfolio_hash`, `policy_hash` and `agent_config_hash` cover stored
redacted snapshots. `state_hash` covers the four state components together. The
storage-level digest includes all trace observations. These hashes detect
modification relative to a trusted digest; they are not a tamper-proof audit log.
There is no raw-state hash that could disclose a secret through guessing.

## Storage

`traces` stores indexed metadata, the canonical payload and its digest. `spans`
stores typed timeline records. `artifacts` stores the four state snapshots and
their hashes. Foreign keys and atomic transactions prevent partial traces.
The local SQLite database is private on creation. Shared cross-thread writers
are not supported; use one collector per sequential local workflow.

Finalization occurs at context exit, so a killed process can lose an in-flight
trace. There is no streaming durability claim. Trace IDs use random UUIDs rather
than sortable ULIDs; timestamps provide list ordering.

## Analysis semantics

Detectors evaluate structured assertions supplied by instrumentation. An oracle
age violation is an observed condition, while an omitted available required
feature is a likely retrieval issue. Missing evidence remains unknown. Findings
are prioritized for inspection but all are retained. The priority order is not a
mathematical claim about the cause of financial loss.

Replay compares full proposals with canonical hashing. Counterfactuals compare
operational signatures (action, protocol, asset, amount), so wording changes in
rationale alone do not create a decision boundary. Baseline reproduction is
required before experiments. One replay does not establish determinism.

Scenario evaluation measures proposals, with blocking policy checks. Trace
scenario runs additionally inject explicitly labeled faults. Synthetic data is
not a backtest or a source of financial performance estimates.

## Dashboard

A built React client is shipped as local static assets. A Python loopback-only
HTTP server exposes GET routes for verified trace summaries, detail and HTML
exports. No mutable endpoint, external font, CDN, analytics or remote collector
is required. Host/Origin checks reduce cross-site access; local process access
and an untrusted browser extension remain outside its protection boundary.

## Extension points

`ModelAdapter.decide(state)` isolates local deterministic and optional Ollama
models. Trusted `module:factory` adapters can integrate other agents. Storage is
injected through `AgentTrace(storage=...)`; compatible implementations provide
`save`, `get`, `list` and `close`. OpenTelemetry mapping can be added without
changing the decision-state contract. Schema migrations and cryptographic
signatures need explicit design before a stable V1 contract is declared.
