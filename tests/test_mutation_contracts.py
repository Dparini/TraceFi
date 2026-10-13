"""Independent format, accounting and redaction contracts found in mutation review."""

import json
from copy import deepcopy

import pytest

from tests.helpers import make_trace
from tracefi.analysis import check_policy, replay
from tracefi.counterfactual import boundary
from tracefi.hashing import state_hash
from tracefi.storage import IntegrityError, SQLiteStorage


@pytest.mark.parametrize(
    "field,value",
    [("schema_version", True), ("schema_version", 2), ("canonical_version", "unsupported")],
)
def test_format_is_rejected_even_when_its_own_hash_matches(field, value):
    trace = make_trace()
    trace[field] = value
    storage = SQLiteStorage(":memory:")
    try:
        storage.save(trace)
        with pytest.raises(IntegrityError):
            storage.get()
    finally:
        storage.close()


@pytest.mark.parametrize("change", ["hash", "identifier", "artifact_identifier"])
def test_independent_integrity_references_are_checked(change):
    trace = make_trace()
    storage = SQLiteStorage(":memory:")
    try:
        storage.save(trace)
        if change == "hash":
            storage.connection.execute("UPDATE traces SET hash=?", ("0" * 64,))
        elif change == "artifact_identifier":
            storage.connection.execute(
                "UPDATE artifacts SET id=? WHERE type=?", ("unbound-artifact", "context")
            )
        else:
            storage.connection.execute("PRAGMA foreign_keys=OFF")
            storage.connection.execute("UPDATE traces SET id=?", ("unbound-trace",))
        with pytest.raises(IntegrityError):
            storage.get()
    finally:
        storage.close()


def test_state_component_shape_is_verified_independently_of_matching_hashes():
    trace = make_trace()
    trace["context"] = []
    trace["context_hash"] = state_hash([])
    trace["state_hash"] = state_hash(
        {
            key: trace[key]
            for key in ("context", "portfolio", "agent_configuration", "policy_configuration")
        }
    )
    storage = SQLiteStorage(":memory:")
    try:
        storage.save(trace)
        with pytest.raises(IntegrityError):
            storage.get()
    finally:
        storage.close()


def test_policy_fields_and_other_asset_balances():
    proposal = {"action": "SUPPLY", "asset": "DAI", "amount": 35}
    policy = check_policy(proposal, {"USDC": 1, "DAI": 100}, {"max_exposure": 0.35})
    assert policy == {
        "approved": True,
        "should_reject": False,
        "reasons": [],
        "requested_exposure": 0.35,
        "maximum_exposure": 0.35,
    }
    proposal["amount"] = 36
    policy = check_policy(proposal, {"DAI": 100}, {"max_exposure": 0.35})
    assert policy["should_reject"] is True and policy["reasons"] == ["MAX_EXPOSURE"]


def test_lending_accounting_unknown_protocols_hold_and_fractional_nav():
    config = {"exposure_basis": "total_portfolio", "max_exposure": 0.5}
    portfolio = {"USDC": 0.2, "total_value_usdc": 0.3, "positions": {"A": 0.1, "B": 0}}
    proposal = {"action": "SUPPLY", "asset": "USDC", "protocol": "B", "amount": 0.15}
    assert check_policy(proposal, portfolio, config)["approved"] is True
    proposal["protocol"] = "unknown"
    assert not check_policy(proposal, portfolio, config)["approved"]
    assert check_policy({"action": "HOLD", "asset": "USDC", "amount": 0}, portfolio, config)[
        "approved"
    ]
    proposal.update(protocol="B", asset="ETH")
    assert not check_policy(proposal, portfolio, config)["approved"]
    # Each target's exposure is below the limit, but the aggregate state is inconsistent.
    result = check_policy(
        {"action": "SUPPLY", "asset": "USDC", "protocol": "A", "amount": 1},
        {"USDC": 50000, "total_value_usdc": 100000, "positions": {"A": 20000, "B": 40000}},
        config,
    )
    assert not result["approved"] and "INVALID_POLICY_INPUT" in result["reasons"]


def test_custom_output_secrets_and_replay_identity_are_preserved():
    trace = make_trace()
    trace["redaction_keys"].append("credential")
    trace["proposal"]["credential"] = "[REDACTED]"

    class CustomSecret:
        def decide(self, state):
            result = deepcopy(trace["proposal"])
            result["credential"] = "SYNTHETIC_SECRET_SENTINEL"
            return result

    report = replay(trace, CustomSecret())
    assert report["equal"] is True
    assert report["trace_id"] == trace["trace_id"]
    assert report["agent"] == trace["agent"]
    assert "SYNTHETIC_SECRET_SENTINEL" not in json.dumps(report)


@pytest.mark.parametrize("iterations", [1, 60])
def test_boundary_diagnostic_contract_and_full_signed_interval_sampling(iterations):
    class Hold:
        def decide(self, state):
            return {"action": "HOLD", "asset": "USDC", "amount": 0}

    trace = make_trace({"liquidity": 0}, adapter=Hold())
    report = boundary(trace, Hold(), "context.liquidity", -10, 10, iterations=iterations)
    assert report["feature"] == "context.liquidity"
    assert report["interval"] == [-10, 10]
    assert report["boundary_found"] is False
    assert report["diagnostics"] == {
        "samples": 17,
        "sampled_transitions": 0,
        "monotonicity_proven": False,
    }
