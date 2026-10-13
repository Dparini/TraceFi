# Agent regression testing

```bash
tracefi eval --baseline agent-v1 --candidate agent-v2
tracefi eval --baseline lending-v1 --candidate lending-v2 --dataset lending
tracefi eval --baseline lending-v1 --candidate lending-v2 --dataset lending \
  --fail-on-regression
```

Both agents receive independent copies of the same scenarios. Each decision is
called twice to measure repeated structured-output consistency. Adapter mutation
cannot alter the policy input or another agent's scenario. Errors are reported
by type with a failed-scenario count; an error is not silently called a safe proposal.

Generic fixtures include 30 normal, market, data, adversarial and execution
scenarios. Eval measures fresh agent proposals; injected proposal/execution
fault overrides are reserved for `tracefi run` and never contaminate agent scoring.
The lending dataset adds eight explicitly synthetic financial comparisons.
User datasets are strict JSON: at most 1,000 files, 8 MiB per input and 64 MiB
summed file sizes; symlink files and duplicate/non-string IDs are rejected.

## Metrics and interpretation

Validity checks the documented action/asset/amount contract, including HOLD amount
zero and rejecting booleans. Consistency counts two identical complete outputs;
it is not global determinism. Unsafe proposals/policy rejections count deterministic
control failures. No real execution occurs, so execution policy violations are
zero by construction. Average proposed exposure is not a calibrated risk score.

Lending fixtures explicitly opt into `synthetic-lending-v1` metric assessment,
derived from inputs rather than agent self-report. Mean maximum protocol exposure
includes existing positions and the proposed principal, using fixed captured
pre-trade total value; fees do not adjust that denominator. Proposed transaction costs,
missing trend and declining trend counts describe proposals **including blocked
ones**. `financial_metrics_scenarios` reports coverage; absent metrics remain null.
Those metrics do not estimate default probability, return or drawdown.

The report separates directional **improvements**, configured **regressions** and
**trade-offs outside configured gates**. Lower cost can mean less participation;
more rejections can mean a control is working. No automatic overall winner is declared.

Default CI gates: valid decisions (higher), unsafe proposals (lower), average
proposed exposure (lower), consistent decisions (higher), failed scenarios (lower).
With `--fail-on-regression`, a deterioration in any configured gate exits 1.
Override gates by repeating `--regression-metric`:

```bash
tracefi eval --baseline lending-v1 --candidate lending-v2 --dataset lending \
  --regression-metric valid_decisions \
  --regression-metric declining_liquidity_proposals --fail-on-regression
```

A gate with unavailable data cannot establish a regression. Read coverage and
failure counts before drawing conclusions. The [case study](FINANCIAL_CASE_STUDY.md)
reports observed fixture numbers and explains why lower costs do not settle the
higher-exposure trade-off.
