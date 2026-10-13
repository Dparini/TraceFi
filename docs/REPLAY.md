# Replay and decision comparison

`tracefi replay TRACE_ID --adapter deterministic` loads a verified local trace,
restores context, portfolio and agent/policy configurations, and invokes only
the selected adapter's `decide(state)`. It does not invoke the captured executor.
Built-ins `deterministic`, `agent-v1`, `agent-v2`, `lending-v1` and `lending-v2`
have no financial execution capability. `ollama` is optional and local.

A full canonical hash comparison includes action, amount, protocol, asset,
rationale and any other structured output. Different rationale counts as replay
divergence even when the operational action matches. Matching prints a matching
decision, never a proof of global determinism. Divergence exits 1; errors exit 2.

```bash
tracefi demo --case-study
tracefi replay latest --adapter lending-v1 --json
tracefi replay latest --adapter lending-v2 --json
tracefi diff TRACE_A TRACE_B
```

Explicit `module:factory` adapters execute trusted local Python code. Missing
modules/dependencies report a sanitized error. Trace content never selects an
arbitrary Python module. Pin source revisions, environment, model weights and
hidden dependencies yourself; the recorded version is a label, not an attestation.
An incompatible adapter can diverge, fail or coincidentally match. No automatic
version-compatibility inference is made.

Redacted values in any state object, including nested lists, make exact replay
unavailable and are refused. A marker appearing only as part of a longer string
is ordinary text. Missing state objects/proposals, corrupted storage and invalid
adapter output objects also fail. The library copies restored state and report
values; adapter mutation cannot rewrite the original trace.

Nondeterministic adapters may match once and later diverge. Counterfactuals use
two baseline and intervention calls, while this replay command makes one call.
Repeated matching is evidence, not statistical qualification. Best-effort replay
means using the available recorded state with an explicit adapter and reporting
match/divergence/unsupported state honestly; there is no secret reconstruction,
transaction replay or fabricated dependency restoration.
