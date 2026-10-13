"""Offline scenario runner and comparable regression metrics."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tracefi.sdk import TraceFi
import math
from pathlib import Path

from tracefi.analysis import check_policy, valid_proposal
from tracefi.hashing import MAX_BYTES, load_json, snapshot, state_hash
from tracefi.models import ModelAdapter, observed_decision
from tracefi.models.deterministic import finite_number

MAX_SCENARIOS = 1000
MAX_DATASET_BYTES = 64 * 1024 * 1024


def load_scenarios(directory: str | Path) -> list[dict[str, Any]]:
    paths = []
    for path in Path(directory).rglob("*.json"):
        paths.append(path)
        if len(paths) > MAX_SCENARIOS:
            raise ValueError("Dataset exceeds scenario count limit")
    paths.sort()
    if not paths:
        raise ValueError(f"No JSON scenarios in {directory}")
    result = []
    total_bytes = 0
    for path in paths:
        size = path.stat().st_size
        total_bytes += size
        if total_bytes > MAX_DATASET_BYTES:
            raise ValueError("Dataset exceeds total byte limit")
        if size > MAX_BYTES:
            raise ValueError("Scenario exceeds the byte limit")
        if path.is_symlink():
            raise ValueError("Scenario symlinks are unsupported")
        with path.open("rb") as stream:
            scenario = load_json(stream.read(MAX_BYTES + 1))
        if not isinstance(scenario, dict) or not isinstance(scenario.get("state"), dict):
            raise ValueError(f"Scenario needs an object state: {path}")
        scenario.setdefault("id", str(path.relative_to(directory)))
        result.append(scenario)
    ids = [scenario["id"] for scenario in result]
    if not all(isinstance(item, str) and item for item in ids) or len(set(ids)) != len(ids):
        raise ValueError("Scenario IDs must be unique nonempty strings")
    return result


def _evaluate_scenario(adapter: ModelAdapter, scenario: dict[str, Any]) -> dict[str, Any]:
    state = snapshot(scenario["state"])
    proposal = observed_decision(adapter, snapshot(state))
    repeated = observed_decision(adapter, snapshot(state))
    policy = check_policy(
        proposal, state.get("portfolio", {}), state.get("policy_configuration", {})
    )
    row = {
        "scenario": scenario["id"],
        "decision": proposal,
        "valid": valid_proposal(proposal),
        "consistent": state_hash(proposal) == state_hash(repeated),
        "unsafe_proposal": not policy["approved"],
        "policy_violation": False,
        "exposure": policy.get("requested_exposure"),
        "matches_expected": state_hash(proposal) == state_hash(scenario["expected_decision"])
        if "expected_decision" in scenario
        else None,
    }
    if "metrics_model" in scenario:
        if scenario["metrics_model"] != "synthetic-lending-v1":
            raise ValueError("Unknown metrics model")
        from tracefi.case_study import assess

        row["financial_metrics"] = assess(proposal, state)
    return row


def evaluate(adapter: ModelAdapter, scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for scenario in scenarios:
        try:
            rows.append(_evaluate_scenario(adapter, scenario))
        except Exception as exc:
            rows.append(
                {
                    "scenario": scenario["id"],
                    "valid": False,
                    "consistent": False,
                    "error_type": type(exc).__name__,
                    "unsafe_proposal": False,
                    "policy_violation": False,
                    "exposure": None,
                }
            )
    exposures = [row["exposure"] for row in rows if finite_number(row.get("exposure"))]
    financial = [row["financial_metrics"] for row in rows if "financial_metrics" in row]
    financial_metrics = {
        "financial_metrics_scenarios": len(financial),
        "average_maximum_protocol_exposure": math.fsum(
            row["maximum_protocol_exposure"] / len(financial) for row in financial
        )
        if financial
        else None,
        "proposed_transaction_cost_usdc": math.fsum(
            row["proposed_transaction_cost_usdc"] for row in financial
        )
        if financial
        else None,
        "declining_liquidity_proposals": sum(
            row["declining_liquidity_proposals"] for row in financial
        )
        if financial
        else None,
        "missing_trend_proposals": sum(row["missing_trend_proposals"] for row in financial)
        if financial
        else None,
    }
    return {
        "metrics": {
            "scenarios": len(rows),
            **financial_metrics,
            "consistent_decisions": sum(row["consistent"] for row in rows),
            "failed_scenarios": sum("error_type" in row for row in rows),
            "policy_rejections": sum(row["unsafe_proposal"] for row in rows),
            "valid_decisions": sum(row["valid"] for row in rows),
            "unsafe_proposals": sum(row["unsafe_proposal"] for row in rows),
            "policy_violations": sum(row["policy_violation"] for row in rows),
            "average_proposed_exposure": math.fsum(value / len(exposures) for value in exposures)
            if exposures
            else None,
        },
        "results": rows,
        "limitations": "Exposure measures proposed allocation, not a calibrated risk score. Returns and drawdown are unavailable without a validated outcome model.",
    }


REGRESSION_DIRECTIONS = {
    "valid_decisions": 1,
    "consistent_decisions": 1,
    "failed_scenarios": -1,
    "unsafe_proposals": -1,
    "policy_rejections": -1,
    "average_proposed_exposure": -1,
    "average_maximum_protocol_exposure": -1,
    "declining_liquidity_proposals": -1,
    "missing_trend_proposals": -1,
    "proposed_transaction_cost_usdc": -1,
}
DEFAULT_REGRESSIONS = [
    "valid_decisions",
    "unsafe_proposals",
    "average_proposed_exposure",
    "consistent_decisions",
    "failed_scenarios",
]


def compare(
    baseline: ModelAdapter,
    candidate: ModelAdapter,
    scenarios: list[dict[str, Any]],
    regression_metrics: list[str] | None = None,
) -> dict[str, Any]:
    tracked = DEFAULT_REGRESSIONS if regression_metrics is None else regression_metrics
    if any(metric not in REGRESSION_DIRECTIONS for metric in tracked):
        raise ValueError("Unsupported regression metric")
    a, b = evaluate(baseline, scenarios), evaluate(candidate, scenarios)
    regressions, improvements, trade_offs = [], [], []
    for metric, direction in REGRESSION_DIRECTIONS.items():
        old, new = a["metrics"][metric], b["metrics"][metric]
        if old is None or new is None or old == new:
            continue
        change = {"metric": metric, "baseline": old, "candidate": new}
        if (new - old) * direction > 0:
            improvements.append(change)
        elif metric in tracked:
            regressions.append(change)
        else:
            trade_offs.append(change)
    return {
        "baseline": a,
        "candidate": b,
        "regressions": regressions,
        "improvements": improvements,
        "trade_offs": trade_offs,
        "tracked_metrics": list(tracked),
        "limitations": "Metric direction is an explicit comparison convention, not financial optimality. Lower costs can mean less participation; policy rejections may demonstrate a working control. Costs/exposure describe proposals, including blocked ones. No returns or drawdown are inferred.",
    }


def run_scenarios(
    collector: TraceFi, adapter: ModelAdapter, scenarios: list[dict[str, Any]]
) -> list[str]:
    """Capture a complete synthetic lifecycle, with explicit injected test faults."""
    from tracefi.models import decision_state

    ids = []
    for scenario in scenarios:
        state = scenario["state"]
        with collector.decision(
            "scenario-agent",
            str(state.get("agent_configuration", {}).get("version", "1")),
            portfolio=state.get("portfolio", {}),
            agent_config=state.get("agent_configuration", {}),
            policy_config=state.get("policy_configuration", {}),
        ) as t:
            t.capture_context(state.get("context", {}))
            t.capture_retrieval(
                scenario.get("retrieval", {"scenario": scenario["id"], "synthetic": True})
            )
            with t.span("scenario-decision", "reasoning") as span:
                proposal = (
                    scenario["proposal_override"]
                    if "proposal_override" in scenario
                    else adapter.decide(decision_state(t.record))
                )
                span.log(
                    {"scenario": scenario["id"], "fault_injection": "proposal_override" in scenario}
                )
            t.capture_decision(proposal)
            policy = (
                scenario["policy_override"]
                if "policy_override" in scenario
                else check_policy(proposal, t.record["portfolio"], t.record["policy_configuration"])
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
