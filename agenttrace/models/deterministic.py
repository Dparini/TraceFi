import math


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class DeterministicAgent:
    """Synthetic example; never submits transactions or handles real funds."""
    def __init__(self, version=None):
        self.version = version

    def decide(self, state):
        context = state.get("context", {})
        config = state.get("agent_configuration", {})
        version = self.version or str(config.get("version", "1"))
        apy = context.get("apy")
        liquidity = context.get("liquidity")
        price = context.get("price")
        oracle_age = context.get("oracle_age_seconds")
        portfolio = state.get("portfolio", {}).get("USDC", 0)
        hold = {"action": "HOLD", "asset": "USDC", "amount": 0,
                "rationale": {"factors": ["Inputs do not meet configured supply thresholds"]}}
        if not all(finite_number(item) for item in (apy, liquidity, price, oracle_age, portfolio)):
            return hold
        threshold = config.get("min_liquidity", 12_400_000)
        min_apy = config.get("min_apy", 0.05)
        allocation = config.get("allocation", 0.25 if version == "1" else 0.8)
        tier = config.get("liquidity_allocation_threshold")
        if finite_number(tier) and finite_number(liquidity) and liquidity < tier:
            allocation = config.get("allocation_low", 0.25)
        if not all(finite_number(item) for item in (threshold, min_apy, allocation)):
            return hold
        if not (0 <= apy <= 1 and liquidity >= threshold and apy >= min_apy
                and 0.98 <= price <= 1.02 and 0 <= oracle_age <= 300 and portfolio > 0
                and 0 <= allocation <= 1):
            return hold
        return {"action": "SUPPLY", "protocol": context.get("protocol", "protocol_a"),
                "asset": "USDC", "amount": round(portfolio * allocation, 2),
                "rationale": {"factors": ["Yield meets threshold", "Sufficient reported liquidity"]}}
