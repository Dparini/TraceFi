# Manual security review

Date: 2026-10-06. Scope: SDK capture/finalization, canonical JSON, redaction,
SQLite integrity, replay, counterfactual interventions, attribution, scenario
loading, CLI/rendering, loopback HTTP routes, React rendering and optional Ollama
transport. This is a source review with adversarial regression tests, not an
independent penetration test or security certification.

## Findings resolved

| Finding | Fix and regression evidence |
| --- | --- |
| Decimal snapshots and high-precision timestamps could silently collapse distinct inputs | Lossless snapshot round-trip; reject unsupported fractional precision and nonzero sub-microsecond timestamps. Golden/precision/property tests. |
| Cyclic, deeply nested, enormous or exponent-expanded input could exhaust resources | Shared limits on depth, nodes, encoded bytes and numeric digits; exponent checked before expansion. Cycle/size/exponent tests. |
| Duplicate JSON keys/nonfinite literals were ambiguous | Strict bounded parser for DB, datasets, CLI/HTTP interventions and Ollama responses. Duplicate/NaN/precision tests. |
| Custom redaction keys could destroy structural metadata | Reject reserved field names; redact before hashes; bypass traversal of secret subtrees. Reserved-key and cyclic-secret tests. |
| Bool/number equality could conceal auxiliary-table modifications | Compare canonical hashes rather than Python structural equality; verify component references. Tampering regression tests. |
| Adapter state/output mutation or unstable repeated calls could invalidate attribution | Fresh isolated snapshots, copied reports, repeated baseline and intervention checks. Mutation/instability tests. |
| Secret-bearing interventions could appear in reports | Apply recorded redaction before invoking adapters and refuse redacted intervention state. Counterfactual secret test. |
| Malformed policy/observation fields could crash or suggest a market outcome | Defensive scalar/list/object validation, strict proposal validity, input-error reporting, evidence prerequisites. Arbitrary-JSON properties and 2,000 corruption grid. |
| Dangling/reused spans and failed finalization could leave active state | Lifecycle validation, context reset in finally, transactional SQLite writes. Rollback/lifecycle tests. |
| CLI argument/adapter errors and raw report input could expose sensitive values | Generic argument/operation errors, re-redact exports, escape control characters. Security-surface tests. |
| Ollama could follow redirect/proxy configuration outside loopback | No proxy/redirect transport, bounded strict response parser. Mock transport tests; no live model validation. |
| Dashboard readers could write or accept arbitrary adapter code | SQLite mode=ro readers; explicit financial feature and adapter allowlists; loopback Host/Origin restrictions. HTTP and read-only DB tests. |

## Residual risks

- Redaction is field/wrapper based. Secrets placed in unknown free text require
  caller removal; CLI JSON output necessarily includes caller-approved recorded data.
- Trusted Python adapters execute arbitrary code. They are not sandboxed, have no
  enforced execution deadline and may perform external side effects. Use reviewed
  offline adapters for reproducibility. Two matching samples cannot prove determinism.
- Local HTTP remains unauthenticated to allowed local clients. Threaded request
  volume and repeated verification of large datasets can cause denial of service.
  JSON bounds do not bound total dataset file count or total database size.
- SHA-256 is not an authenticated append-only log. A writer able to alter every
  payload and hash can manufacture a self-consistent database. Keep backups and
  independent trusted digests where required. Existing DB permissions are retained.
- Wall clocks, scenario labels and caller assertions can be wrong. No attestation
  proves that the snapshot was the complete input actually used by an agent.
- Failure attribution remains rule-based evidence, not causal or financial proof.
  Missing context, poisoned datasets, model drift and unobserved errors can escape rules.
- Live Ollama and browser interactions were not exercised; local mock/HTTP tests
  cover transport boundaries. No distributed or shared cross-thread collector qualification.

SQLite remains the only core store. No blockchain, funds custody, exchange
integration or new feature was introduced during hardening.
