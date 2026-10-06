from tracefi import TraceFi
from tracefi.analysis import check_policy
from tracefi.models import decision_state
from tracefi.models.deterministic import DeterministicAgent

if __name__ == "__main__":
    with TraceFi() as trace:
        with trace.decision(agent="rule-agent", version="1", portfolio={"USDC": 100000},
                            agent_config={"version": "1"}, policy_config={"max_exposure": 0.35}) as t:
            t.capture_context({"apy": 0.067, "liquidity": 21000000, "price": 1, "oracle_age_seconds": 20})
            decision = DeterministicAgent().decide(decision_state(t.record))
            t.capture_decision(decision)
            policy = check_policy(decision, t.record["portfolio"], t.record["policy_configuration"])
            t.capture_policy(policy)
            t.capture_simulation({"success": True, "mode": "synthetic"})
            t.capture_execution({"status": "success" if policy["approved"] else "blocked", "mode": "synthetic"})
        print(t.trace_id)
