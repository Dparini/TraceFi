# Supported scope and limitations

v0.1.0 supports sequential, local, instrumented financial-agent investigations
with bounded JSON, SQLite, explicit adapters and synthetic offline examples.
Python 3.10, 3.12 and 3.14 are exercised in CI. Browser automation qualifies the
packaged Chromium workflow; operating-system coverage is macOS locally and Linux
in CI, not a claim that every Python/browser/OS combination was tested.

- Instrumentation can omit dependencies, retrieved evidence, code revisions or
  tool state. No mechanism proves that recorded context was the complete actual input.
- Hashes validate internal consistency, not authenticity, retention or completeness.
  A filesystem writer can rewrite all hashes, delete traces or misstate wall clocks.
- Original schema/canonical identifiers remain accepted for valid, bounded,
  losslessly representable traces. No automatic migration rewrites data; unsupported
  schema versions fail. Back up databases before updating.
- There is one final synchronous transaction per decision. Process death can lose
  an active trace, and storage failure raises into the caller. Shared cross-thread
  collectors and distributed/multi-process ingestion are not qualified.
- Adapter code is trusted and unsandboxed. Built-ins have no financial execution
  capability; third-party adapters may have arbitrary side effects or hang.
- Exact replay refuses redacted state. Version names do not pin source, weights or
  dependencies. A matching comparison, including two samples, does not establish
  global or statistical determinism.
- Boundary searches assume a monotonic binary operational transition. Finite grid
  sampling can falsify that assumption but cannot prove it or find every narrow
  transition. Returned brackets are conditional; missing numeric features are unsupported.
- Failure rules operate on documented evidence, retain unknowns and can be wrong.
  They do not infer internal reasoning, prove causality or decide financial rationality.
- Example policy modes are simple allocation controls, not calibrated risk engines.
  They omit correlated risk, credit analysis, multi-asset pricing and complete gas/
  slippage/withdrawal mechanics. The lending simulation models immediate feasibility
  and cash effects; its stressed outcome is an explicit fixture, not a return forecast.
- Dataset count/bytes and individual JSON structures are bounded. Database size,
  filesystem scan time, HTTP concurrency and arbitrary adapter compute are not.
- Dashboard lists at most 1,000 latest verified traces. List verification is linear
  in payload size; benchmarks do not qualify arbitrary large-dataset responsiveness.
- Unknown free-text secrets and external code logs require caller handling. Local
  HTTP is unauthenticated; do not expose it to a network or untrusted browser environment.
- Live Ollama, financial RPC/execution, historical backtesting, signed logs,
  OpenTelemetry, robust statistical replay and validated return/drawdown models are
  not included. No paid service, token or blockchain dependency is required.

Mutation survivors are disclosed as test debt rather than automatically labeled
harmless. Performance measurements, test counts and recorded demos are evidence
for a specific scope, not security certification or financial guarantees.
