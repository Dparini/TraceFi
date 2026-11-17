"""Trace record format: fields, integrity seal, status and trace-scoped redaction."""

from collections.abc import Iterable, Mapping
from typing import Any, cast

from tracefi.hashing import (
    CANONICAL_VERSION,
    SUPPORTED_CANONICAL_VERSIONS,
    now,
    snapshot,
    state_hash,
)
from tracefi.security import Redactor

SCHEMA_VERSION = 1
STATE_HASHES = {
    "context": "context_hash",
    "portfolio": "portfolio_hash",
    "agent_configuration": "agent_config_hash",
    "policy_configuration": "policy_hash",
}
STATE_FIELDS = tuple(STATE_HASHES)
OBSERVATIONS = ("context", "retrieval", "proposal", "policy", "simulation", "execution", "outcome")
FAILED_EXECUTION_STATUSES = ("failed", "reverted")
EXECUTION_STATUSES = ("success", "blocked", *FAILED_EXECUTION_STATUSES)


def redactor(keys: Iterable[str] = ()) -> Redactor:
    """A redactor for trace payloads; it may never erase trace structure."""
    redact = Redactor(keys)
    if any(redact.targets(key) for key in _STRUCTURAL_KEYS):
        raise ValueError("Redaction cannot target trace structural fields")
    return redact


def trace_redactor(trace: Mapping[str, Any]) -> Redactor:
    return redactor(trace.get("redaction_keys", ()))


def clean(trace: Mapping[str, Any], value: Any) -> Any:
    """An independent snapshot of `value`, redacted with the trace's own keys."""
    return snapshot(trace_redactor(trace)(value))


def decision_state(trace: Mapping[str, Any]) -> dict[str, Any]:
    """The complete state an adapter receives: the four recorded state objects."""
    if any(not isinstance(trace.get(key), dict) for key in STATE_FIELDS):
        raise ValueError("Replay requires all four recorded state objects")
    return cast(dict[str, Any], clean(trace, {key: trace[key] for key in STATE_FIELDS}))


def new_record(
    trace_id: str,
    timestamp: str,
    agent: str,
    version: str,
    model: Any,
    redaction_keys: list[str],
    state: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "canonical_version": CANONICAL_VERSION,
        "redaction_keys": redaction_keys,
        "trace_id": trace_id,
        "timestamp": timestamp,
        "end": None,
        "agent": {"name": agent, "version": version, "model": model},
        **{key: state.get(key, {}) for key in STATE_FIELDS},
        "retrieval": {},
        "proposal": None,
        "policy": None,
        "simulation": None,
        "execution": None,
        "outcome": None,
        "spans": [],
        "status": "pending",
    }


def new_span(span_id: str, name: str, kind: str) -> dict[str, Any]:
    return {
        "id": span_id,
        "name": name,
        "type": kind,
        "parent_id": None,
        "start": None,
        "end": None,
        "status": "pending",
        "events": [],
    }


def new_event(payload: Any) -> dict[str, Any]:
    return {"timestamp": now(), "payload": payload}


def finish(record: dict[str, Any], duration_ns: int, status: str, error: str | None) -> None:
    """Close a trace or span record; errors keep only the exception type name."""
    record["end"] = now()
    record["duration_ns"] = duration_ns
    record["status"] = status
    if error is not None:
        record["error"] = {"type": error}


def _structural_keys() -> set[str]:
    record = new_record("", "", "", "", None, [], {})
    finish(record, 0, "", "")
    seal(record)
    return {*record, *record["agent"], *record["error"], *new_span("", "", ""), *new_event(None)}


def execution_failed(execution: Mapping[str, Any]) -> bool:
    return execution.get("status") in FAILED_EXECUTION_STATUSES or execution.get("success") is False


def final_status(record: Mapping[str, Any], raised: bool) -> str:
    if raised:
        return "error"
    if execution_failed(record["execution"] or {}):
        return "failed"
    if (record["policy"] or {}).get("approved") is False:
        return "rejected"
    return "success"


def seal(record: dict[str, Any]) -> None:
    """Hash the stored (already redacted) state components and their combination."""
    for field, hashed in STATE_HASHES.items():
        record[hashed] = state_hash(record[field])
    record["state_hash"] = state_hash({key: record[key] for key in STATE_FIELDS})


def verify_seal(trace: Mapping[str, Any]) -> None:
    version = trace.get("schema_version")
    if (
        version != SCHEMA_VERSION
        or isinstance(version, bool)
        or trace.get("canonical_version") not in SUPPORTED_CANONICAL_VERSIONS
    ):
        raise ValueError("Unsupported trace format")
    for field, hashed in STATE_HASHES.items():
        if not isinstance(trace[field], dict) or state_hash(trace[field]) != trace[hashed]:
            raise ValueError("Snapshot mismatch")
    if state_hash({key: trace[key] for key in STATE_FIELDS}) != trace["state_hash"]:
        raise ValueError("Combined state mismatch")


def changed_paths(a: Any, b: Any, prefix: str = "") -> list[dict[str, Any]]:
    """Dot paths where two JSON values differ; lists compare as whole values."""
    if isinstance(a, dict) and isinstance(b, dict):
        changes = []
        for key in sorted(a.keys() | b.keys()):
            path = f"{prefix}.{key}" if prefix else key
            if key not in a or key not in b:
                changes.append(
                    {
                        "path": path,
                        "before": a.get(key),
                        "after": b.get(key),
                        "before_present": key in a,
                        "after_present": key in b,
                    }
                )
            else:
                changes.extend(changed_paths(a[key], b[key], path))
        return changes
    if state_hash(a) != state_hash(b):
        return [
            {"path": prefix, "before": a, "after": b, "before_present": True, "after_present": True}
        ]
    return []


_STRUCTURAL_KEYS = _structural_keys()
