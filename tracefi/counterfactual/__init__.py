"""One-variable experiments; no invented historical execution or PnL."""
from copy import deepcopy
from tracefi.analysis import changed_paths, replay
from tracefi.hashing import state_hash
from tracefi.models import decision_state, observed_decision
from tracefi.models.deterministic import finite_number


def action_signature(proposal):
    return {key: proposal.get(key) for key in ("action", "protocol", "asset", "amount")}


def set_path(state, path, value, present=True):
    parts = path.split(".")
    current = state
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            raise ValueError(f"Unknown input path: {path}")
        current = current[part]
    if not isinstance(current, dict):
        raise ValueError(f"Input path is not an object: {path}")
    if present:
        current[parts[-1]] = value
    else:
        current.pop(parts[-1], None)


def counterfactual(trace, adapter, path, value):
    verified = replay(trace, adapter)
    if not verified["equal"]:
        raise ValueError("Adapter does not reproduce this trace; counterfactual attribution is unavailable")
    state = decision_state(trace)
    modified = deepcopy(state)
    set_path(modified, path, value)
    result = observed_decision(adapter, modified, trace.get("redaction_keys", ()))
    return {"feature": path, "value": value, "original": verified["original"], "counterfactual": result,
            "decision_changed": action_signature(result) != action_signature(verified["original"])}


def boundary(trace, adapter, path, low, high, iterations=24):
    if not finite_number(low) or not finite_number(high) or low >= high:
        raise ValueError("Boundary requires finite low < high")
    if not 1 <= iterations <= 60:
        raise ValueError("Iterations must be between 1 and 60")
    verified = replay(trace, adapter)
    if not verified["equal"]:
        raise ValueError("Adapter does not reproduce this trace")
    state = decision_state(trace)
    def decide(value):
        modified = deepcopy(state)
        set_path(modified, path, value)
        return action_signature(observed_decision(adapter, modified, trace.get("redaction_keys", ())))
    left, right = decide(low), decide(high)
    if left == right:
        return {"feature": path, "boundary_found": False, "interval": [low, high],
                "limitations": "Equal endpoints do not exclude changes inside the interval."}
    for _ in range(iterations):
        middle = (low + high) / 2
        if decide(middle) == left:
            low = middle
        else:
            high = middle
    return {"feature": path, "boundary_found": True, "interval": [low, high], "below": left, "above": right,
            "limitations": "Local bracket under a monotonic-transition assumption; not a global decision boundary."}


def why_change(a, b, adapter):
    if not replay(a, adapter)["equal"] or not replay(b, adapter)["equal"]:
        raise ValueError("Adapter must reproduce both decisions before attribution")
    state = decision_state(a)
    changes = changed_paths(state, decision_state(b))
    tests = []
    target = action_signature(b["proposal"])
    original = action_signature(a["proposal"])
    for change in changes:
        modified = deepcopy(state)
        set_path(modified, change["path"], change["after"], change["after_present"])
        result = observed_decision(adapter, modified, a.get("redaction_keys", ()))
        signature = action_signature(result)
        tests.append({**change, "decision": result, "decision_changed": signature != original,
                      "matches_target": signature == target and signature != original})
    drivers = [test["path"] for test in tests if test["matches_target"]]
    return {"trace_a": a["trace_id"], "trace_b": b["trace_id"], "experiments": tests,
            "primary_decision_driver": drivers[0] if len(drivers) == 1 else None,
            "sufficient_single_changes": drivers,
            "limitations": "Single-variable sufficiency is conditional on recorded state; interactions and nondeterminism can invalidate causal interpretation."}
