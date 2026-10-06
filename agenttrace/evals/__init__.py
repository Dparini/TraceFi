"""Offline scenario runner and comparable regression metrics."""
import json
from pathlib import Path
from agenttrace.analysis import check_policy
from agenttrace.hashing import snapshot, state_hash
from agenttrace.models.deterministic import finite_number
from agenttrace.models import observed_decision


def load_scenarios(directory):
    paths = sorted(Path(directory).rglob("*.json"))
    if not paths:
        raise ValueError(f"No JSON scenarios in {directory}")
    result = []
    for path in paths:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(scenario, dict) or not isinstance(scenario.get("state"), dict):
            raise ValueError(f"Scenario needs an object state: {path}")
        scenario.setdefault("id", str(path.relative_to(directory)))
        result.append(scenario)
    return result


def evaluate(adapter, scenarios):
    rows = []
    for scenario in scenarios:
        state = snapshot(scenario["state"])
        try:
            proposal = observed_decision(adapter, state)
            if not isinstance(proposal, dict):
                raise ValueError("Decision must be an object")
            valid = (proposal.get("action") in ("HOLD", "SUPPLY", "WITHDRAW")
                     and finite_number(proposal.get("amount")) and proposal["amount"] >= 0)
            policy = check_policy(proposal, state.get("portfolio", {}), state.get("policy_configuration", {}))
            # All execution is simulated; unsafe proposals are blocked, not violations.
            unsafe = not policy["approved"]
            rows.append({"scenario": scenario["id"], "decision": proposal, "valid": valid,
                         "unsafe_proposal": unsafe, "policy_violation": False,
                         "exposure": policy.get("requested_exposure"),
                         "matches_expected": state_hash(proposal) == state_hash(scenario["expected_decision"])
                         if "expected_decision" in scenario else None})
        except Exception as exc:
            rows.append({"scenario": scenario["id"], "valid": False, "error_type": type(exc).__name__,
                         "unsafe_proposal": False, "policy_violation": False, "exposure": None})
    exposures = [row["exposure"] for row in rows if finite_number(row.get("exposure"))]
    return {"metrics": {"scenarios": len(rows), "valid_decisions": sum(row["valid"] for row in rows),
                        "unsafe_proposals": sum(row["unsafe_proposal"] for row in rows),
                        "policy_violations": sum(row["policy_violation"] for row in rows),
                        "average_proposed_exposure": sum(exposures) / len(exposures) if exposures else None},
            "results": rows,
            "limitations": "Exposure measures proposed allocation, not a calibrated risk score. Returns and drawdown are unavailable without a validated outcome model."}


def compare(baseline, candidate, scenarios):
    a, b = evaluate(baseline, scenarios), evaluate(candidate, scenarios)
    regressions = []
    for metric in ("valid_decisions", "unsafe_proposals", "average_proposed_exposure"):
        old, new = a["metrics"][metric], b["metrics"][metric]
        if old is not None and new is not None and (new < old if metric == "valid_decisions" else new > old):
            regressions.append({"metric": metric, "baseline": old, "candidate": new})
    return {"baseline": a, "candidate": b, "regressions": regressions,
            "limitations": "A regression report does not decide which agent is financially better."}


def run_scenarios(collector, adapter, scenarios):
    """Capture a complete synthetic lifecycle, with explicit injected test faults."""
    from agenttrace.models import decision_state
    ids = []
    for scenario in scenarios:
        state = scenario["state"]
        with collector.decision("scenario-agent", str(state.get("agent_configuration", {}).get("version", "1")),
                                portfolio=state.get("portfolio", {}), agent_config=state.get("agent_configuration", {}),
                                policy_config=state.get("policy_configuration", {})) as t:
            t.capture_context(state.get("context", {}))
            t.capture_retrieval(scenario.get("retrieval", {"scenario": scenario["id"], "synthetic": True}))
            with t.span("scenario-decision", "reasoning") as span:
                proposal = scenario.get("proposal_override") or adapter.decide(decision_state(t.record))
                span.log({"scenario": scenario["id"], "fault_injection": "proposal_override" in scenario})
            t.capture_decision(proposal)
            policy = scenario.get("policy_override") or check_policy(proposal, t.record["portfolio"], t.record["policy_configuration"])
            t.capture_policy(policy)
            if policy.get("approved"):
                t.capture_simulation(scenario.get("simulation", {"success": True, "mode": "synthetic"}))
                t.capture_execution(scenario.get("execution", {"status": "success", "mode": "synthetic"}))
            else:
                t.capture_execution({"status": "blocked", "mode": "synthetic"})
            if "outcome" in scenario:
                t.capture_outcome(scenario["outcome"])
        ids.append(t.trace_id)
    return ids
