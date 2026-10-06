"""Behavioral guards added after inspecting surviving mutations."""

from copy import deepcopy
from unittest.mock import patch

import pytest

from tests.helpers import make_trace
from tracefi.analysis import FailureType, analyze, valid_proposal
from tracefi.counterfactual import why_change
from tracefi.models import load_adapter
from tracefi.security import REDACTED, Redactor


def test_why_change_rejects_ambiguous_nested_paths():
    adapter = load_adapter("deterministic")
    for key in ("", "liquidity.foo"):
        a = make_trace({"metadata": {key: 1}})
        b = make_trace({"metadata": {key: 2}})
        with pytest.raises(ValueError):
            why_change(a, b, adapter)


def test_redaction_structural_limits_and_secret_subtrees():
    with patch("tracefi.security.MAX_DEPTH", 2):
        assert Redactor()([["leaf"]]) == [["leaf"]]
        with pytest.raises(ValueError):
            Redactor()([[["too deep"]]])
    with patch("tracefi.security.MAX_NODES", 3):
        assert Redactor()([1, 2]) == [1, 2]
        with pytest.raises(ValueError):
            Redactor()([1, 2, 3])
    cycle = []
    cycle.append(cycle)
    assert Redactor()({"private-key": cycle}) == {"private-key": REDACTED}
    assert Redactor()({"AUTHORIZATION": "a", "Access-Token": "b", "refresh_token": "c"}) == {
        "AUTHORIZATION": REDACTED,
        "Access-Token": REDACTED,
        "refresh_token": REDACTED,
    }


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


def test_market_outcome_requires_all_positive_evidence():
    original = make_trace()
    original["outcome"] = {"pnl": -10}
    assert analyze(original)["likely_failure_class"] == FailureType.MARKET_OUTCOME.value
    for stage in ("context", "portfolio", "proposal", "policy", "simulation", "execution"):
        trace = deepcopy(original)
        trace.pop(stage)
        assert analyze(trace)["likely_failure_class"] != FailureType.MARKET_OUTCOME.value
    for section, field in (("policy", "approved"), ("simulation", "success")):
        trace = deepcopy(original)
        trace[section][field] = False
        assert analyze(trace)["likely_failure_class"] != FailureType.MARKET_OUTCOME.value
