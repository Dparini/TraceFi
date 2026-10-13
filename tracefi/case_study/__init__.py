"""Synthetic lending investigation. No RPC, historical feeds or financial executor."""

from copy import deepcopy
from pathlib import Path
from typing import Any

from tracefi.analysis import check_policy, valid_proposal
from tracefi.counterfactual import counterfactual
from tracefi.models import decision_state
from tracefi.models.deterministic import finite_number
from tracefi.sdk import TraceFi

DATASET = Path(__file__).parent / "scenarios"


class LendingAgent:
    """Two explicitly synthetic strategies; APYs are observations, not forecasts."""

    def __init__(self, version: str = "1") -> None:
        if version not in ("1", "2"):
            raise ValueError("Unsupported lending agent version")
        self.version = version

    def decide(self, state: dict[str, Any]) -> dict[str, Any]:
        context = state["context"]
        candidates = []
        for protocol, market in context["markets"].items():
            values = [
                market.get(key)
                for key in (
                    "supply_apy",
                    "liquidity_usdc",
                    "oracle_age_seconds",
                    "transaction_cost_usdc",
                )
            ]
            if not all(finite_number(value) for value in values):
                continue
            apy, liquidity, age, cost = values
            if not (0 <= apy <= 1 and liquidity >= 10_000_000 and 0 <= age <= 300 and cost >= 0):
                continue
            trend = market.get("liquidity_trend_24h")
            cutoff = -0.2 if self.version == "1" else -0.6
            if trend is not None and (not finite_number(trend) or trend < cutoff):
                continue
            amount = min(state["portfolio"]["USDC"], 25_000 if self.version == "1" else 50_000)
            if self.version == "1":
                remaining = (
                    state["policy_configuration"]["max_exposure"]
                    * state["portfolio"]["total_value_usdc"]
                    - state["portfolio"]["positions"][protocol]
                )
                amount = max(0, min(amount, round(remaining, 2)))
                if amount == 0:
                    continue
            # V2 considers the 7-day simple-interest budget; V1 ignores transaction costs.
            if self.version == "2" and cost >= amount * apy * 7 / 365:
                continue
            candidates.append((apy, protocol, amount))
        if not candidates:
            return {
                "action": "HOLD",
                "asset": "USDC",
                "amount": 0,
                "rationale": {"factors": ["No market satisfies the synthetic strategy thresholds"]},
            }
        _, protocol, amount = max(candidates)
        return {
            "action": "SUPPLY",
            "asset": "USDC",
            "amount": amount,
            "protocol": protocol,
            "rationale": {
                "factors": [
                    "Highest reported APY among eligible markets",
                    "Reported liquidity and oracle age meet thresholds",
                ],
                "unknowns": ["Missing liquidity trend"]
                if "liquidity_trend_24h" not in context["markets"][protocol]
                else [],
            },
        }


def assess(proposal: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Metrics derived independently from recorded inputs, not model self-report."""
    if not valid_proposal(proposal) or proposal["asset"] != "USDC":
        raise ValueError("Lending metrics require a valid USDC proposal")
    portfolio, markets = state["portfolio"], state["context"]["markets"]
    positions = deepcopy(portfolio["positions"])
    cost = 0
    selected_trend = None
    if proposal.get("action") == "SUPPLY":
        protocol = proposal["protocol"]
        positions[protocol] += proposal["amount"]
        cost = markets[protocol]["transaction_cost_usdc"]
        selected_trend = markets[protocol].get("liquidity_trend_24h")
    return {
        "maximum_protocol_exposure": max(positions.values(), default=0)
        / portfolio["total_value_usdc"],
        "proposed_transaction_cost_usdc": cost,
        "declining_liquidity_proposals": int(
            finite_number(selected_trend) and selected_trend < -0.2
        ),
        "missing_trend_proposals": int(
            proposal.get("action") == "SUPPLY" and selected_trend is None
        ),
    }


def simulate(proposal: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Static feasibility and accounting, without predicting future market losses."""
    if not valid_proposal(proposal) or proposal["asset"] != "USDC":
        raise ValueError("Lending simulation requires a valid USDC proposal")
    amount = proposal["amount"]
    market = state["context"]["markets"].get(proposal.get("protocol"), {})
    cost = market.get("transaction_cost_usdc", 0)
    return {
        "success": proposal["action"] == "HOLD"
        or amount + cost <= state["portfolio"]["USDC"]
        and amount <= market["liquidity_usdc"],
        "mode": "synthetic",
        "predicted_effect": -amount - cost,
        "effect_tolerance": 0,
        "transaction_cost_usdc": cost,
        "scope": "Immediate cash delta and available liquidity only; future losses are not predicted.",
    }


def run_case_study(collector: TraceFi) -> dict[str, Any]:
    from tracefi.evals import load_scenarios

    scenario = next(item for item in load_scenarios(DATASET) if item["id"] == "omitted-trend")
    state, snapshot_data = scenario["state"], scenario["market_snapshot"]
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
                "available_features": ["markets.protocol_b.liquidity_trend_24h"],
                "required_features": ["markets.protocol_b.liquidity_trend_24h"],
                "included_features": [],
                "omission": "Synthetic retrieval fixture drops Protocol B liquidity trend; agent has an explicit unknown.",
            }
        )
        proposal = adapter.decide(decision_state(trace.record))
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
                trace.capture_outcome(
                    {
                        "pnl": -1821,
                        "synthetic": True,
                        "horizon_days": 7,
                        "components_usdc": {
                            "interest": 32,
                            "liquidity_exit_haircut": -1835,
                            "transaction_cost": -18,
                        },
                        "liquidity_change": -0.41,
                        "assumption": "A predeclared stressed exit haircut, not a forecast or historical result.",
                    }
                )
        else:
            trace.capture_execution({"status": "blocked", "mode": "synthetic"})
    record = collector.storage.get(trace.trace_id)
    experiment = counterfactual(
        record, adapter, "context.markets.protocol_b.liquidity_trend_24h", -0.41
    )
    return {"trace_id": trace.trace_id, "counterfactual": experiment}
