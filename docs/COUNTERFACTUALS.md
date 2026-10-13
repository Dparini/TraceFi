# Counterfactual debugging

```bash
tracefi counterfactual TRACE_ID --adapter deterministic \
  --feature context.liquidity --value 10000000
tracefi counterfactual TRACE_ID --adapter deterministic \
  --feature context.liquidity --low 1000000 --high 30000000
tracefi why-change TRACE_A TRACE_B --adapter deterministic
```

The adapter must match the entire original decision twice (both originals for
`why-change`). Each intervention runs twice on fresh copies; divergent full
outputs are refused. This guards simple instability, not stochastic determinism.
Adapter exceptions propagate through the API and are sanitized on the CLI.

Operational sensitivity compares action, protocol, asset and amount. Rationale-only
changes do not count as an action boundary, although unstable rationale prevents
repeatability qualification. Booleans remain distinct from numbers.

## Paths and interventions

Paths start at `context`, `portfolio`, `agent_configuration` or
`policy_configuration`, followed by nonempty object keys. Intermediate objects
must exist; a single intervention can add a missing leaf, as required to restore
omitted retrieval evidence. Lists are atomic values, not index-addressable paths.
`why-change` refuses dotted/empty keys because dot paths would be ambiguous.
Redacted intervention state is refused; originals are never rewritten.

Changing policy configuration reruns the **agent**, not the independent policy,
simulator or executor. No hypothetical PnL is generated. A sufficient single
change is conditional on this state; zero or several sufficient changes leave
the primary driver undetermined. Interacting variables can require joint changes.

## Numerical boundary assumptions

A boundary feature must already be recorded and numeric. Endpoints must be finite
and strictly ordered; iterations must be an integer from 1 to 60 (default 24).
The engine samples up to 17 distinct points before bisection. More than two
operational decisions or more than one sampled transition is an explicit
unsupported/ambiguous error. Equal samples yield no sampled boundary, not a
proof of insensitivity. Adjacent representable endpoints stop refinement.

Returned intervals are **local brackets under an unproven monotonic binary-transition
assumption**. Finite samples cannot detect every narrow transition or discontinuity.
The response includes sample count, sampled transition count and
`monotonicity_proven: false`. CLI errors have stable CF diagnostic codes and safe
static descriptions. A threshold at the lower endpoint with no differing sample
has no bracket; a differing upper endpoint can bracket a transition at that limit.

Even a successful bracket is not a precise global threshold or causal proof.
Changing financial inputs may also make a proposal invalid under controls not
rerun by this experiment. The [lending investigation](FINANCIAL_CASE_STUDY.md)
uses a single restored liquidity trend rather than pretending to infer a return.
