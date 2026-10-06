"""Bounded one-variable experiments. They never execute financial actions."""

from copy import deepcopy
from typing import Any

from tracefi.analysis import changed_paths, replay
from tracefi.hashing import snapshot, state_hash
from tracefi.models import ModelAdapter, decision_state, observed_decision
from tracefi.models.deterministic import finite_number
from tracefi.security import Redactor, contains_redacted

_STATE_FIELDS = {"context", "portfolio", "agent_configuration", "policy_configuration"}


def action_signature(proposal: dict[str, Any]) -> dict[str, Any]:
    return {key: proposal.get(key) for key in ("action", "protocol", "asset", "amount")}


def _signature(proposal: dict[str, Any]) -> str:
    return state_hash(action_signature(proposal))


def set_path(state: dict[str, Any], path: str, value: Any, present: bool = True) -> None:
    if not isinstance(path, str):
        raise ValueError("Input path must be a string")
    parts = path.split(".")
    if len(parts) < 2 or any(not part for part in parts) or parts[0] not in _STATE_FIELDS:
        raise ValueError("Input path requires a recorded state root and nonempty field names")
    current = state
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ValueError("Unknown input path")
        current = current[part]
    if not isinstance(current, dict):
        raise ValueError("Input path is not an object")
    if present:
        current[parts[-1]] = deepcopy(value)
    else:
        current.pop(parts[-1], None)


def _reproduce(trace: dict[str, Any], adapter: ModelAdapter) -> dict[str, Any]:
    first = replay(trace, adapter)
    second = replay(trace, adapter)
    if not first["equal"] or not second["equal"]:
        raise ValueError("Adapter must repeatedly reproduce the original decision")
    return dict(first["original"])


def _experiment(
    trace: dict[str, Any], adapter: ModelAdapter, state: dict[str, Any]
) -> dict[str, Any]:
    keys = trace.get("redaction_keys", ())
    cleaned = snapshot(Redactor(keys)(state))
    if contains_redacted(cleaned):
        raise ValueError("Counterfactual state contains redacted values")
    first = observed_decision(adapter, snapshot(cleaned), keys)
    second = observed_decision(adapter, snapshot(cleaned), keys)
    if state_hash(first) != state_hash(second):
        raise ValueError("Adapter produced unstable counterfactual decisions")
    return first


def counterfactual(
    trace: dict[str, Any], adapter: ModelAdapter, path: str, value: Any
) -> dict[str, Any]:
    original = _reproduce(trace, adapter)
    modified = decision_state(trace)
    set_path(modified, path, value)
    result = _experiment(trace, adapter, modified)
    return {
        "feature": path,
        "value": snapshot(value),
        "original": original,
        "counterfactual": result,
        "decision_changed": _signature(result) != _signature(original),
    }


def boundary(
    trace: dict[str, Any],
    adapter: ModelAdapter,
    path: str,
    low: int | float,
    high: int | float,
    iterations: int = 24,
) -> dict[str, Any]:
    if not finite_number(low) or not finite_number(high) or low >= high:
        raise ValueError("Boundary requires finite low < high")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 60:
        raise ValueError("Iterations must be an integer between 1 and 60")
    _reproduce(trace, adapter)
    state = decision_state(trace)

    def decide(value: int | float) -> dict[str, Any]:
        modified = deepcopy(state)
        set_path(modified, path, value)
        return action_signature(_experiment(trace, adapter, modified))

    left, right = decide(low), decide(high)
    left_hash, right_hash = state_hash(left), state_hash(right)
    if left_hash == right_hash:
        return {
            "feature": path,
            "boundary_found": False,
            "interval": [low, high],
            "limitations": "Equal endpoints do not exclude changes inside the interval.",
        }
    for _ in range(iterations):
        # Splitting each operand avoids overflow when both endpoints are large.
        middle = low / 2 + high / 2
        if not low < middle < high:
            break  # Adjacent representable numbers cannot be subdivided further.
        signature = state_hash(decide(middle))
        if signature not in (left_hash, right_hash):
            raise ValueError("More than two decisions observed; a binary boundary is ambiguous")
        if signature == left_hash:
            low = middle
        else:
            high = middle
    return {
        "feature": path,
        "boundary_found": True,
        "interval": [low, high],
        "below": left,
        "above": right,
        "limitations": "Local bracket under a monotonic-transition assumption. Repeated matching calls do not prove determinism or a global boundary.",
    }


def _reject_ambiguous_keys(value: Any) -> None:
    if isinstance(value, dict):
        if any(not key or "." in key for key in value):
            raise ValueError("Dotted/empty object keys are ambiguous in counterfactual paths")
        for part in value.values():
            _reject_ambiguous_keys(part)
    # Lists are atomic leaves, never traversed by dot paths.


def why_change(a: dict[str, Any], b: dict[str, Any], adapter: ModelAdapter) -> dict[str, Any]:
    _reproduce(a, adapter)
    _reproduce(b, adapter)
    state = decision_state(a)
    other = decision_state(b)
    _reject_ambiguous_keys(state)
    _reject_ambiguous_keys(other)
    changes = changed_paths(state, other)
    tests = []
    target = _signature(b["proposal"])
    original = _signature(a["proposal"])
    for change in changes:
        modified = deepcopy(state)
        set_path(modified, change["path"], change["after"], change["after_present"])
        result = _experiment(a, adapter, modified)
        signature = _signature(result)
        tests.append(
            {
                **change,
                "decision": result,
                "decision_changed": signature != original,
                "matches_target": signature == target and signature != original,
            }
        )
    drivers = [test["path"] for test in tests if test["matches_target"]]
    return {
        "trace_a": a["trace_id"],
        "trace_b": b["trace_id"],
        "experiments": tests,
        "primary_decision_driver": drivers[0] if len(drivers) == 1 else None,
        "sufficient_single_changes": drivers,
        "limitations": "Single-variable sufficiency is conditional on recorded state. Interactions and nondeterminism remain possible despite repeated matching calls.",
    }
