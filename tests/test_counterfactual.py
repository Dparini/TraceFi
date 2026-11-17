import json
import math
from copy import deepcopy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.helpers import make_trace
from tracefi import TraceFi
from tracefi.counterfactual import boundary, counterfactual, replay, set_path, why_change
from tracefi.demo import run_demo
from tracefi.hashing import canonicalize, state_hash
from tracefi.registry import load_adapter
from tracefi.schema import decision_state
from tracefi.security import Secret


def hold(amount=0):
    return {"action": "HOLD", "asset": "USDC", "amount": amount}


class Step:
    def __init__(self, threshold):
        self.threshold = threshold

    def decide(self, state):
        active = state["context"]["liquidity"] >= self.threshold
        return {"action": "SUPPLY" if active else "HOLD", "asset": "USDC", "amount": int(active)}


class Wavy:
    def decide(self, state):
        x = state["context"]["liquidity"]
        active = 3 <= x < 7 or x >= 9
        return {"action": "SUPPLY" if active else "HOLD", "asset": "USDC", "amount": int(active)}


# Replay


def test_replay_reports_are_independent_of_the_trace():
    trace = make_trace({"note": "The label [REDACTED] is text", "[REDACTED]": "key"})
    report = replay(trace, load_adapter("deterministic"))
    assert report["equal"]
    report["original"]["amount"] = 99
    report["agent"]["name"] = "changed"
    assert trace["proposal"]["amount"] == 25000
    assert trace["agent"]["name"] == "rule-agent"


@pytest.mark.parametrize(
    "documents", [["[REDACTED]"], [{"authorization": "sensitive"}], "[REDACTED]"]
)
def test_redacted_state_cannot_be_replayed(documents):
    trace = make_trace()
    trace["context"]["documents"] = documents
    with pytest.raises(ValueError):
        replay(trace, load_adapter("deterministic"))


def test_replay_requires_recorded_state_decision_and_object_outputs():
    for field in ("context", "portfolio", "agent_configuration", "policy_configuration"):
        trace = make_trace()
        del trace[field]
        with pytest.raises(ValueError):
            replay(trace, load_adapter("deterministic"))
    for output in (None, [], "HOLD", {"amount": float("inf")}):

        class BadAdapter:
            def decide(self, state, chosen=output):
                return chosen

        with pytest.raises((TypeError, ValueError)):
            replay(make_trace(), BadAdapter())
    trace = make_trace()
    trace["proposal"] = None
    with pytest.raises(ValueError):
        replay(trace, load_adapter("deterministic"))


def test_replay_compares_rationale_and_incompatible_versions():
    class ChangedRationale:
        def decide(self, state):
            result = load_adapter("deterministic").decide(state)
            result["rationale"] = {"factors": ["different explanation"]}
            return result

    trace = make_trace()
    assert not replay(trace, ChangedRationale())["equal"]
    assert not replay(trace, load_adapter("agent-v2"))["equal"]


def test_adapter_output_secrets_are_redacted():
    class LeakyAdapter:
        def decide(self, state):
            return {"action": "HOLD", "amount": 0, "private_key": "OUTPUT_SENTINEL"}

    report = replay(make_trace(), LeakyAdapter())
    assert "OUTPUT_SENTINEL" not in json.dumps(report)
    assert report["replayed"]["private_key"] == "[REDACTED]"


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


# Single interventions


@given(
    st.floats(min_value=0, max_value=0.2, allow_nan=False),
    st.integers(min_value=0, max_value=100_000_000),
)
def test_replay_and_irrelevant_counterfactual_preserve_state(apy, liquidity):
    trace = make_trace({"apy": apy, "liquidity": liquidity})
    before = canonicalize(trace)
    adapter = load_adapter("deterministic")
    assert replay(trace, adapter)["equal"]
    assert not counterfactual(trace, adapter, "context.unused", 42)["decision_changed"]
    assert canonicalize(trace) == before
    assert decision_state(trace)["context"] == trace["context"]


def test_relevant_counterfactual_changes_the_decision():
    report = counterfactual(make_trace(), load_adapter("deterministic"), "context.liquidity", 1)
    assert report["decision_changed"]
    assert report["counterfactual"]["action"] == "HOLD"
    assert report["limitations"]


