from typing import Any

from tracefi import TraceFi
from tracefi.analysis import check_policy
from tracefi.models import ModelAdapter, decision_state, load_adapter


def make_trace(
    context: dict[str, Any] | None = None,
    adapter: ModelAdapter | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    adapter = adapter or load_adapter("deterministic")
    market = {"apy": 0.067, "liquidity": 21_000_000, "price": 1, "oracle_age_seconds": 20}
    if context is not None:
        market.update(context)
    with TraceFi(db=":memory:") as collector:
        with collector.decision(
            "rule-agent",
            "1",
            portfolio={"USDC": 100_000},
            agent_config=config or {"version": "1"},
            policy_config={"max_exposure": 0.35},
        ) as trace:
            trace.capture_context(market)
            proposal = adapter.decide(decision_state(trace.record))
            trace.capture_decision(proposal)
            trace.capture_policy(
                check_policy(
                    proposal, trace.record["portfolio"], trace.record["policy_configuration"]
                )
            )
            trace.capture_simulation({"success": True})
            trace.capture_execution({"status": "success"})
        return collector.storage.get(trace.trace_id)
