from __future__ import annotations

from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, cast

if TYPE_CHECKING:
    from tracefi.sdk import TraceFi
from collections.abc import Mapping
from contextvars import ContextVar
from datetime import datetime, timezone
from time import perf_counter_ns
from uuid import uuid4

from tracefi.hashing import CANONICAL_VERSION, snapshot, state_hash


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def identifier(prefix: str) -> str:
    return prefix + "_" + uuid4().hex


class Span:
    def __init__(self, decision: DecisionTrace, name: str, kind: str | None = None) -> None:
        self.decision = decision
        self.record: dict[str, Any] = {
            "id": identifier("sp"),
            "name": name,
            "type": kind or name,
            "parent_id": None,
            "start": None,
            "end": None,
            "status": "pending",
            "events": [],
        }

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

    def log(self, payload: Any) -> None:
        if (
            not self.decision.active
            or self.record["status"] != "pending"
            or self.record["start"] is None
        ):
            raise RuntimeError("Cannot log to an inactive span")
        self.record["events"].append({"timestamp": now(), "payload": self.decision.clean(payload)})

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        if (
            not self.decision.active
            or self.record["status"] != "pending"
            or self.record["start"] is None
        ):
            raise RuntimeError("Cannot close an inactive span")
        if self.decision.parent.get() != self.record["id"]:
            raise RuntimeError("Nested spans must close in reverse order")
        self.record["end"] = now()
        self.record["duration_ns"] = perf_counter_ns() - self.started
        self.record["status"] = "error" if exc_type else "success"
        if exc_type:
            # Exception strings frequently embed request headers and credentials.
            self.record["error"] = {"type": exc_type.__name__}
        self.decision.parent.reset(self.token)
        self.decision.open_spans.remove(self.record["id"])
        return False


class DecisionTrace:
    def __init__(
        self,
        owner: TraceFi,
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
        self.owner = owner
        self.open_spans: set[str] = set()
        self.parent: ContextVar[str | None] = ContextVar(
            "tracefi_parent_" + uuid4().hex, default=None
        )
        self.active = False
        self.finished = False
        self.record: dict[str, Any] = {
            "schema_version": 1,
            "canonical_version": CANONICAL_VERSION,
            "redaction_keys": sorted(owner.redactor.keys),
            "trace_id": identifier("tr"),
            "timestamp": now(),
            "end": None,
            "agent": {"name": agent, "version": version, "model": model},
            "context": {},
            "portfolio": self.clean(portfolio or {}),
            "agent_configuration": self.clean(agent_config or {}),
            "policy_configuration": self.clean(policy_config or {}),
            "retrieval": {},
            "proposal": None,
            "policy": None,
            "simulation": None,
            "execution": None,
            "outcome": None,
            "spans": [],
            "status": "pending",
        }

    @property
    def trace_id(self) -> str:
        return cast(str, self.record["trace_id"])

    def clean(self, value: Any) -> Any:
        return snapshot(self.owner.redactor(value))

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
            self.record["end"] = now()
            self.record["duration_ns"] = perf_counter_ns() - self.started
            execution = self.record["execution"] or {}
            policy = self.record["policy"] or {}
            self.record["status"] = (
                "error"
                if exc_type
                else "failed"
                if execution.get("status") in ("failed", "reverted")
                or execution.get("success") is False
                else "rejected"
                if policy.get("approved") is False
                else "success"
            )
            if exc_type:
                self.record["error"] = {"type": exc_type.__name__}
            # Redact first: all hashes must cover exactly the state that is stored.
            self.record = self.clean(self.record)
            for field, hashed in (
                ("context", "context_hash"),
                ("portfolio", "portfolio_hash"),
                ("policy_configuration", "policy_hash"),
                ("agent_configuration", "agent_config_hash"),
            ):
                self.record[hashed] = state_hash(self.record[field])
            self.record["state_hash"] = state_hash(
                {
                    key: self.record[key]
                    for key in (
                        "context",
                        "portfolio",
                        "agent_configuration",
                        "policy_configuration",
                    )
                }
            )
            self.owner.storage.save(self.record)
        finally:
            self.active = False
            self.finished = True
        return False