def test_invalid_paths_and_values():
    trace, adapter = make_trace(), load_adapter("deterministic")
    for path in (
        "",
        "context",
        "context..apy",
        ".apy",
        "metadata.apy",
        "context.missing.value",
        "context.apy.value",
    ):
        with pytest.raises(ValueError):
            counterfactual(trace, adapter, path, 1)
    for value in (float("nan"), float("inf"), Secret("SENSITIVE")):
        with pytest.raises((ValueError, TypeError)):
            counterfactual(trace, adapter, "context.apy", value)
    with pytest.raises(ValueError):
        counterfactual(trace, adapter, "context.private_key", "SENSITIVE")


def test_nondeterministic_baselines_and_candidate_outputs_are_refused():
    original = make_trace()

    class Alternating:
        calls = 0

        def decide(self, state):
            self.calls += 1
            return original["proposal"] if self.calls % 2 else hold()

    with pytest.raises(ValueError):
        counterfactual(original, Alternating(), "context.liquidity", 1)

    class UnstableIntervention:
        calls = 0

        def decide(self, state):
            if state["context"]["liquidity"] == 21000000:
                return original["proposal"]
            self.calls += 1
            return hold(self.calls)

    with pytest.raises(ValueError):
        counterfactual(original, UnstableIntervention(), "context.liquidity", 1)


def test_boolean_amount_does_not_equal_numeric_amount():
    class TypeAdapter:
        def decide(self, state):
            return hold(state["context"]["value"])

    trace = make_trace({"value": False}, TypeAdapter())
    assert counterfactual(trace, TypeAdapter(), "context.value", 0)["decision_changed"]


def test_mutating_adapter_and_input_cannot_mutate_original():
    class Mutating:
        def decide(self, state):
            state["context"].pop("unused", None)
            return hold()

    trace = make_trace(adapter=Mutating())
    before = deepcopy(trace)
    value = {"items": [1]}
    counterfactual(trace, Mutating(), "context.unused", value)
    assert value == {"items": [1]}
    assert trace == before
    set_path(trace, "context.extra", value)
    trace["context"]["extra"]["items"].append(2)
    assert value == {"items": [1]}


def test_adapter_exceptions_do_not_mutate_traces():
    class FailOnIntervention:
        calls = 0

        def decide(self, state):
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("SECRET_SENTINEL")
            return load_adapter("deterministic").decide(state)

    trace = make_trace()
    original = state_hash(trace)
    with pytest.raises(RuntimeError):
        counterfactual(trace, FailOnIntervention(), "context.liquidity", 1)
    assert state_hash(trace) == original


# Boundaries


def test_boundary_brackets_the_liquidity_threshold():
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
    assert report["interval"][1] - report["interval"][0] < 2


def test_boundary_invalid_limits():
    trace, adapter = make_trace(), load_adapter("deterministic")
    with pytest.raises(ValueError, match="path must be a string"):
        boundary(trace, adapter, None, 0, 1)
    for low, high in (
        (1, 1),
        (2, 1),
        (float("nan"), 2),
        (0, float("inf")),
        (True, 2),
        (0, 10**400),
    ):
        with pytest.raises(ValueError):
            boundary(trace, adapter, "context.apy", low, high)
    for count in (0, 61, 1.5, True, "2"):
        with pytest.raises(ValueError):
            boundary(trace, adapter, "context.apy", 0, 1, count)


@pytest.mark.parametrize("feature", ["context.absent", "context.protocol"])
def test_boundary_requires_recorded_numeric_feature(feature):
    with pytest.raises(ValueError):
        boundary(make_trace({"protocol": "A"}), load_adapter("deterministic"), feature, 0, 10)


@pytest.mark.parametrize("iterations", [1, 60])
def test_boundary_without_transition_reports_sampling_diagnostics(iterations):
    class Hold:
        def decide(self, state):
            return hold()

    trace = make_trace({"liquidity": 0}, adapter=Hold())
    report = boundary(trace, Hold(), "context.liquidity", -10, 10, iterations=iterations)
    assert report["feature"] == "context.liquidity"
    assert report["interval"] == [-10, 10]
    assert report["boundary_found"] is False
    assert "do not exclude" in report["limitations"]
    assert report["diagnostics"] == {
        "samples": 17,
        "sampled_transitions": 0,
        "monotonicity_proven": False,
    }


