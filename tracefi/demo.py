"""Repeatable synthetic captures: no external service or transaction."""

from typing import Any

from tracefi.case_study import DATASET as LENDING_DATASET
from tracefi.case_study import LendingAgent, simulate
from tracefi.counterfactual import counterfactual, why_change
from tracefi.hashing import load_json
from tracefi.models import ModelAdapter
from tracefi.models.deterministic import DeterministicAgent
from tracefi.policy import check_policy
from tracefi.schema import changed_paths
from tracefi.sdk import TraceFi


def run_demo(collector: TraceFi) -> dict[str, Any]:
    """Capture two decisions that differ only in liquidity, then explain the change."""
    ids = []
    for liquidity in (15_000_000, 21_000_000):
        with collector.decision(
            agent="yield-agent",
            version="2",
            portfolio={"USDC": 100_000},
            agent_config={
                "version": "2",
                "liquidity_allocation_threshold": 20_000_000,
                "allocation_low": 0.25,
            },
            policy_config={"max_exposure": 0.35},
        ) as t:
            t.capture_context(
                {
                    "apy": 0.067,
                    "liquidity": liquidity,
                    "price": 1,
                    "oracle_age_seconds": 20,
                    "protocol": "protocol_b",
                }
            )
            t.capture_retrieval(
                {
                    "available_features": ["apy", "liquidity", "liquidity_trend_24h"],
                    "included_features": ["apy", "liquidity"],
                    "required_features": ["liquidity_trend_24h"],
                    "evidence": [{"source": "synthetic-snapshot", "liquidity_trend_24h": -0.41}],
                }
            )
            with t.span("rule-agent", "reasoning") as span:
                proposal = DeterministicAgent().decide(t.state())
                span.log({"adapter": "deterministic", "rationale": proposal["rationale"]})
            t.capture_decision(proposal)
            state = t.state()
            policy = check_policy(proposal, state["portfolio"], state["policy_configuration"])
            t.capture_policy(policy)
            if policy["approved"]:
                t.capture_simulation({"success": True, "mode": "synthetic"})
                t.capture_execution({"status": "success", "mode": "synthetic"})
            else:
                t.capture_execution(
                    {
                        "status": "blocked",
                        "reason": ", ".join(policy["reasons"]),
                        "mode": "synthetic",
                    }
                )
            ids.append(t.trace_id)
    first, second = (collector.storage.get(trace_id) for trace_id in ids)
    return {"trace_ids": ids, "why_change": why_change(first, second, DeterministicAgent())}


def run_case_study(collector: TraceFi) -> dict[str, Any]:
    """Capture the omitted-trend lending decision, then restore the omitted signal."""
    scenario = load_json((LENDING_DATASET / "omitted-trend.json").read_bytes())
    state, snapshot_data = scenario["state"], scenario["market_snapshot"]
    (omitted,) = (
        change
        for change in changed_paths({"markets": snapshot_data}, state["context"])
        if not change["after_present"]
    )
    adapter = LendingAgent("1")
    with collector.decision(
        "lending-agent",
        "1",
        portfolio=state["portfolio"],
        agent_config=state["agent_configuration"],
        policy_config=state["policy_configuration"],
    ) as trace:
        with trace.span("market-snapshot", "data") as span:
            span.log({"synthetic": True, "markets": snapshot_data})
        trace.capture_context(state["context"])
        trace.capture_retrieval(
            {
                "market_snapshot": snapshot_data,
                "available_features": [omitted["path"]],
                "required_features": [omitted["path"]],
                "included_features": [],
                "omission": scenario["omission"],
            }
        )
        proposal = adapter.decide(trace.state())
        trace.capture_decision(proposal)
        policy = check_policy(proposal, state["portfolio"], state["policy_configuration"])
        trace.capture_policy(policy)
        if policy["approved"]:
            simulation = simulate(proposal, state)
            trace.capture_simulation(simulation)
            trace.capture_execution(
                {
                    "status": "success" if simulation["success"] else "blocked",
                    "mode": "synthetic",
                    "actual_effect": simulation["predicted_effect"],
                }
            )
            if simulation["success"]:
                trace.capture_outcome(scenario["outcome"])
        else:
            trace.capture_execution({"status": "blocked", "mode": "synthetic"})
    record = collector.storage.get(trace.trace_id)
    experiment = counterfactual(record, adapter, "context." + omitted["path"], omitted["before"])
    return {"trace_id": trace.trace_id, "counterfactual": experiment}


def run_scenarios(
    collector: TraceFi, adapter: ModelAdapter, version: str, scenarios: list[dict[str, Any]]
) -> list[str]:
    """Capture a complete synthetic lifecycle, with explicit injected test faults."""
    ids = []
    for scenario in scenarios:
        state = scenario["state"]
        with collector.decision(
            "scenario-agent",
            version,
            portfolio=state.get("portfolio", {}),
            agent_config=state.get("agent_configuration", {}),
            policy_config=state.get("policy_configuration", {}),
        ) as t:
            t.capture_context(state.get("context", {}))
            t.capture_retrieval(
                scenario.get("retrieval", {"scenario": scenario["id"], "synthetic": True})
            )
            recorded = t.state()
            with t.span("scenario-decision", "reasoning") as span:
                proposal = (
                    scenario["proposal_override"]
                    if "proposal_override" in scenario
                    else adapter.decide(t.state())
                )
                span.log(
                    {"scenario": scenario["id"], "fault_injection": "proposal_override" in scenario}
                )
            t.capture_decision(proposal)
            policy = (
                scenario["policy_override"]
                if "policy_override" in scenario
                else check_policy(proposal, recorded["portfolio"], recorded["policy_configuration"])
            )
            t.capture_policy(policy)
            if policy.get("approved"):
                t.capture_simulation(
                    scenario.get("simulation", {"success": True, "mode": "synthetic"})
                )
                t.capture_execution(
                    scenario.get("execution", {"status": "success", "mode": "synthetic"})
                )
            else:
                t.capture_execution({"status": "blocked", "mode": "synthetic"})
            if "outcome" in scenario:
                t.capture_outcome(scenario["outcome"])
        ids.append(t.trace_id)
    return ids
