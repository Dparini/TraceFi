"""Adapters receive the entire recorded decision state, not hidden live inputs."""

import importlib
from typing import Any, Protocol, cast

from tracefi.hashing import snapshot
from tracefi.security import Redactor


class ModelAdapter(Protocol):
    def decide(self, state: dict[str, Any]) -> dict[str, Any]: ...


def decision_state(trace: dict[str, Any]) -> dict[str, Any]:
    fields = ("context", "portfolio", "agent_configuration", "policy_configuration")
    if any(not isinstance(trace.get(key), dict) for key in fields):
        raise ValueError("Replay requires all four recorded state objects")
    state = {key: trace[key] for key in fields}
    return cast(dict[str, Any], snapshot(Redactor(trace.get("redaction_keys", ()))(state)))


def load_adapter(name: str) -> ModelAdapter:
    if name in ("deterministic", "agent-v1", "agent-v2"):
        from tracefi.models.deterministic import DeterministicAgent

        return DeterministicAgent(
            version="1" if name == "agent-v1" else "2" if name == "agent-v2" else None
        )
    if name == "ollama":
        from tracefi.models.ollama import OllamaAgent

        return OllamaAgent()
    if ":" not in name:
        raise ValueError(
            "Adapter must be deterministic, agent-v1, agent-v2, ollama or module:factory"
        )
    module, attribute = name.split(":", 1)
    factory = getattr(importlib.import_module(module), attribute)
    adapter = factory()
    if not callable(getattr(adapter, "decide", None)):
        raise TypeError("Adapter must implement decide(state)")
    return cast(ModelAdapter, adapter)


def observed_decision(
    adapter: ModelAdapter, state: dict[str, Any], redaction_keys: Any = ()
) -> dict[str, Any]:
    """Sanitize adapter outputs before reporting or comparing stored proposals."""
    output = snapshot(Redactor(redaction_keys)(adapter.decide(state)))
    if not isinstance(output, dict):
        raise TypeError("Adapter decision must be a JSON object")
    return output