@pytest.mark.parametrize("threshold", [0, 10, 5])
def test_boundary_endpoint_transitions_and_no_transition(threshold):
    trace = make_trace({"liquidity": 5}, adapter=Step(threshold))
    report = boundary(trace, Step(threshold), "context.liquidity", 0, 10)
    assert report["boundary_found"] is (threshold != 0)
    assert report["diagnostics"]["monotonicity_proven"] is False
    if threshold:
        assert report["interval"][0] < threshold <= report["interval"][1]


def test_boundary_detects_sampled_nonmonotonicity_and_third_outcomes():
    trace = make_trace({"liquidity": 0}, adapter=Wavy())
    for high in (8, 10):
        with pytest.raises(ValueError, match="Non-monotonic"):
            boundary(trace, Wavy(), "context.liquidity", 0, high)

    class ThreeOutcomes:
        def decide(self, state):
            x = state["context"]["x"]
            action = "HOLD" if x < 0 else "SUPPLY" if x < 1 else "WITHDRAW"
            return {"action": action, "asset": "USDC", "amount": 0}

    trace = make_trace({"x": -1}, ThreeOutcomes())
    with pytest.raises(ValueError):
        boundary(trace, ThreeOutcomes(), "context.x", -1, 2)


def test_boundary_float_resolution_near_the_float_limit():
    class Threshold:
        def decide(self, state):
            return {
                "action": "HOLD" if state["context"]["x"] < 10**308 else "SUPPLY",
                "asset": "USDC",
                "amount": 0,
            }

    trace = make_trace({"x": 0}, Threshold())
    result = boundary(trace, Threshold(), "context.x", 9e307, 1.1e308)
    assert result["interval"][0] <= 1e308 <= result["interval"][1]
    assert all(math.isfinite(n) for n in result["interval"])
    assert boundary(trace, Threshold(), "context.x", 1e308 - 1e292, 1e308, 60)["boundary_found"]


# Why change


def test_demo_liquidity_drives_the_changed_decision():
    with TraceFi(db=":memory:") as collector:
        result = run_demo(collector)
        second = collector.storage.get(result["trace_ids"][1])
    assert result["why_change"]["primary_decision_driver"] == "context.liquidity"
    assert second["status"] == "rejected"


def test_why_change_identical_interactions_and_multiple_drivers():
    class Logic:
        def __init__(self, operation):
            self.operation = operation

        def decide(self, state):
            x, y = state["context"].get("x", 0), state["context"].get("y", 0)
            active = x and y if self.operation == "and" else x or y
            return {
                "action": "SUPPLY" if active else "HOLD",
                "asset": "USDC",
                "amount": int(bool(active)),
            }

    for mode, sufficient in (("and", []), ("or", ["context.x", "context.y"])):
        adapter = Logic(mode)
        a, b = make_trace({"x": 0, "y": 0}, adapter), make_trace({"x": 1, "y": 1}, adapter)
        report = why_change(a, b, adapter)
        assert report["primary_decision_driver"] is None
        assert report["sufficient_single_changes"] == sufficient
        assert why_change(a, a, adapter)["experiments"] == []


def test_why_change_unused_and_removed_inputs():
    adapter = load_adapter("deterministic")
    a, b = make_trace({"unused": [1]}), make_trace({"unused": [2]})
    assert not why_change(a, b, adapter)["experiments"][0]["decision_changed"]
    a = make_trace({"unused": None})
    assert not why_change(a, make_trace(), adapter)["experiments"][0]["after_present"]


@pytest.mark.parametrize("context", [{"a.b": 1}, {"metadata": {"": 1}}, {"metadata": {"x.y": 1}}])
def test_why_change_rejects_ambiguous_paths(context):
    trace = make_trace(context)
    with pytest.raises(ValueError):
        why_change(trace, trace, load_adapter("deterministic"))
