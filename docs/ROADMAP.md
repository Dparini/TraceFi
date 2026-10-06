# Roadmap

**Temporary feature freeze.** Only bug fixes, test coverage, security hardening,
accurate documentation and quality automation are accepted until the hardening
gates pass. Keep SQLite and the dependency-free runtime. Blockchain and new
product capabilities require a demonstrated need after this freeze.

Current version: 0.1 development baseline with the main local workflow already
implemented. These milestones describe release-quality gates, not claims that
later features have been validated in production.

- **0.1:** qualify SDK, span lifecycle, atomic SQLite storage, canonical hashing,
  list/show/export and immutable original state; define schema migration policy.
- **0.2:** strengthen adapter/environment pinning and replay sampling; expand
  credential leakage tests and explicit redaction behavior.
- **0.3:** validate failure rules against labeled fixtures, unknown coverage and
  false-attribution cases; stabilize credible post-mortem terminology.
- **0.4:** qualify scenario runner and agent comparisons; add a validated outcome
  model before reporting simulated returns or drawdown.
- **0.5:** handle counterfactual feature interactions, nondeterministic runs and
  nonmonotone boundaries with statistical uncertainty.
- **0.6:** qualify React timeline and trace explorer accessibility and large local
  datasets. Dashboard exists; the core release gates take precedence.
- **1.0:** stable schema and migrations, documentation/security review, signed
  release artifacts, PyPI name/ownership checks, demo video and GIF, tested
  distribution and clean CI. Publish only after explicit authorization.

Optional future evolution: OpenTelemetry export and independently verifiable
signed trace digests. No exchange, blockchain, token, real-funds executor,
mandatory paid API or distributed infrastructure is planned.
