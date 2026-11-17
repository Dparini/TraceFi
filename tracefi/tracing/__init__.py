from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from time import perf_counter_ns
from types import TracebackType
from typing import Any, Literal, Protocol, cast
from uuid import uuid4

from tracefi.hashing import now, snapshot
from tracefi.schema import (
    decision_state,
    final_status,
    finish,
    new_event,
    new_record,
    new_span,
    seal,
)
from tracefi.security import Redactor


class TraceSink(Protocol):
    def save(self, trace: dict[str, Any]) -> None: ...


def identifier(prefix: str) -> str:
    return prefix + "_" + uuid4().hex


class Span:
    def __init__(self, decision: DecisionTrace, name: str, kind: str | None = None) -> None:
        if (
            not isinstance(name, str)
            or not name
            or kind is not None
            and (not isinstance(kind, str) or not kind)
        ):
            raise ValueError("Span name and kind must be nonempty strings")
        self.decision = decision
        self.record = new_span(identifier("sp"), name, kind or name)

    def __enter__(self) -> Span:
        if not self.decision.active:
            raise RuntimeError("Spans require an active decision")
        if self.record["start"] is not None:
            raise RuntimeError("Spans are single-use")
        self.record["parent_id"] = self.decision.parent.get()
        self.record["start"] = now()
        self.started = perf_counter_ns()
        self.token = self.decision.parent.set(self.record["id"])
        self.decision.record["spans"].append(self.record)
        self.decision.open_spans.add(self.record["id"])
        return self

    def _open(self) -> bool:
        return (
            self.decision.active
            and self.record["status"] == "pending"
            and self.record["start"] is not None
        )

    def log(self, payload: Any) -> None:
        if not self._open():
            raise RuntimeError("Cannot log to an inactive span")
        self.record["events"].append(new_event(self.decision.clean(payload)))

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if not self._open():
            raise RuntimeError("Cannot close an inactive span")
        if self.decision.parent.get() != self.record["id"]:
            raise RuntimeError("Nested spans must close in reverse order")
        finish(
            self.record,
            perf_counter_ns() - self.started,
            "error" if exc_type else "success",
            # Exception strings frequently embed request headers and credentials.
            exc_type.__name__ if exc_type else None,
        )
        self.decision.parent.reset(self.token)
        self.decision.open_spans.remove(self.record["id"])
        return False


class DecisionTrace:
    def __init__(
        self,
        sink: TraceSink,
        redactor: Redactor,
        agent: str,
        version: str,
        model: Any = None,
        portfolio: Any = None,
        agent_config: Any = None,
        policy_config: Any = None,
    ) -> None:
        if not isinstance(agent, str) or not isinstance(version, str):
            raise TypeError("Agent and version must be strings")
        for state in (portfolio, agent_config, policy_config):
            if state is not None and not isinstance(state, Mapping):
                raise TypeError("Decision state components must be JSON objects")
        self.sink = sink
        self.redactor = redactor
        self.open_spans: set[str] = set()
        self.parent: ContextVar[str | None] = ContextVar(
            "tracefi_parent_" + uuid4().hex, default=None
        )
        self.active = False
        self.finished = False
        self.record = new_record(
            trace_id=identifier("tr"),
            timestamp=now(),
            agent=agent,
            version=version,
            model=model,
            redaction_keys=sorted(redactor.keys),
            state={
                "portfolio": self.clean(portfolio or {}),
                "agent_configuration": self.clean(agent_config or {}),
                "policy_configuration": self.clean(policy_config or {}),
            },
        )

    @property
    def trace_id(self) -> str:
        return cast(str, self.record["trace_id"])

    def clean(self, value: Any) -> Any:
        return snapshot(self.redactor(value))

    def state(self) -> dict[str, Any]:
        """An independent copy of the decision state captured so far, as adapters receive it."""
        return decision_state(self.record)

    def __enter__(self) -> DecisionTrace:
        if self.active or self.finished:
            raise RuntimeError("Decision contexts are single-use")
        self.record["timestamp"] = now()
        self.started = perf_counter_ns()
        self.active = True
        return self

    def span(self, name: str, kind: str | None = None) -> Span:
        return Span(self, name, kind)

    def _capture(self, field: str, value: Any, kind: str) -> None:
        if not self.active:
            raise RuntimeError("Capture requires an active decision")
        if not isinstance(value, Mapping):
            raise TypeError("Captured observations must be JSON objects")
        if field == "context" and self.record["proposal"] is not None:
            raise RuntimeError("Context is frozen after the decision is captured")
        if field == "proposal" and self.record["proposal"] is not None:
            raise RuntimeError("Each trace captures exactly one decision")
        cleaned = self.clean(value)
        with self.span(kind) as span:
            span.log(cleaned)
        self.record[field] = cleaned

    def capture_context(self, value: Any) -> None:
        self._capture("context", value, "data")

    def capture_decision(self, value: Any) -> None:
        self._capture("proposal", value, "proposal")

    def capture_policy(self, value: Any) -> None:
        self._capture("policy", value, "policy")

    def capture_simulation(self, value: Any) -> None:
        self._capture("simulation", value, "simulation")

    def capture_execution(self, value: Any) -> None:
        self._capture("execution", value, "execution")

    def capture_retrieval(self, value: Any) -> None:
        self._capture("retrieval", value, "retrieval")

    def capture_outcome(self, value: Any) -> None:
        self._capture("outcome", value, "outcome")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if not self.active:
            raise RuntimeError("Cannot close an inactive decision")
        try:
            if self.open_spans:
                raise RuntimeError("Cannot finalize a decision with open spans")
            finish(
                self.record,
                perf_counter_ns() - self.started,
                final_status(self.record, raised=exc_type is not None),
                exc_type.__name__ if exc_type else None,
            )
            self.record = self.clean(self.record)
            seal(self.record)
            self.sink.save(self.record)
        finally:
            self.active = False
            self.finished = True
        return False
