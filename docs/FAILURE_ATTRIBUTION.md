# Failure attribution

```bash
tracefi analyze TRACE_ID
tracefi analyze TRACE_ID --json
```

The engine uses deterministic rules against documented structured evidence,
not an LLM or hidden chain-of-thought. It retains every finding and shows a
priority-ordered likely class for navigation. Priority is not a causal ranking.

- `DATA_FAILURE`: invalid/stale oracle age, invalid recorded price or reported
  source conflict. A producer's conflict flag is a likely interpretation.
- `RETRIEVAL_FAILURE`: required features existed in the recorded available
  evidence but were not included in the agent context; interpretation is likely.
- `REASONING_FAILURE`: a malformed/inconsistent structured proposal, not inferred
  internal model reasoning or a general test of financial rationality.
- `POLICY_FAILURE`: success despite a recorded rejection requirement, or recorded
  approval inconsistent with the configured deterministic policy.
- `SIMULATION_FAILURE`: explicit unsuccessful simulation or effects outside the
  recorded numeric tolerance. A simulation rejection is an observed result; it
  does not alone establish a simulator bug.
- `EXECUTION_FAILURE`: explicit failed/reverted execution, separately retained
  even when simulation passed. Simulation failure does not imply execution failure.
- `MARKET_OUTCOME`: negative PnL, valid recorded proposal/state, positive policy,
  simulation and execution evidence, no invalid observations and no detected failure.
  This likely interpretation does not rule out unseen failures.
- `ADVERSARIAL_INPUT`: explicitly marked suspicious untrusted input, with source
  evidence; influence on the agent is unproven. This is not a universal injection detector.

Findings distinguish **observed conditions** and **likely interpretations**.
`coverage` distinguishes recorded, empty, absent and invalid sections.
`input_errors` surfaces malformed evidence and prevents a market-outcome fallback.
A missing stage remains unknown; a completed trace status does not mean every
stage was recorded or every financial control passed.

Exact detector fields are in [API.md](API.md#detector-fields). Generic data rules
inspect the documented top-level context fields; arbitrary nested market schemas
need explicit instrumentation/adapter validation. The lending case adapter checks
its nested freshness/eligibility inputs, while retrieval omission uses standard
feature-list evidence. Instrumentation may be incomplete or incorrect.

[Case study](FINANCIAL_CASE_STUDY.md) shows an omitted trend and conditional
sensitivity without treating subsequent loss as proof of error. Rules can miss
failures, identify irrelevant inconsistencies or produce false attribution;
review the evidence rather than consuming the likely class as a verdict.
