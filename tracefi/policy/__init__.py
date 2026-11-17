"""Deterministic risk policy for single financial proposals."""

import math
from collections.abc import Mapping
from decimal import Decimal, localcontext
from typing import Any

from tracefi.hashing import finite_number

ACTIONS = ("HOLD", "SUPPLY", "WITHDRAW")


def valid_proposal(proposal: Any) -> bool:
    if not isinstance(proposal, Mapping):
        return False
    action, amount, asset = proposal.get("action"), proposal.get("amount"), proposal.get("asset")
    return (
        action in ACTIONS
        and isinstance(asset, str)
        and bool(asset)
        and finite_number(amount)
        and amount >= 0
        and (action != "HOLD" or amount == 0)
    )


def _exceeds_limit(amount: Any, existing: Any, limit: Any, denominator: Any) -> bool:
    with localcontext() as arithmetic:
        arithmetic.prec = 1024
        return Decimal(str(existing)) + Decimal(str(amount)) > Decimal(str(limit)) * Decimal(
            str(denominator)
        )


def _portfolio_value_fits(positions: dict[str, Any], balance: Any, total: Any) -> bool:
    with localcontext() as arithmetic:
        arithmetic.prec = 1024
        return sum((Decimal(str(value)) for value in positions.values()), Decimal(0)) + Decimal(
            str(balance)
        ) <= Decimal(str(total))


def check_policy(proposal: Any, portfolio: Any, config: Any) -> dict[str, Any]:
    reasons: list[str] = []
    valid = valid_proposal(proposal)
    if not valid:
        reasons.append("INVALID_PROPOSAL")
    proposal = proposal if isinstance(proposal, Mapping) else {}
    portfolio_ok, config_ok = isinstance(portfolio, Mapping), isinstance(config, Mapping)
    portfolio = portfolio if portfolio_ok else {}
    config = config if config_ok else {}
    asset = proposal.get("asset", "USDC")
    balance = portfolio.get(asset, 0) if isinstance(asset, str) else None
    limit = config.get("max_exposure", 0.35)
    inputs_valid = (
        portfolio_ok
        and config_ok
        and finite_number(balance)
        and balance >= 0
        and finite_number(limit)
        and 0 <= limit <= 1
    )
    if not inputs_valid:
        reasons.append("INVALID_POLICY_INPUT")
    amount = proposal.get("amount")
    exposure = None
    basis = config.get("exposure_basis", "asset_balance")
    if basis not in ("asset_balance", "total_portfolio"):
        reasons.append("INVALID_POLICY_INPUT")
        inputs_valid = False
    denominator, existing = balance, 0
    if basis == "total_portfolio":
        denominator = portfolio.get("total_value_usdc")
        positions = portfolio.get("positions")
        positions_ok = isinstance(positions, dict) and all(
            isinstance(key, str) and finite_number(value) and value >= 0
            for key, value in positions.items()
        )
        protocol = proposal.get("protocol")
        positions_total = sum(positions.values()) if positions_ok else None
        inputs_valid = bool(
            inputs_valid
            and asset == "USDC"
            and finite_number(denominator)
            and denominator > 0
            and positions_ok
            and finite_number(positions_total)
            and finite_number(balance)
            and _portfolio_value_fits(positions, balance, denominator)
            and (
                proposal.get("action") == "HOLD"
                or isinstance(protocol, str)
                and protocol in positions
            )
        )
        if not inputs_valid and "INVALID_POLICY_INPUT" not in reasons:
            reasons.append("INVALID_POLICY_INPUT")
        if positions_ok and isinstance(protocol, str):
            existing = positions.get(protocol, 0)
    if (
        valid
        and inputs_valid
        and finite_number(denominator)
        and denominator > 0
        and finite_number(amount)
    ):
        proposed = (
            existing + amount if proposal["action"] == "SUPPLY" else max(0, existing - amount)
        )
        ratio = proposed / denominator if basis == "total_portfolio" else amount / denominator
        numerator = proposed if basis == "total_portfolio" else amount
        if math.isfinite(ratio) and (ratio != 0 or numerator == 0):
            exposure = ratio
    if valid and proposal["action"] == "SUPPLY":
        exceeds = (
            inputs_valid
            and finite_number(denominator)
            and _exceeds_limit(amount, existing, limit, denominator)
        )
        if not inputs_valid or exposure is None or exceeds:
            reasons.append("MAX_EXPOSURE")
        if inputs_valid and _exceeds_limit(amount, 0, 1, balance):
            reasons.append("INSUFFICIENT_BALANCE")
    if (
        valid
        and proposal["action"] == "WITHDRAW"
        and basis == "total_portfolio"
        and inputs_valid
        and _exceeds_limit(amount, 0, 1, existing)
    ):
        reasons.append("INSUFFICIENT_POSITION")
    return {
        "approved": not reasons,
        "should_reject": bool(reasons),
        "reasons": reasons,
        "requested_exposure": exposure,
        "maximum_exposure": limit if finite_number(limit) else None,
    }
