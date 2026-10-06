"""Repeatable synthetic capture: no external service or transaction."""
from tracefi.models.deterministic import DeterministicAgent
from tracefi.models import decision_state
from tracefi.analysis import check_policy


def run_demo(collector):
    ids = []
    for liquidity in (15_000_000, 21_000_000):
        with collector.decision(agent="yield-agent", version="2", portfolio={"USDC": 100_000},
                                agent_config={"version": "2", "liquidity_allocation_threshold": 20_000_000, "allocation_low": 0.25}, policy_config={"max_exposure": 0.35}) as t:
            t.capture_context({"apy": 0.067, "liquidity": liquidity, "price": 1,
                               "oracle_age_seconds": 20, "protocol": "protocol_b"})
            t.capture_retrieval({"available_features": ["apy", "liquidity", "liquidity_trend_24h"],
                                "included_features": ["apy", "liquidity"],
                                "required_features": ["liquidity_trend_24h"],
                                "evidence": [{"source": "synthetic-snapshot", "liquidity_trend_24h": -0.41}]})
            with t.span("rule-agent", "reasoning") as span:
                proposal = DeterministicAgent().decide(decision_state(t.record))
                span.log({"adapter": "deterministic", "rationale": proposal["rationale"]})
            t.capture_decision(proposal)
            policy = check_policy(proposal, t.record["portfolio"], t.record["policy_configuration"])
            t.capture_policy(policy)
            if policy["approved"]:
                t.capture_simulation({"success": True, "mode": "synthetic"})
                t.capture_execution({"status": "success", "mode": "synthetic"})
            else:
                t.capture_execution({"status": "blocked", "reason": "MAX_EXPOSURE", "mode": "synthetic"})
            ids.append(t.trace_id)
    return ids
