import pytest
from hypothesis import given

from tests.helpers import JSON
from tracefi.hashing import snapshot
from tracefi.policy import check_policy, valid_proposal

TOTAL_PORTFOLIO = {"exposure_basis": "total_portfolio", "max_exposure": 0.35}


def test_proposal_validity_contract():
    assert valid_proposal({"action": "HOLD", "asset": "USDC", "amount": 0})
    assert valid_proposal({"action": "WITHDRAW", "asset": "USDC", "amount": 1})
    for proposal in (
        None,
        {},
        {"action": "HOLD", "asset": "USDC", "amount": 1},
        {"action": "SUPPLY", "asset": "", "amount": 0},
        {"action": "SUPPLY", "asset": "USDC", "amount": True},
        {"action": "SUPPLY", "asset": "USDC", "amount": -1},
    ):
        assert not valid_proposal(proposal)


def test_policy_fields_and_other_asset_balances():
    proposal = {"action": "SUPPLY", "asset": "DAI", "amount": 35}
    assert check_policy(proposal, {"USDC": 1, "DAI": 100}, {"max_exposure": 0.35}) == {
        "approved": True,
        "should_reject": False,
        "reasons": [],
        "requested_exposure": 0.35,
        "maximum_exposure": 0.35,
    }
    proposal["amount"] = 36
    policy = check_policy(proposal, {"DAI": 100}, {"max_exposure": 0.35})
    assert policy["should_reject"] is True and policy["reasons"] == ["MAX_EXPOSURE"]


def test_asset_balance_boundaries_invalid_assets_and_extreme_ratios():
    for asset in ([], {}, 123, None):
        assert not check_policy(
            {"action": "SUPPLY", "amount": 1, "asset": asset}, {"USDC": 100}, {}
        )["approved"]
    for amount, approved in ((35, True), (36, False)):
        result = check_policy(
            {"action": "SUPPLY", "amount": amount, "asset": "USDC"},
            {"USDC": 100},
            {"max_exposure": 0.35},
        )
        assert result["approved"] is approved
    huge = check_policy(
        {"action": "SUPPLY", "amount": 1e308, "asset": "USDC"}, {"USDC": 1e-308}, {}
    )
    assert not huge["approved"]
    assert huge["requested_exposure"] is None
    assert not check_policy({"action": "HOLD", "amount": 1, "asset": "USDC"}, {"USDC": 100}, {})[
        "approved"
    ]


def test_policy_does_not_round_tiny_positive_exposure_to_zero():
    result = check_policy(
        {"action": "SUPPLY", "asset": "USDC", "amount": 1e-300},
        {"USDC": 1e308},
        {"max_exposure": 0},
    )
    assert not result["approved"]
    assert result["requested_exposure"] is None


def test_policy_decimal_comparison_preserves_large_integer_thresholds():
    result = check_policy(
        {"action": "SUPPLY", "asset": "USDC", "amount": 35 * 10**98 + 1},
        {"USDC": 10**100},
        {"max_exposure": 0.35},
    )
    assert not result["approved"]


@pytest.mark.parametrize(
    "positions,nav,amount,approved",
    [
        ({"A": 10000}, 100000, 25000, True),
        ({"A": 10001}, 100000, 25000, False),
        ({"A": True}, 100000, 1, False),
        ({"A": 0}, 0, 0, False),
        ({"A": -1}, 100000, 1, False),
        ([], 100000, 1, False),
        ({"A": 90000}, 100000, 1, False),
    ],
)
def test_existing_exposure_policy(positions, nav, amount, approved):
    proposal = {"action": "SUPPLY", "asset": "USDC", "protocol": "A", "amount": amount}
    portfolio = {"USDC": 80000, "positions": positions, "total_value_usdc": nav}
    assert check_policy(proposal, portfolio, TOTAL_PORTFOLIO)["approved"] is approved


@pytest.mark.parametrize("amount,approved", [(5000, True), (5001, False)])
def test_withdrawal_position_bounds(amount, approved):
    proposal = {"action": "WITHDRAW", "asset": "USDC", "protocol": "A", "amount": amount}
    portfolio = {"USDC": 95000, "total_value_usdc": 100000, "positions": {"A": 5000}}
    assert check_policy(proposal, portfolio, TOTAL_PORTFOLIO)["approved"] is approved


def test_total_portfolio_unknown_protocols_hold_and_fractional_nav():
    config = {"exposure_basis": "total_portfolio", "max_exposure": 0.5}
    portfolio = {"USDC": 0.2, "total_value_usdc": 0.3, "positions": {"A": 0.1, "B": 0}}
    proposal = {"action": "SUPPLY", "asset": "USDC", "protocol": "B", "amount": 0.15}
    assert check_policy(proposal, portfolio, config)["approved"] is True
    proposal["protocol"] = "unknown"
    assert not check_policy(proposal, portfolio, config)["approved"]
    hold = {"action": "HOLD", "asset": "USDC", "amount": 0}
    assert check_policy(hold, portfolio, config)["approved"]
    proposal.update(protocol="B", asset="ETH")
    assert not check_policy(proposal, portfolio, config)["approved"]
    # Each target's exposure is below the limit, but the aggregate state is inconsistent.
    result = check_policy(
        {"action": "SUPPLY", "asset": "USDC", "protocol": "A", "amount": 1},
        {"USDC": 50000, "total_value_usdc": 100000, "positions": {"A": 20000, "B": 40000}},
        config,
    )
    assert not result["approved"] and "INVALID_POLICY_INPUT" in result["reasons"]


@given(JSON, JSON, JSON)
def test_policy_never_throws_or_emits_nonfinite_numbers(proposal, portfolio, config):
    result = check_policy(proposal, portfolio, config)
    snapshot(result)
    if not isinstance(proposal, dict):
        assert not result["approved"]
