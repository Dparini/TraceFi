"""Adapters receive the entire recorded decision state, not hidden live inputs."""
import importlib
from typing import Protocol, Any
from tracefi.hashing import snapshot
from tracefi.security import Redactor


class ModelAdapter(Protocol):
    def decide(self, context: dict[str, Any]) -> dict[str, Any]: ...


def decision_state(trace):
    return snapshot({key: trace[key] for key in ("context", "portfolio", "agent_configuration", "policy_configuration")})


def load_adapter(name):
    if name in ("deterministic", "agent-v1", "agent-v2"):
        from tracefi.models.deterministic import DeterministicAgent
        return DeterministicAgent(version="1" if name == "agent-v1" else "2" if name == "agent-v2" else None)
    if name == "ollama":
        from tracefi.models.ollama import OllamaAgent
        return OllamaAgent()
    if ":" not in name:
        raise ValueError("Adapter must be deterministic, agent-v1, agent-v2, ollama or module:factory")
    module, attribute = name.split(":", 1)
    factory = getattr(importlib.import_module(module), attribute)
    adapter = factory()
    if not callable(getattr(adapter, "decide", None)):
        raise TypeError("Adapter must implement decide(state)")
    return adapter


def observed_decision(adapter, state, redaction_keys=()):
    """Sanitize adapter outputs before reporting or comparing stored proposals."""
    output = snapshot(Redactor(redaction_keys)(adapter.decide(state)))
    if not isinstance(output, dict):
        raise TypeError("Adapter decision must be a JSON object")
    return output
