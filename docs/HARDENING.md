# Hardening validation

2026-10-06. New product features are frozen. SQLite remains the only core store;
the Python runtime has no third-party dependencies and no blockchain integration.

## Completed checks

- 88 tests pass locally, including full loopback HTTP integration. Hashing,
  redaction, replay, counterfactuals, failure attribution and storage integrity
  have adversarial regression tests.
- Ten Hypothesis properties use up to 200 examples in normal CI. The local stress
  run passed with up to 2,000 examples each (finite domains may exhaust earlier).
  A separate attribution grid exercised 2,000 corrupted observation combinations.
- Counterfactual cases include invalid paths, absent/added fields, secret inputs,
  mutating adapters, unstable baselines/interventions, boolean versus numeric
  amounts, irrelevant inputs, interactions, multiple drivers, equal endpoints,
  three-way decisions, huge values and adjacent representable floats.
- Ruff lint/format and mypy pass across the core. Regular CI tests Python 3.10,
  3.12 and 3.14; scheduled/manual CI additionally runs property stress and mutations.
- A fresh local Git clone built a wheel, installed it without dependencies into a
  clean environment and ran demo, replay, analyze, eval and standalone HTML export
  outside the source tree. The package includes all 30 scenarios and built React assets.
- Dashboard rebuild passes; GitHub CI checks that generated assets are committed
  and audits runtime JavaScript dependencies. No unnecessary core dependency was added.
- [Manual security review](SECURITY_REVIEW.md) records fixes and residual risks.
  [README contract audit](README_CONTRACTS.md) maps operational promises to code,
  tests and explicit limitations. Browser visual QA and a live Ollama run remain unverified.

## Mutation testing

The first complete run used mutmut 3.8.0 on hashing, redaction, counterfactuals
and attribution: **1,610 mutations, 913 killed, 697 survived**. It excluded the
HTTP integration test and the long attribution grid; neither replaces targeted
unit/property tests. These counts describe that initial snapshot, not the final
code. Follow-up runs use the 40-example Hypothesis mutation profile and explicitly
rerun selected functions after adding behavioral guards.

Inspected survivors led to tests for object-depth enforcement, exact resource
limits, markers inside arrays, ambiguous unchanged paths, proposal validity,
positive evidence prerequisites, simulation tolerance and boundary result sides.
Exception-message-only mutations are not treated as financial/security failures
when the exception type and rejection behavior are preserved. Other survivors
remain test debt; they must not all be called equivalent without inspection.

The [mutation inventory](mutation-survivors.txt) and
[module counts](mutation-results.json) accompany this report: **1,641 tracked
mutations, 1,074 killed and 567 surviving**, without timeouts or unchecked entries. It combines
results from the full run and explicit reruns of affected functions; it is not a
claim that every mutant was executed in one final clean run. Storage, HTTP,
tracing and the example models were tested but are outside the configured
mutation scope. Scheduled/manual CI generates a fresh run artifact.

## Remaining release gates

The feature freeze remains in effect. Review untriaged surviving logic mutations,
qualify browser interactions and large-dataset behavior, and add release/schema
migration qualification before claiming V1 readiness. No test count, matching
replay or mutation score establishes causal or financial correctness.
