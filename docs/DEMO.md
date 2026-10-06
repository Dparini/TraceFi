# A 60–90 second demo

Everything here is synthetic, offline and uses no funds.

1. **0–20 seconds:** `tracefi demo`. Show the $100,000 portfolio, the $25,000
   approved supply and the $80,000 rejected supply. Explain the 35% exposure
   limit. Copy the two printed IDs.
2. **20–40 seconds:** `tracefi analyze latest`. Show the omitted available
   liquidity trend and the policy rejection. Distinguish a likely retrieval
   issue from a policy failure: the policy correctly blocked the second action.
3. **40–60 seconds:** `tracefi why-change FIRST_ID SECOND_ID --adapter
   deterministic`. Liquidity alone changes the proposal amount, with the same
   agent configuration. No counterfactual transaction is sent.
4. **60–90 seconds:** `tracefi serve`. Open `http://127.0.0.1:8765`, click the
   rejected trace and inspect policy evidence and the timeline. Export HTML.

The generated standalone HTML is suitable for sharing after checking the
captured non-secret portfolio and evidence. The repository does not yet contain
a recorded video or an animated GIF; do not present a placeholder as a recording.
