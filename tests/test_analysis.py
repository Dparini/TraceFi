from copy import deepcopy

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from tests.helpers import JSON, make_trace
from tracefi.analysis import FailureType, analyze, diff
from tracefi.hashing import canonicalize, snapshot

SECTIONS = [
    "context",
    "portfolio",
    "retrieval",
    "proposal",
    "policy",
    "simulation",
    "execution",
    "outcome",
]


def test_complete_successful_trace_has_no_findings():
    report = analyze(make_trace())
    assert report["findings"] == []
    assert report["input_errors"] == []
    assert report["likely_failure_class"] is None


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
    matches = [f for f in analyze(trace)["findings"] if f["type"] == expected]
    assert matches
    assert all(f["certainty"] == certainty and f["path"] == path for f in matches)
    assert all(isinstance(f["evidence"], str) and f["evidence"] for f in matches)


def test_multiple_findings_are_prioritized_and_retained():
    trace = make_trace({"oracle_age_seconds": 301})
    trace["proposal"]["amount"] = 80000
    trace["policy"] = {"approved": True, "should_reject": True}
    trace["retrieval"] = {
        "available_features": ["trend"],
        "included_features": [],
        "required_features": ["trend"],
    }
    trace["simulation"] = {"success": True, "predicted_effect": 1}
    trace["execution"] = {"status": "success", "actual_effect": 2}
    report = analyze(trace)
    assert report["likely_failure_class"] == "POLICY_FAILURE"
    assert {"DATA_FAILURE", "POLICY_FAILURE", "RETRIEVAL_FAILURE", "SIMULATION_FAILURE"} <= {
        f["type"] for f in report["findings"]
    }
    trace["retrieval"] = {"available_features": [{}], "untrusted_data": "not-a-list"}
    assert analyze(trace)["input_errors"]


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
    findings = [f for f in analyze(trace)["findings"] if f["type"] == "SIMULATION_FAILURE"]
    assert bool(findings) is mismatch
    if mismatch:
        assert findings[0]["certainty"] == "observed"
        assert findings[0]["path"] == "simulation.predicted_effect"


def test_simulation_failure_is_observed_without_inferring_execution_failure():
    trace = make_trace()
    trace["simulation"]["success"] = False
    assert [(f["type"], f["certainty"]) for f in analyze(trace)["findings"]] == [
        ("SIMULATION_FAILURE", "observed")
    ]


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


def test_negative_pnl_is_a_market_outcome_only_with_complete_positive_evidence():
    original = make_trace()
    original["outcome"] = {"pnl": -10}
    report = analyze(original)
    assert report["likely_failure_class"] == FailureType.MARKET_OUTCOME.value
    assert report["findings"][0]["certainty"] == "likely"
    for stage in ("context", "portfolio", "proposal", "policy", "simulation", "execution"):
        trace = deepcopy(original)
        trace.pop(stage)
        assert analyze(trace)["likely_failure_class"] != FailureType.MARKET_OUTCOME.value
    for section, field in (("policy", "approved"), ("simulation", "success")):
        trace = deepcopy(original)
        trace[section][field] = False
        assert analyze(trace)["likely_failure_class"] != FailureType.MARKET_OUTCOME.value


@pytest.mark.parametrize(
    "field,invalid",
    [
        ("context", {}),
        ("portfolio", {}),
        ("retrieval", []),
        ("policy", {"approved": "true"}),
        ("proposal", {}),
        ("execution", {"status": "success", "success": False}),
        ("simulation", {"success": "true"}),
    ],
)
def test_negative_outcome_requires_valid_complete_observations(field, invalid):
    trace = make_trace()
    trace["outcome"] = {"pnl": -1}
    trace[field] = invalid
    assert analyze(trace)["likely_failure_class"] != FailureType.MARKET_OUTCOME.value


@pytest.mark.parametrize(
    "section,changes",
    [
        ("context", {"conflicting_sources": "false"}),
        ("retrieval", {"untrusted_data": [{"suspicious": "false"}]}),
    ],
)
def test_malformed_evidence_flags_cannot_support_market_outcome(section, changes):
    trace = make_trace()
    trace[section].update(changes)
    trace["outcome"] = {"pnl": -10}
    report = analyze(trace)
    assert report["input_errors"]
    assert report["likely_failure_class"] is None


@given(st.sampled_from(SECTIONS), JSON)
@example("simulation", {"success": "true"})
@example("retrieval", {"available_features": [None]})
@example("execution", {"status": "blocked", "success": True})
@example("proposal", {"amount": -1})
def test_attribution_handles_arbitrary_json_sections_without_mutation(field, value):
    trace = make_trace()
    trace[field] = value
    before = canonicalize(trace)
    report = analyze(trace)
    snapshot(report)
    assert canonicalize(trace) == before
    if value is not None and not isinstance(value, dict):
        assert report["input_errors"]
        assert report["likely_failure_class"] != "MARKET_OUTCOME"


def test_diff_reports_changed_inputs_and_decisions():
    a = make_trace()
    b = make_trace({"liquidity": 1})
    report = diff(a, b)
    assert [change["path"] for change in report["changed_inputs"]] == ["context.liquidity"]
    assert {change["path"] for change in report["decision_changes"]} >= {"proposal.action"}
    assert diff(a, a)["changed_inputs"] == []
