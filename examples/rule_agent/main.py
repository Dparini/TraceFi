from tracefi import TraceFi
from tracefi.models.deterministic import DeterministicAgent
from tracefi.policy import check_policy

if __name__ == "__main__":
    with TraceFi() as trace:
        with trace.decision(
            agent="rule-agent",
            version="1",
            portfolio={"USDC": 100000},
            agent_config={"version": "1"},
            policy_config={"max_exposure": 0.35},
        ) as t:
            t.capture_context(
                {"apy": 0.067, "liquidity": 21000000, "price": 1, "oracle_age_seconds": 20}
            )
            decision = DeterministicAgent().decide(t.state())
            t.capture_decision(decision)
            state = t.state()
            policy = check_policy(decision, state["portfolio"], state["policy_configuration"])
            t.capture_policy(policy)
            if policy["approved"]:
                t.capture_simulation({"success": True, "mode": "synthetic"})
                t.capture_execution({"status": "success", "mode": "synthetic"})
            else:
                t.capture_execution({"status": "blocked", "mode": "synthetic"})
        print(t.trace_id)
