"""Adapters receive the entire recorded decision state, not hidden live inputs."""

from typing import Any, Protocol

from tracefi.hashing import snapshot
from tracefi.security import Redactor


class ModelAdapter(Protocol):
    def decide(self, state: dict[str, Any]) -> dict[str, Any]: ...


class ExperimentAdapter(ModelAdapter, Protocol):
    def inputs(self, state: dict[str, Any]) -> dict[str, bool]:
        """Numeric state paths the decision reads, mapped to whether they may be absent."""
        ...


def observed_decision(
    adapter: ModelAdapter, state: dict[str, Any], redact: Redactor | None = None
) -> dict[str, Any]:
    """Sanitize adapter outputs before reporting or comparing stored proposals."""
    output = snapshot((redact or Redactor())(adapter.decide(state)))
    if not isinstance(output, dict):
        raise TypeError("Adapter decision must be a JSON object")
    return output
