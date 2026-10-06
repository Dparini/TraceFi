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
        with pytest.raises(ValueError):
            why_change(a, a, adapter)


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


@pytest.mark.parametrize(
    "section,changes,expected,certainty,path",
    [
        (
            "context",
            {"oracle_age_seconds": 301},
            "DATA_FAILURE",
            "observed",
            "context.oracle_age_seconds",
        ),
        (
            "context",
            {"oracle_age_seconds": -1},
            "DATA_FAILURE",
            "observed",
            "context.oracle_age_seconds",
        ),
        (
            "context",
            {"oracle_age_seconds": "stale"},
            "DATA_FAILURE",
            "observed",
            "context.oracle_age_seconds",
        ),
        ("context", {"price": None}, "DATA_FAILURE", "observed", "context.price"),
        (
            "context",
            {"conflicting_sources": True},
            "DATA_FAILURE",
            "likely",
            "context.conflicting_sources",
        ),
        (
            "retrieval",
            {
                "available_features": ["trend"],
                "required_features": ["trend"],
                "included_features": [],
            },
            "RETRIEVAL_FAILURE",
            "likely",
            "retrieval",
        ),
        (
            "retrieval",
            {"untrusted_data": [{"source": "metadata", "suspicious": True}]},
            "ADVERSARIAL_INPUT",
            "likely",
            "retrieval.untrusted_data",
        ),
        ("policy", {"should_reject": True}, "POLICY_FAILURE", "observed", "policy"),
        ("execution", {"status": "reverted"}, "EXECUTION_FAILURE", "observed", "execution"),
        ("execution", {"status": "failed"}, "EXECUTION_FAILURE", "observed", "execution"),
        (
            "execution",
            {"status": None, "success": False},
            "EXECUTION_FAILURE",
            "observed",
            "execution",
        ),
        ("proposal", {"action": "TRANSFER_ALL"}, "REASONING_FAILURE", "observed", "proposal"),
    ],
)
def test_rule_evidence_classification_and_certainty(section, changes, expected, certainty, path):
    trace = make_trace()
    trace.setdefault(section, {}).update(changes)
    report = analyze(trace)
    matches = [finding for finding in report["findings"] if finding["type"] == expected]
    assert matches
    assert all(finding["certainty"] == certainty and finding["path"] == path for finding in matches)
    assert all(isinstance(finding["evidence"], str) and finding["evidence"] for finding in matches)


@pytest.mark.parametrize(
    "predicted,actual,tolerance,mismatch",
    [
        (10, 12, 1, True),
        (10, 11, 1, False),
        (10, 9, 1, False),
        (10, 8, 1, True),
        (10, 10, 0, False),
    ],
)
def test_simulation_tolerance_boundary(predicted, actual, tolerance, mismatch):
    trace = make_trace()
    trace["simulation"].update(predicted_effect=predicted, effect_tolerance=tolerance)
    trace["execution"]["actual_effect"] = actual
    report = analyze(trace)
    findings = [
        finding for finding in report["findings"] if finding["type"] == "SIMULATION_FAILURE"
    ]
    assert bool(findings) is mismatch
    if mismatch:
        assert findings[0]["certainty"] == "observed"
        assert findings[0]["path"] == "simulation.predicted_effect"


def test_retrieval_inclusion_and_fresh_oracle_do_not_create_findings():
    for age in (0, 300):
        trace = make_trace({"oracle_age_seconds": age})
        trace["retrieval"] = {
            "available_features": ["a", "b"],
            "required_features": ["a", "missing"],
            "included_features": ["a"],
        }
        report = analyze(trace)
        assert report["findings"] == []
        assert report["input_errors"] == []
        assert report["coverage"]["retrieval"] == "recorded"


def test_nested_object_redaction_depth_is_bounded():
    with patch("tracefi.security.MAX_DEPTH", 2):
        assert Redactor()({"a": {"b": 1}}) == {"a": {"b": 1}}
        for value in ({"a": {"b": {"c": 1}}}, [{"b": [1]}]):
            with pytest.raises(ValueError):
                Redactor()(value)


def test_redacted_state_inside_arrays_cannot_be_replayed():
    from tracefi.analysis import replay

    for value in (["[REDACTED]"], [{"authorization": "sensitive"}]):
        trace = make_trace()
        trace["context"]["documents"] = value
        with pytest.raises(ValueError):
            replay(trace, load_adapter("deterministic"))


def test_boundary_reports_both_sides_of_the_bracket():
    from tracefi.counterfactual import boundary

    report = boundary(
        make_trace(), load_adapter("deterministic"), "context.liquidity", 10_000_000, 21_000_000
    )
    assert report["boundary_found"] is True
    assert report["below"] == {"action": "HOLD", "protocol": None, "asset": "USDC", "amount": 0}
    assert report["above"] == {
        "action": "SUPPLY",
        "protocol": "protocol_a",
        "asset": "USDC",
        "amount": 25000,
    }
    assert report["interval"][0] < 12_400_000 <= report["interval"][1]


def test_malformed_evidence_flags_cannot_support_market_outcome():
    for section, changes in (
        ("context", {"conflicting_sources": "false"}),
        ("retrieval", {"untrusted_data": [{"suspicious": "false"}]}),
    ):
        trace = make_trace()
        trace.setdefault(section, {}).update(changes)
        trace["outcome"] = {"pnl": -10}
        report = analyze(trace)
        assert report["input_errors"]
        assert report["likely_failure_class"] is None
