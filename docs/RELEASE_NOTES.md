# TraceFi v0.1.0

Local decision provenance, explicit replay, deterministic failure attribution,
single-input counterfactual debugging and agent regression comparisons. SQLite,
Python 3.10+, zero third-party Python runtime dependencies and no paid services.

## Included

- SDK decision/span contexts, redacted independent snapshots, versioned canonical
  JSON and verified SQLite traces/artifacts/parent graphs.
- CLI inspection, analysis, replay/diff, conditional counterfactuals, configurable
  regression exits, safe standalone HTML/JSON exports and loopback React explorer.
- Thirty generic scenarios and eight lending fixtures. The full synthetic lending
  investigation connects an omitted liquidity trend, a negative recorded outcome
  and a changed proposal without claiming financial causality.
- Two lending versions with exposure/cost/consistency comparisons, a recorded
  75-second walkthrough, real browser screenshots and reproducible benchmarks.

## Correctness and security changes

- Reject sampled multiple/non-monotonic boundary transitions, missing/non-numeric
  boundary features and unstable repeated outputs; report conditional brackets.
- Protect existing files and symlinks during atomic export, refuse final DB symlinks,
  use read-only CLI inspection and validate span parent graphs.
- Bound dataset counts/total bytes and reads; validate duplicate HTTP Host/Origin
  headers, safely render malformed proposal fields and avoid duplicate list verification.
- Preserve original eval inputs against mutating adapters; measure repeated-output
  consistency; distinguish failed scenarios and expose explicit unsuccessful simulation.
- Account for existing USDC protocol positions in an explicitly selected policy
  mode; use high-precision decimal threshold comparison and refuse underflowed ratios.

## Validation and installation

See [release validation](RELEASE_VALIDATION.md), [security review](SECURITY.md),
[benchmarks](BENCHMARKS.md) and [reproduction commands](DEMO.md).
The GitHub release includes a wheel, source distribution and checksums. Install
an asset with `python -m pip install /path/to/tracefi-0.1.0-py3-none-any.whl`, or
clone the `v0.1.0` tag and run `python -m pip install .`. No PyPI publication occurred.

```bash
tracefi demo --case-study
tracefi replay latest --adapter lending-v1
tracefi serve
```

## Known limitations

Explicit adapters are trusted unsandboxed code. Hashes are not authenticated
signatures; instrumentation may be incomplete. Redaction does not discover all
free-text secrets. A matching replay does not prove determinism; finite boundary
sampling cannot prove monotonicity or causality. Financial outcomes are synthetic
fixtures; there is no validated return/drawdown model or real execution. Local
sequential collection is qualified, distributed ingestion is not. Live Ollama
behavior remains unverified. Mutation survivors are disclosed test debt, not
blanket evidence of equivalence. [Complete limitations](LIMITATIONS.md).
