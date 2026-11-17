import pytest
from hypothesis import given
from hypothesis import strategies as st

from tracefi import TraceFi
from tracefi.hashing import canonicalize, snapshot


def test_captures_are_independent_snapshots():
    with TraceFi(db=":memory:") as collector:
        with collector.decision("snapshot") as trace:
            context = {"list": [1]}
            trace.capture_context(context)
            context["list"].append(2)
        assert collector.storage.get(trace.trace_id)["context"] == {"list": [1]}


def test_exception_type_only_and_nested_spans(tmp_path):
    path = tmp_path / "traces.sqlite3"
    with TraceFi(db=path) as collector:
        with pytest.raises(RuntimeError):
            with collector.decision("failure") as trace:
                with trace.span("outer"):
                    with trace.span("inner"):
                        raise RuntimeError("PRIVATE_EXCEPTION_SENTINEL")
        stored = collector.storage.get(trace.trace_id)
    assert stored["status"] == "error"
    assert stored["spans"][1]["parent_id"] == stored["spans"][0]["id"]
    assert b"PRIVATE_EXCEPTION_SENTINEL" not in path.read_bytes()


@pytest.mark.parametrize(
    "policy,execution,status",
    [
        ({"approved": True}, {"status": "success"}, "success"),
        ({"approved": False}, {"status": "blocked"}, "rejected"),
        ({"approved": True}, {"status": "reverted"}, "failed"),
        ({"approved": True}, {"status": "success", "success": False}, "failed"),
    ],
)
def test_status_follows_recorded_policy_and_execution(policy, execution, status):
    with TraceFi(db=":memory:") as collector:
        with collector.decision("status") as trace:
            trace.capture_policy(policy)
            trace.capture_execution(execution)
        assert collector.storage.get(trace.trace_id)["status"] == status


def test_context_frozen_and_one_decision_per_trace():
    with TraceFi(db=":memory:") as collector:
        with collector.decision("frozen") as trace:
            with pytest.raises(TypeError):
                trace.capture_decision(None)
            trace.capture_context({"price": 1})
            trace.capture_decision({"action": "HOLD", "amount": 0})
            with pytest.raises(RuntimeError):
                trace.capture_context({"price": 2})
            with pytest.raises(RuntimeError):
                trace.capture_decision({"action": "SUPPLY", "amount": 1})


def test_reusing_or_leaving_spans_open_is_rejected():
    with TraceFi(db=":memory:") as collector:
        with collector.decision("span-test") as trace:
            span = trace.span("once")
            with span:
                span.log({"records": 1})
            with pytest.raises(RuntimeError):
                span.__enter__()
            with pytest.raises(RuntimeError):
                span.log({})
        with pytest.raises(RuntimeError):
            trace.__enter__()
        with pytest.raises(RuntimeError):
            trace.__exit__(None, None, None)
        unfinished = collector.decision("unfinished")
        with pytest.raises(RuntimeError):
            with unfinished:
                unfinished.span("open").__enter__()
        assert not unfinished.active
        assert unfinished.finished
        assert len(collector.storage.list()) == 1


def test_storage_failure_deactivates_trace():
    class FailingStorage:
        def save(self, trace):
            raise OSError("disk full")

        def close(self):
            pass

    with TraceFi(storage=FailingStorage()) as collector:
        trace = collector.decision("unsaved")
        with pytest.raises(OSError):
            with trace:
                trace.capture_context({"price": 1})
        assert not trace.active
        assert trace.finished


@pytest.mark.parametrize("field", ["portfolio", "agent_config", "policy_config"])
def test_state_components_must_be_objects(field):
    with TraceFi(db=":memory:") as collector:
        with pytest.raises(TypeError):
            collector.decision("invalid", **{field: []})


@given(st.lists(st.text(max_size=15), max_size=8))
def test_nested_span_parents_and_redacted_round_trip(labels):
    with TraceFi(db=":memory:") as collector:
        with collector.decision("property") as trace:
            with trace.span("parent"):
                for label in labels:
                    with trace.span("child") as span:
                        span.log({"label": label, "private_key": "SYNTHETIC_SECRET"})
        record = collector.storage.get(trace.trace_id)
    assert canonicalize(record) == canonicalize(snapshot(record))
    assert all(span["parent_id"] == record["spans"][0]["id"] for span in record["spans"][1:])
    assert "SYNTHETIC_SECRET" not in str(record)
