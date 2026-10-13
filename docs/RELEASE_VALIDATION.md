# v0.1.0 validation record

Scope: local, sequential, bounded-JSON decision observation and synthetic offline
investigations. This record distinguishes measured checks from unqualified areas.
It does not assert security certification, formal verification, financial
correctness or V1 readiness.

## Executed locally

- Baseline on commit `865d2ff`: 88 tests, Ruff lint/format and mypy passed; original
  offline demo passed. GitHub had no tags or releases; default main matched the
  local checkout and existing CI was green.
- Expanded unit/property/security tests cover original behavior, malformed inputs,
  safe exports, missing/read-only DB handling, span graphs, non-monotonic boundary
  diagnostics, decimal policy thresholds, adapter exceptions/dependencies and
  isolated repeated eval. **139 tests passed** in the final complete run (20.92 seconds); Ruff lint/format
  and mypy passed across 19 core modules.
- Hypothesis stress profile: 34 tests passed in 105.65 seconds with up to 2,000
  examples per property. Finite domains can exhaust earlier; deterministic unit
  cases in that selection do not each generate 2,000 examples.
- The full lending investigation reproduces B 25k → A 20k when only the omitted
  −41% trend is restored; original data remains unchanged. Both lending agents
  process the same eight fixtures with explicit cost/exposure/consistency metrics.
- Real Chromium validation passed empty/list/detail/search/filter/timeline/context/
  evidence/failure/counterfactual/redaction/XSS behavior with zero page errors,
  including malformed structured proposals. A 75.4-second actual-output/browser
  recording and screenshots were generated and inspected.
- Frontend audit found zero known vulnerabilities including development packages.
  The Python environment audit found a pip tooling advisory; upgrading pip from
  26.1.2 to 26.2.1 resolved it and the follow-up audit reported none. This is a
  dated advisory check, not a continuing assurance. TraceFi is unpublished and
  has no third-party runtime Python dependencies.
- A source distribution and universal wheel built successfully. Distribution
  contents and independent installation qualification are qualified by the clean committed-clone gate described below.
- [Measured benchmarks](BENCHMARKS.md) include 100 repetitions per latency and
  1,000/10,000-trace storage sizes, with raw variability and hardware information.

## Mutation evidence

The historical complete run and survivors remain in `mutation-results.json` and
`mutation-survivors.txt`, explicitly dated before this release work. The release
run prioritizes policy thresholds, replay, redaction/atomic exports, boundary
search and SQLite verification. It uses the 40-example property profile and
excludes browser/HTTP integration and the long corruption grid. Selected functions
are rerun when source or guards change; non-selected mutants are not claimed tested.

Mutation review identified gaps for same-filesystem export publication, preserving
creation failures, cleanup after encoding failure and prompt rejection of invalid
span cycles. Those behaviors gained regression tests. Two infinite-loop verification
mutants initially exhausted CPU; bounded graph-rejection assertions distinguish
liveness failure from a successful rejection. Final selected inventory: **840 tested, 644 killed, 196 survived**, with no
remaining timeout/error exit codes. The [full results](release-mutation-results.json)
and [survivors](release-mutation-survivors.txt) combine the fresh run and explicit
reruns after adding independent digest/schema/identifier checks, custom replay
redaction and decimal funding tests. They do not claim a full final mutation run
of every generated function.

Message-only mutations are not automatically financial/security defects; examples
include changing rejection wording or UTF-8 capitalization. Other surviving logic
requires case-by-case review. No arbitrary mutation-score target determines readiness.

## Release gates and unqualified areas

The source release requires passing tests/lint/types, built wheel/sdist, isolated
wheel/editable installation, both offline demos, replay/counterfactual/eval exits,
dashboard startup/browser checks, valid docs/media links and green remote CI before
tagging. GitHub publication must be independently verified against the release
commit and artifact checksums. The final workflow record identifies completed gates.

Not qualified: live Ollama model behavior, financial/RPC execution, historical
returns/backtests, stochastic determinism, distributed or cross-thread shared
collectors, arbitrary large-dataset UI behavior, authenticated audit logs and
security certification. These are [documented limitations](LIMITATIONS.md), not
placeholders for included essential functionality.
