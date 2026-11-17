"""Synthetic lending investigation. No RPC, historical feeds or financial executor."""

import math
from copy import deepcopy
from pathlib import Path
from typing import Any

from tracefi.hashing import finite_number
from tracefi.policy import valid_proposal

DATASET = Path(__file__).parent / "scenarios"
MARKET_INPUTS = ("supply_apy", "liquidity_usdc", "oracle_age_seconds", "transaction_cost_usdc")
TREND = "liquidity_trend_24h"


class LendingAgent:
    """Two explicitly synthetic strategies; APYs are observations, not forecasts."""

    def __init__(self, version: str = "1") -> None:
        if version not in ("1", "2"):
            raise ValueError("Unsupported lending agent version")
        self.version = version

    def inputs(self, state: dict[str, Any]) -> dict[str, bool]:
        markets = state.get("context", {}).get("markets")
        if not isinstance(markets, dict):
            return {}
        return {
            f"context.markets.{protocol}.{field}": field == TREND
            for protocol in markets
            for field in (*MARKET_INPUTS, TREND)
        }

    def decide(self, state: dict[str, Any]) -> dict[str, Any]:
        context = state["context"]
        candidates = []
        for protocol, market in context["markets"].items():
            values = [market.get(key) for key in MARKET_INPUTS]
            if not all(finite_number(value) for value in values):
                continue
            apy, liquidity, age, cost = values
            if not (0 <= apy <= 1 and liquidity >= 10_000_000 and 0 <= age <= 300 and cost >= 0):
                continue
            trend = market.get(TREND)
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
                if TREND not in context["markets"][protocol]
                else [],
            },
        }


class LendingMetrics:
    """Metrics derived independently from recorded inputs, not model self-report."""

    directions = {
        "average_maximum_protocol_exposure": -1,
        "declining_liquidity_proposals": -1,
        "missing_trend_proposals": -1,
        "proposed_transaction_cost_usdc": -1,
    }

    def assess(self, proposal: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
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
            selected_trend = markets[protocol].get(TREND)
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

    def summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(rows)
        return {
            "financial_metrics_scenarios": count,
            "average_maximum_protocol_exposure": math.fsum(
                row["maximum_protocol_exposure"] / count for row in rows
            )
            if rows
            else None,
            "proposed_transaction_cost_usdc": math.fsum(
                row["proposed_transaction_cost_usdc"] for row in rows
            )
            if rows
            else None,
            "declining_liquidity_proposals": sum(
                row["declining_liquidity_proposals"] for row in rows
            )
            if rows
            else None,
            "missing_trend_proposals": sum(row["missing_trend_proposals"] for row in rows)
            if rows
            else None,
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
