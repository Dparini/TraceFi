import json
import signal
import sqlite3
from copy import deepcopy

import pytest

from tests.helpers import make_trace, save
from tracefi import TraceFi
from tracefi.hashing import canonicalize, state_hash
from tracefi.schema import STATE_FIELDS
from tracefi.storage import IntegrityError, SQLiteStorage


@pytest.fixture
def collector(tmp_path):
    with TraceFi(db=tmp_path / "traces.sqlite3") as value:
        yield value


@pytest.fixture
def stored(collector):
    return make_trace(collector=collector)


def test_save_is_atomic():
    with TraceFi(db=":memory:") as collector:
        trace = make_trace()
        trace["spans"].append(deepcopy(trace["spans"][0]))
        with pytest.raises(sqlite3.IntegrityError):
            collector.storage.save(trace)
        assert collector.storage.list() == []


@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM spans WHERE trace_id=:id",
        "UPDATE artifacts SET payload='{}' WHERE trace_id=:id",
        "UPDATE spans SET type='forged' WHERE trace_id=:id",
        "UPDATE traces SET status='failed' WHERE id=:id",
    ],
)
def test_tampered_rows_are_rejected(collector, stored, statement):
    collector.storage.connection.execute(statement, {"id": stored["trace_id"]})
    with pytest.raises(IntegrityError):
        collector.storage.get(stored["trace_id"])
    with pytest.raises(IntegrityError):
        collector.storage.list()


def test_tampered_payload_is_rejected(collector, stored):
    corrupt = json.loads(json.dumps(stored))
    corrupt["context"]["liquidity"] = 1
    collector.storage.connection.execute(
        "UPDATE traces SET payload=? WHERE id=?", (json.dumps(corrupt), stored["trace_id"])
    )
    with pytest.raises(IntegrityError):
        collector.storage.get(stored["trace_id"])


def test_bool_numeric_substitution_in_auxiliary_rows_is_detected():
    with TraceFi(db=":memory:") as collector:
        with collector.decision("integrity") as trace:
            trace.capture_context({"flag": 1})
        collector.storage.connection.execute(
            "UPDATE artifacts SET payload=?,hash=? WHERE id=?",
            ('{"flag":true}', state_hash({"flag": True}), trace.trace_id + ":context"),
        )
        with pytest.raises(IntegrityError):
            collector.storage.get(trace.trace_id)
    with TraceFi(db=":memory:") as collector:
        with collector.decision("integrity") as trace:
            trace.capture_context({"flag": 1})
        span = deepcopy(collector.storage.get(trace.trace_id)["spans"][0])
        span["events"][0]["payload"]["flag"] = True
        collector.storage.connection.execute(
            "UPDATE spans SET payload=? WHERE id=?", (canonicalize(span).decode(), span["id"])
        )
        with pytest.raises(IntegrityError):
            collector.storage.get(trace.trace_id)


def test_malformed_rows_and_invalid_limits():
    with TraceFi(db=":memory:") as collector:
        with collector.decision("row") as trace:
            trace.capture_context({})
        for raw in ("null", "[]", "{", '{"x":1,"x":2}'):
            collector.storage.connection.execute(
                "UPDATE traces SET payload=? WHERE id=?", (raw, trace.trace_id)
            )
            with pytest.raises(IntegrityError):
                collector.storage.get()
        for limit in (0, -1, 1001, True, 1.5):
            with pytest.raises(ValueError):
                collector.storage.list(limit)


def test_original_canonical_format_remains_readable(collector):
    trace = make_trace()
    trace["canonical_version"] = "agenttrace-json-v1"
    collector.storage.save(trace)
    query = "SELECT payload,hash FROM traces WHERE id=?"
    original = collector.storage.connection.execute(query, (trace["trace_id"],)).fetchone()
    assert collector.storage.get(trace["trace_id"])["canonical_version"] == "agenttrace-json-v1"
    assert collector.storage.connection.execute(query, (trace["trace_id"],)).fetchone() == original


@pytest.mark.parametrize(
    "field,value",
    [("schema_version", True), ("schema_version", 2), ("canonical_version", "unsupported")],
)
def test_format_is_rejected_even_when_its_own_hash_matches(field, value):
    trace = make_trace()
    trace[field] = value
    storage = SQLiteStorage(":memory:")
    try:
        storage.save(trace)
        with pytest.raises(IntegrityError):
            storage.get()
    finally:
        storage.close()


@pytest.mark.parametrize("change", ["hash", "identifier", "artifact_identifier"])
def test_independent_integrity_references_are_checked(change):
    storage = SQLiteStorage(":memory:")
    try:
        storage.save(make_trace())
        if change == "hash":
            storage.connection.execute("UPDATE traces SET hash=?", ("0" * 64,))
        elif change == "artifact_identifier":
            storage.connection.execute(
                "UPDATE artifacts SET id=? WHERE type=?", ("unbound-artifact", "context")
            )
        else:
            storage.connection.execute("PRAGMA foreign_keys=OFF")
            storage.connection.execute("UPDATE traces SET id=?", ("unbound-trace",))
        with pytest.raises(IntegrityError):
            storage.get()
    finally:
        storage.close()


def test_state_component_shape_is_verified_independently_of_matching_hashes():
    trace = make_trace()
    trace["context"] = []
    trace["context_hash"] = state_hash([])
    trace["state_hash"] = state_hash({key: trace[key] for key in STATE_FIELDS})
    storage = SQLiteStorage(":memory:")
    try:
        storage.save(trace)
        with pytest.raises(IntegrityError):
            storage.get()
    finally:
        storage.close()


@pytest.mark.parametrize("parent", ["missing", "self", "cycle"])
def test_span_graph_integrity(parent):
    trace = make_trace()
    spans = trace["spans"]
    spans[0]["parent_id"] = (
        "missing" if parent == "missing" else spans[0]["id"] if parent == "self" else spans[1]["id"]
    )
    if parent == "cycle":
        spans[1]["parent_id"] = spans[0]["id"]
    storage = SQLiteStorage(":memory:")
    try:
        storage.save(trace)
        previous = None
        if hasattr(signal, "setitimer"):

            def deadline(signum, frame):
                raise AssertionError("Invalid parent graphs must be rejected promptly")

            previous = signal.signal(signal.SIGALRM, deadline)
            signal.setitimer(signal.ITIMER_REAL, 2)
        try:
            with pytest.raises(IntegrityError):
                storage.get(trace["trace_id"])
        finally:
            if previous is not None:
                signal.setitimer(signal.ITIMER_REAL, 0)
                signal.signal(signal.SIGALRM, previous)
    finally:
        storage.close()


def test_readonly_storage_rejects_writes(tmp_path):
    path = save(tmp_path / "traces.sqlite3", make_trace())
    reader = SQLiteStorage(path, read_only=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader.save(make_trace())
    finally:
        reader.close()


def test_database_symlinks_are_refused(tmp_path):
    target = tmp_path / "db"
    SQLiteStorage(target).close()
    link = tmp_path / "link"
    link.symlink_to(target)
    for read_only in (True, False):
        with pytest.raises(ValueError):
            SQLiteStorage(link, read_only=read_only)
