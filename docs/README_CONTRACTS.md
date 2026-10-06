# README contract audit

Reviewed 2026-10-06. This table covers the operational claims in the README;
financial motivation and examples are illustrative. A passing test supports the
specified contract, not unrestricted correctness or financial suitability.

| README promise | Code / verification | Scope and limits |
| --- | --- | --- |
| Local, offline, dependency-free core | `pyproject.toml`, `scripts/check_install.py` | Development tools and UI build dependencies are optional; Ollama needs its own local service. |
| Installable Python 3.10+ development release | CI 3.10/3.12/3.14, clean-clone wheel smoke test | Local execution used 3.14; other versions are CI checks. No PyPI publication claim. |
| SDK quick-start, automatic captures | `sdk`, `tracing`; `test_replay_and_snapshot` | User instruments the actual inputs and checks. Uninstrumented evidence cannot be recovered. |
| UUID IDs, UTC timestamps, monotonic duration | `tracing.identifier/now`, `perf_counter_ns`; nested-span tests | Wall-clock correctness depends on the host; monotonic durations do not authenticate timestamps. |
| Independent snapshots, one proposal, frozen context | `test_context_frozen_and_none_proposal_rejected`, replay properties | Mutable returned reports and adapters cannot rewrite recorded inputs. |
| Nested spans and exception recording | `test_exception_type_only_and_nested_spans`, span lifecycle/rollback tests | Spans must close in stack order. Storage errors propagate. Exception messages are omitted. |
| Structured rationale, no hidden chain-of-thought capture | SDK API/source inspection, example adapters | Arbitrary caller payloads remain caller responsibility. There is no automatic extraction of internal model reasoning. |
| Canonical hashing | Golden-byte, order, Decimal, timezone and Hypothesis tests | Bounded JSON, strict timestamps and lossless snapshot contract in API.md. Hashes cover redacted data. |
| Replay complete structured decision | `test_replay_and_snapshot`, marker/alias/malformed-output tests | Requires explicit trusted adapter and pinned external dependencies; a match is not proof of determinism. |
| Replay divergence exits 1; no transactions | `cli.main` source inspection and clean-install replay | Adapter code is trusted and can have side effects; built-ins do not execute financial transactions. |
| Explicit adapters and version labels | `models.load_adapter`, CLI required arguments | Trace contents do not dynamically select Python factories. Version labels do not pin code. |
| Diff recorded inputs, proposals and policy | `analysis.diff/changed_paths`, why-change tests | Structural differences do not prove causality. |
| Deterministic failure taxonomy | `test_scenario_fault_attribution`, multiple-findings tests | Rules operate only on documented fields; arbitrary financial faults are not covered. |
| Freshness, conflicts, missing retrieval, malformed proposals | Policy/attribution edge and property tests, 2,000 corruption grid | Malformed observations appear in `input_errors`; missing data stays unknown. |
| Adversarial inputs observable | Scenario attribution tests; `analyze` suspicious flag | Requires instrumented provenance and explicit suspicious flag; not a general injection detector. |
| Multiple findings and uncertainty | Finding priority tests, source inspection of certainty labels | Likely class is a presentation priority, not a statistically calibrated confidence. |
| Loss alone does not mean failure | `test_no_false_market_failure`, market-outcome guards | Valid recorded state and positive policy/simulation/execution evidence required; unseen errors remain possible. |
| One-variable counterfactual | Irrelevant-input property, mutating-adapter and secret guards | Two repeated calls must match both baseline and intervention. This does not establish stochastic determinism. |
| Conditional drivers, interactions, multiple drivers | `test_why_change_identical_interactions_and_multiple_drivers` | No primary driver when zero or multiple single changes suffice; lists are atomic; ambiguous paths rejected. |
| Numerical boundary bracket | Equal-endpoint/third-outcome/adjacent-float/extreme-bound tests | Monotonic binary-transition assumption; third observed decisions rejected; interval interiors may contain unseen changes. |
| Agent-only intervention, no fabricated returns | Counterfactual implementation/source inspection | Policy/execution/outcome are not rerun. |
| 30 offline scenarios, same packaged dataset | `test_packaged_scenarios_match_repository`, clean-install probe | Synthetic inputs and explicit faults, not financial calibration. |
| Comparable eval inputs, validity, unsafe proposals and exposure | `test_regression_dataset`, invalid-decision scoring test | No real execution; zero execution policy violations by construction; average exposure is not calibrated risk. |
| Opt-in regression exit 1 | `cli.main` tracked-regression branch | Does not decide which model is financially better. |
| Local React explorer, timeline, evidence and empty state | React source review, deterministic build, HTTP integration test | Browser visual/interaction QA is not available in this environment. Search/filter/tabs are source-reviewed, not browser-tested. |
| Dashboard counterfactual experiments | `test_local_api_and_origin_guard` | Fixed synthetic adapter, recorded numeric allowlist, no arbitrary Python adapter parameter. |
| Standalone JSON/HTML export | Escape/redaction tests, clean-install HTML export | Export contains recorded data; caller must redact free-text secrets. |
| Verified trace, component, span and artifact reads | Tampering tests, bool/number auxiliary-row test, strict malformed-row tests | SHA-256 detects mismatches, not wholesale malicious rewriting. Low-level verification opt-out is explicit. |
| Demo passing 25k and blocked 80k, liquidity driver | `demo.run_demo`, clean-install CLI sequence | Entirely synthetic; no return claims. |
| Recursive redaction and explicit secret wrapper | Storage-wide Hypothesis redaction, custom/reserved-key tests | Default/configured key names and wrappers only; unknown free-text credentials are not recognized. |
| New DB mode 0600, loopback and Host/Origin checks | `storage.__init__` source review, HTTP integration test, readonly test | Existing file permissions unchanged; local hostile processes and denial of service remain risks. |
| HTML and React escape untrusted content | Export injection test; React text-only render review | No dangerous inner HTML; terminal controls also escaped in text reports. |
| Compatibility with original canonical identifier | `test_original_canonical_format_remains_readable` | Valid bounded losslessly representable legacy traces only; oversized or ambiguous old payloads fail safely. |
| Limitations and future work | API, architecture, threat model and roadmap cross-review | No signed log, distributed ingestion, validated returns/drawdown, statistical nondeterminism analysis, OpenTelemetry or demo video claimed. |

Development claims are enforced by lint/type checks, the regular test suite,
Hypothesis stress profile and clean installation. Mutation results identify
remaining test gaps; their existence is not evidence that every mutant was killed.
