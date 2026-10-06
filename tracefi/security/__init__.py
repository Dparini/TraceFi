"""Redact before serialization, hashing, persistence and export."""

from collections.abc import Iterable, Mapping
from typing import Any

from tracefi.hashing import MAX_DEPTH, MAX_NODES

REDACTED = "[REDACTED]"
DEFAULT_KEYS = {
    "api_key",
    "private_key",
    "authorization",
    "password",
    "secret",
    "access_token",
    "refresh_token",
}
# These keys carry trace structure or integrity metadata, rather than caller data.
_RESERVED_KEYS = {
    "trace_id",
    "id",
    "parent_id",
    "schema_version",
    "canonical_version",
    "redaction_keys",
    "context",
    "portfolio",
    "agent_configuration",
    "policy_configuration",
    "agent",
    "spans",
    "context_hash",
    "portfolio_hash",
    "policy_hash",
    "agent_config_hash",
    "state_hash",
    "events",
    "payload",
    "start",
    "end",
    "timestamp",
    "duration_ns",
}


class Secret:
    """Explicitly mark a value sensitive; its repr never reveals the value."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def __repr__(self) -> str:
        return REDACTED

    def reveal(self) -> Any:
        return self._value


def _key(value: str) -> str:
    return value.casefold().replace("-", "").replace("_", "")


class Redactor:
    def __init__(self, keys: Iterable[str] = ()) -> None:
        if isinstance(keys, (str, bytes)):
            raise TypeError("Redaction keys must be an iterable of field names")
        extra = set(keys)
        if not all(isinstance(key, str) and key for key in extra):
            raise TypeError("Redaction field names must be nonempty strings")
        normalized = {_key(key) for key in extra}
        if normalized & {_key(key) for key in _RESERVED_KEYS}:
            raise ValueError("Redaction cannot target trace structural fields")
        self.keys = {_key(key) for key in DEFAULT_KEYS} | normalized

    def __call__(self, value: Any) -> Any:
        ancestors: set[int] = set()
        nodes = 0

        def visit(item: Any, depth: int = 0) -> Any:
            nonlocal nodes
            nodes += 1
            if nodes > MAX_NODES or depth > MAX_DEPTH:
                raise ValueError("Redaction input exceeds structural limits")
            if isinstance(item, Secret):
                return REDACTED
            if isinstance(item, (Mapping, list, tuple)):
                identity = id(item)
                if identity in ancestors:
                    raise ValueError("Cyclic values are not JSON")
                ancestors.add(identity)
                try:
                    if isinstance(item, Mapping):
                        return {
                            key: REDACTED
                            if isinstance(key, str) and _key(key) in self.keys
                            else visit(part, depth + 1)
                            for key, part in item.items()
                        }
                    return [visit(part, depth + 1) for part in item]
                finally:
                    ancestors.remove(identity)
            return item

        return visit(value)


def contains_redacted(value: Any) -> bool:
    """Exact markers in values indicate missing state; names/text are not markers."""
    if isinstance(value, str):
        return value == REDACTED
    if isinstance(value, dict):
        return any(contains_redacted(part) for part in value.values())
    if isinstance(value, list):
        return any(contains_redacted(part) for part in value)
    return False
