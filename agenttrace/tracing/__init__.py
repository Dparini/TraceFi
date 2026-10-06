from contextvars import ContextVar
from collections.abc import Mapping
from datetime import datetime, timezone
from time import perf_counter_ns
from uuid import uuid4
from agenttrace.hashing import CANONICAL_VERSION, snapshot, state_hash


def now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def identifier(prefix):
    return prefix + "_" + uuid4().hex


class Span:
    def __init__(self, decision, name, kind=None):
        self.decision = decision
        self.record = {"id": identifier("sp"), "name": name, "type": kind or name,
                       "parent_id": None, "start": None, "end": None, "status": "pending", "events": []}

    def __enter__(self):
        if not self.decision.active:
            raise RuntimeError("Spans require an active decision")
        self.record["parent_id"] = self.decision.parent.get()
        self.record["start"] = now()
        self.started = perf_counter_ns()
        self.token = self.decision.parent.set(self.record["id"])
        self.decision.record["spans"].append(self.record)
        return self

    def log(self, payload):
        if self.record["status"] != "pending" or self.record["start"] is None:
            raise RuntimeError("Cannot log to an inactive span")
        self.record["events"].append({"timestamp": now(), "payload": self.decision.clean(payload)})

    def __exit__(self, exc_type, exc, traceback):
        self.record["end"] = now()
        self.record["duration_ns"] = perf_counter_ns() - self.started
        self.record["status"] = "error" if exc_type else "success"
        if exc_type:
            # Exception strings frequently embed request headers and credentials.
            self.record["error"] = {"type": exc_type.__name__}
        self.decision.parent.reset(self.token)
        return False


class DecisionTrace:
    def __init__(self, owner, agent, version, model=None, portfolio=None,
                 agent_config=None, policy_config=None):
        if not isinstance(agent, str) or not isinstance(version, str):
            raise TypeError("Agent and version must be strings")
        self.owner = owner
        self.parent = ContextVar("agenttrace_parent_" + uuid4().hex, default=None)
        self.active = False
        self.finished = False
        self.record = {
            "schema_version": 1, "canonical_version": CANONICAL_VERSION,
            "redaction_keys": sorted(owner.redactor.keys),
            "trace_id": identifier("tr"), "timestamp": now(), "end": None,
            "agent": {"name": agent, "version": version, "model": model},
            "context": {}, "portfolio": self.clean(portfolio or {}),
            "agent_configuration": self.clean(agent_config or {}),
            "policy_configuration": self.clean(policy_config or {}),
            "retrieval": {}, "proposal": None, "policy": None,
            "simulation": None, "execution": None, "outcome": None,
            "spans": [], "status": "pending"}

    @property
    def trace_id(self):
        return self.record["trace_id"]

    def clean(self, value):
        return snapshot(self.owner.redactor(value))

    def __enter__(self):
        if self.active or self.finished:
            raise RuntimeError("Decision contexts are single-use")
        self.record["timestamp"] = now()
        self.started = perf_counter_ns()
        self.active = True
        return self

    def span(self, name, kind=None):
        return Span(self, name, kind)

    def _capture(self, field, value, kind):
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

    def capture_context(self, value):
        self._capture("context", value, "data")

    def capture_decision(self, value):
        self._capture("proposal", value, "proposal")

    def capture_policy(self, value):
        self._capture("policy", value, "policy")

    def capture_simulation(self, value):
        self._capture("simulation", value, "simulation")

    def capture_execution(self, value):
        self._capture("execution", value, "execution")

    def capture_retrieval(self, value):
        self._capture("retrieval", value, "retrieval")

    def capture_outcome(self, value):
        self._capture("outcome", value, "outcome")

    def __exit__(self, exc_type, exc, traceback):
        self.record["end"] = now()
        self.record["duration_ns"] = perf_counter_ns() - self.started
        execution = self.record["execution"] or {}
        policy = self.record["policy"] or {}
        self.record["status"] = ("error" if exc_type else "failed" if execution.get("status") in ("failed", "reverted")
                                or execution.get("success") is False else "rejected" if policy.get("approved") is False else "success")
        if exc_type:
            self.record["error"] = {"type": exc_type.__name__}
        for field, hashed in (("context", "context_hash"), ("portfolio", "portfolio_hash"),
                              ("policy_configuration", "policy_hash"), ("agent_configuration", "agent_config_hash")):
            self.record[hashed] = state_hash(self.record[field])
        self.record["state_hash"] = state_hash({key: self.record[key] for key in
                                                ("context", "portfolio", "agent_configuration", "policy_configuration")})
        # Final redaction also protects fields manually added by callers.
        self.record = self.clean(self.record)
        try:
            self.owner.storage.save(self.record)
        finally:
            self.active = False
            self.finished = True
        return False
