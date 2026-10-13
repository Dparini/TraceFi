# A missing liquidity signal

This is a fully synthetic, local lending-market investigation. It is not
historical data, a backtest, investment advice or an executable financial strategy.
No chain, RPC, signing key or real funds are used.

## Recorded environment

The portfolio is denominated in USDC at an assumed $1 unit value: total value
100,000, available cash 80,000, existing claims of 15,000 on Protocol A and 5,000
on Protocol B. Maximum **per-protocol post-supply exposure** is 35% of total value.
Exposure uses the captured pre-trade total value as a fixed denominator; fees
are modeled separately and do not reduce that denominator. The example does
not model correlated exposure or cross-asset valuation.

- Protocol A: 4.1% supply APY, 35,000,000 available USDC liquidity, +2% 24-hour
  liquidity trend, oracle age 20 seconds, estimated immediate transaction cost 12 USDC.
- Protocol B: 6.7% supply APY, 21,000,000 available liquidity, −41% 24-hour trend,
  oracle age 40 seconds, estimated cost 18 USDC.
- Freshness threshold: 300 seconds, asserted by synthetic producer inputs. No
  independent oracle authenticity or timestamp attestation is implied.

Fixtures live in `tracefi/case_study/scenarios/`. The `omitted-trend` snapshot
contains B's trend; the agent's recorded `context.markets.protocol_b` omits it.
A data span and retrieval record preserve the full snapshot, source omission and
available/required/included feature lists. Retrieval evidence is not implicitly
injected into the adapter's context during replay.

## Strategy and controls

`lending-v1` selects the highest eligible APY, requires at least 10M liquidity
and a fresh oracle, rejects a recorded trend below −20%, and respects policy
headroom with a maximum 25,000 allocation. A missing trend is an explicit unknown,
not automatically a veto. The rationale records that unknown.

It proposes **SUPPLY 25,000 USDC → Protocol B**. The policy independently checks
existing exposure: `(5,000 + 25,000) / 100,000 = 30%`, below 35%. Enhanced policy
mode is explicitly selected with `exposure_basis: total_portfolio`. The legacy
asset-balance mode remains the default for generic examples. Policy validation
rejects malformed portfolios, unfunded principal, invalid proposals and exposure
violations. It is a small example control, not a complete financial risk engine.

Simulation checks immediate cash availability including the modeled cost and
reported market liquidity. Expected cash delta is −25,018 USDC; synthetic execution
records exactly that delta. Future yield, market liquidity changes, credit losses
and exit prices are outside that simulation's scope.

Seven days later, the fixture records: +32 interest, −1,835 stressed exit discount,
−18 transaction cost, giving **−1,821 USDC**. Interest is rounded from a simple
7-day APY illustration. The exit discount is **predeclared stress data**, not a
prediction derived from the liquidity trend. A liquidity decline does not by
itself imply impaired principal or this discount. No alternative return is computed.

## Investigation

```bash
tracefi demo --case-study
tracefi analyze latest --json
tracefi replay latest --adapter lending-v1
tracefi counterfactual latest --adapter lending-v1 \
  --feature context.markets.protocol_b.liquidity_trend_24h --value -0.41
tracefi serve
```

- **Observed fact:** the original snapshot contains a required trend that the
  included context lacks; exposure policy, immediate simulation and execution pass.
- **Inferred explanation:** `RETRIEVAL_FAILURE` is a likely interpretation of the
  omission. The rule does not establish that omission caused the financial loss.
- **Counterfactual observation:** restoring only B's −41% trend changes the proposal
  to **SUPPLY 20,000 → Protocol A**. A's existing 15,000 plus 20,000 equals its
  35% exposure limit. No counterfactual transaction or future outcome is generated.
- **Unknown:** whether the agent would have obtained a better financial outcome,
  whether the original incomplete-information decision was irrational, and what
  additional uninstrumented signals might matter.

Removing the outcome does not remove the retrieval evidence. Negative PnL is
not the classifier's proof. Matching replay reproduces the full proposal and
rationale using this explicit code version; it is not a global determinism proof.

## Version comparison

Eight fixtures vary missing/complete trends, healthy liquidity, oracle staleness,
liquidity stress, fees, yield and an invalid yield quote.
`lending-v2` raises allocation to 50,000, tolerates trends down to −60%, and avoids
costs that exceed a simple seven-day interest budget. It deliberately illustrates
an aggressive change with a cost improvement and risk regressions.

```bash
tracefi eval --baseline lending-v1 --candidate lending-v2 --dataset lending
tracefi eval --baseline lending-v1 --candidate lending-v2 --dataset lending \
  --fail-on-regression
```

Both versions return eight valid, repeatedly matching proposals. Unsafe proposals
and policy rejections rise from 0 to 8; mean maximum proposed protocol exposure
rises from 33.125% to 61.25%. Total **proposed** costs fall from 596 to 114 USDC.
Candidate proposals are blocked: those amounts are not actual paid costs or
executed positions. The report separates improvements, configured regressions
and changes outside configured gates. [Metric definitions](REGRESSION_TESTING.md).
