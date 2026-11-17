"""Replay and bounded one-variable experiments. They never execute financial actions."""

from copy import deepcopy
from typing import Any

from tracefi.hashing import finite_number, snapshot, state_hash
from tracefi.models import ModelAdapter, observed_decision
from tracefi.schema import STATE_FIELDS, changed_paths, clean, decision_state, trace_redactor
from tracefi.security import contains_redacted

ERROR_MESSAGES = {
    "CF01": "Input path must be a string",
    "CF02": "Input path requires a recorded state root and nonempty field names",
    "CF03": "Unknown input path",
    "CF04": "Input path is not an object",
    "CF05": "Adapter must repeatedly reproduce the original decision",
    "CF06": "Counterfactual state contains redacted values",
    "CF07": "Adapter produced unstable counterfactual decisions",
    "CF08": "Boundary requires finite low < high",
    "CF09": "Iterations must be an integer between 1 and 60",
    "CF10": "Boundary feature must be present in recorded state",
    "CF11": "Boundary feature must be a finite numeric value",
    "CF12": "More than two decisions observed; a binary boundary is ambiguous",
    "CF13": "Dotted/empty object keys are ambiguous in counterfactual paths",
    "CF14": "Non-monotonic or multiple decision transitions sampled; boundary unsupported",
}


class CounterfactualError(ValueError):
    """Static diagnostic codes keep adapter exception messages out of CLI output."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(ERROR_MESSAGES[code])


def replay(trace: dict[str, Any], adapter: ModelAdapter) -> dict[str, Any]:
    original = clean(trace, trace.get("proposal"))
    if not isinstance(original, dict):
        raise ValueError("Trace has no recorded decision object")
    state = decision_state(trace)
    if contains_redacted(state):
        raise ValueError("Replay state contains redacted values; exact reproduction is unavailable")
    result = observed_decision(adapter, state, trace_redactor(trace))
    equal = state_hash(original) == state_hash(result)
    return {
        "trace_id": trace["trace_id"],
        "agent": clean(trace, trace["agent"]),
        "original": original,
        "replayed": result,
        "equal": equal,
        "interpretation": "One replay matched" if equal else "Decision divergence",
        "limitations": "A matching replay is not proof of determinism; code, dependencies and model must also match.",
    }


def action_signature(proposal: dict[str, Any]) -> dict[str, Any]:
    return {key: proposal.get(key) for key in ("action", "protocol", "asset", "amount")}


def _signature(proposal: dict[str, Any]) -> str:
    return state_hash(action_signature(proposal))


def set_path(state: dict[str, Any], path: str, value: Any, present: bool = True) -> None:
    if not isinstance(path, str):
        raise CounterfactualError("CF01")
    parts = path.split(".")
    if len(parts) < 2 or any(not part for part in parts) or parts[0] not in STATE_FIELDS:
        raise CounterfactualError("CF02")
    current = state
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise CounterfactualError("CF03")
        current = current[part]
    if not isinstance(current, dict):
        raise CounterfactualError("CF04")
    if present:
        current[parts[-1]] = deepcopy(value)
    else:
        current.pop(parts[-1], None)


def resolve_path(state: dict[str, Any], path: str) -> tuple[bool, Any]:
    """Whether a dot path is recorded in the state, and its value."""
    current: Any = state
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _reproduce(trace: dict[str, Any], adapter: ModelAdapter) -> dict[str, Any]:
    first = replay(trace, adapter)
    second = replay(trace, adapter)
    if not first["equal"] or not second["equal"]:
        raise CounterfactualError("CF05")
    return dict(first["original"])


def _experiment(
    trace: dict[str, Any], adapter: ModelAdapter, state: dict[str, Any]
) -> dict[str, Any]:
    redact = trace_redactor(trace)
    cleaned = snapshot(redact(state))
    if contains_redacted(cleaned):
        raise CounterfactualError("CF06")
    first = observed_decision(adapter, snapshot(cleaned), redact)
    second = observed_decision(adapter, snapshot(cleaned), redact)
    if state_hash(first) != state_hash(second):
        raise CounterfactualError("CF07")
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
        "limitations": "One-variable experiment on the selected adapter. No transaction, policy recheck or financial outcome is simulated.",
    }


def boundary(
    trace: dict[str, Any],
    adapter: ModelAdapter,
    path: str,
    low: int | float,
    high: int | float,
    iterations: int = 24,
) -> dict[str, Any]:
    if not isinstance(path, str):
        raise CounterfactualError("CF01")
    if not finite_number(low) or not finite_number(high) or low >= high:
        raise CounterfactualError("CF08")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 60:
        raise CounterfactualError("CF09")
    _reproduce(trace, adapter)
    state = decision_state(trace)

    def decide(value: int | float) -> dict[str, Any]:
        modified = deepcopy(state)
        set_path(modified, path, value)
        return action_signature(_experiment(trace, adapter, modified))

    present, current = resolve_path(state, path)
    if not present:
        raise CounterfactualError("CF10")
    if not finite_number(current):
        raise CounterfactualError("CF11")
    samples = sorted({low, high, *(low * (1 - i / 16) + high * (i / 16) for i in range(1, 16))})
    samples = [value for value in samples if low <= value <= high and finite_number(value)]
    decisions = [decide(value) for value in samples]
    signatures = [state_hash(value) for value in decisions]
    if len(set(signatures)) > 2:
        raise CounterfactualError("CF12")
    transitions = sum(a != b for a, b in zip(signatures[:-1], signatures[1:], strict=True))
    if transitions > 1:
        raise CounterfactualError("CF14")
    left, right = decisions[0], decisions[-1]
    left_hash, right_hash = signatures[0], signatures[-1]
    diagnostics = {
        "samples": len(samples),
        "sampled_transitions": transitions,
        "monotonicity_proven": False,
    }
    if left_hash == right_hash:
        return {
            "feature": path,
            "boundary_found": False,
            "interval": [low, high],
            "diagnostics": diagnostics,
            "limitations": "No transition sampled. Equal samples do not exclude unseen interior changes.",
        }
    for _ in range(iterations):
        middle = low / 2 + high / 2
        if not low < middle < high:
            break
        signature = state_hash(decide(middle))
        if signature not in (left_hash, right_hash):
            raise CounterfactualError("CF12")
        if signature == left_hash:
            low = middle
        else:
            high = middle
    return {
        "feature": path,
        "boundary_found": True,
        "interval": [low, high],
        "diagnostics": diagnostics,
        "below": left,
        "above": right,
        "limitations": "Local bracket under a monotonic-transition assumption. Repeated matching calls do not prove determinism or a global boundary.",
    }


def _reject_ambiguous_keys(value: Any) -> None:
    if isinstance(value, dict):
        if any(not key or "." in key for key in value):
            raise CounterfactualError("CF13")
        for part in value.values():
            _reject_ambiguous_keys(part)


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
