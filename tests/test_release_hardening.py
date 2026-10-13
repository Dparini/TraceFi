import io
import os
import signal
from contextlib import redirect_stderr
from copy import deepcopy

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tests.helpers import make_trace
from tracefi import TraceFi
from tracefi.analysis import analyze, replay
from tracefi.cli import main
from tracefi.counterfactual import boundary
from tracefi.hashing import canonicalize, snapshot
from tracefi.models import load_adapter
from tracefi.security.files import write_export
from tracefi.storage import IntegrityError, SQLiteStorage


def test_read_commands_do_not_create_missing_database(tmp_path):
    db = tmp_path / "missing.sqlite3"
    for command in ("list", "show", "analyze"):
        errors = io.StringIO()
        with redirect_stderr(errors):
            assert main(["--db", str(db), command]) == 2
        assert "missing" in errors.getvalue().lower()
        assert not db.exists()


def test_export_is_private_atomic_and_non_overwriting(tmp_path):
    target = tmp_path / "report.html"
    write_export(target, "complete")
    assert target.read_text() == "complete"
    if os.name == "posix":
        assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_export(target, "replacement")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        write_export(link, "leak")
    assert target.read_text() == "complete"
    assert not list(tmp_path.glob(".tracefi-*"))


def test_database_symlinks_are_refused(tmp_path):
    target = tmp_path / "db"
    SQLiteStorage(target).close()
    link = tmp_path / "link"
    link.symlink_to(target)
    for readonly in (True, False):
        with pytest.raises(ValueError):
            SQLiteStorage(link, read_only=readonly)


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


def test_simulation_failure_is_observed_without_inferring_execution_failure():
    trace = make_trace()
    trace["simulation"]["success"] = False
    report = analyze(trace)
    assert [(f["type"], f["certainty"]) for f in report["findings"]] == [
        ("SIMULATION_FAILURE", "observed")
    ]


def test_boundary_detects_sampled_nonmonotonicity():
    class Wavy:
        def decide(self, state):
            x = state["context"]["liquidity"]
            return {
                "action": "SUPPLY" if 3 <= x < 7 or x >= 9 else "HOLD",
                "asset": "USDC",
                "amount": 1 if 3 <= x < 7 or x >= 9 else 0,
            }

    trace = make_trace({"liquidity": 0}, adapter=Wavy())
    for high in (8, 10):
        with pytest.raises(ValueError, match="Non-monotonic"):
            boundary(trace, Wavy(), "context.liquidity", 0, high)


@pytest.mark.parametrize("feature", ["context.absent", "context.protocol"])
def test_boundary_requires_recorded_numeric_feature(feature):
    with pytest.raises(ValueError):
        boundary(make_trace({"protocol": "A"}), load_adapter("deterministic"), feature, 0, 10)


@pytest.mark.parametrize("threshold", [0, 10, 5])
def test_boundary_endpoint_transitions_and_no_transition(threshold):
    class Step:
        def decide(self, state):
            active = state["context"]["liquidity"] >= threshold
            return {
                "action": "SUPPLY" if active else "HOLD",
                "asset": "USDC",
                "amount": int(active),
            }

    trace = make_trace({"liquidity": 5}, adapter=Step())
    report = boundary(trace, Step(), "context.liquidity", 0, 10)
    assert report["boundary_found"] is (threshold != 0)
    assert report["diagnostics"]["monotonicity_proven"] is False
    if threshold:
        assert report["interval"][0] < threshold <= report["interval"][1]


def test_replay_compares_rationale_and_incompatible_versions():
    trace = make_trace()

    class ChangedRationale:
        def decide(self, state):
            result = load_adapter("deterministic").decide(state)
            result["rationale"] = {"factors": ["different explanation"]}
            return result

    assert not replay(trace, ChangedRationale())["equal"]
    assert not replay(trace, load_adapter("agent-v2"))["equal"]


@given(st.lists(st.text(max_size=15), max_size=8))
def test_export_import_supported_semantics_and_nested_span_parents(labels):
    with TraceFi(db=":memory:") as collector:
        with collector.decision("property") as trace:
            with trace.span("parent"):
                for label in labels:
                    with trace.span("child") as span:
                        span.log({"label": label, "private_key": "SYNTHETIC_SECRET"})
        record = collector.storage.get(trace.trace_id)
        copied = snapshot(record)
        assert canonicalize(record) == canonicalize(copied)
        assert all(span["parent_id"] == record["spans"][0]["id"] for span in record["spans"][1:])
        assert "SYNTHETIC_SECRET" not in str(copied)
        assert record == deepcopy(record)


def test_policy_does_not_round_tiny_positive_exposure_to_zero():
    from tracefi.analysis import check_policy

    result = check_policy(
        {"action": "SUPPLY", "asset": "USDC", "amount": 1e-300},
        {"USDC": 1e308},
        {"max_exposure": 0},
    )
    assert not result["approved"]
    assert result["requested_exposure"] is None


def test_dataset_resource_limits_and_symlinks(tmp_path, monkeypatch):
    import tracefi.evals as evaluation

    for index in range(3):
        (tmp_path / f"{index}.json").write_text('{"state":{}}')
    monkeypatch.setattr(evaluation, "MAX_SCENARIOS", 2)
    with pytest.raises(ValueError, match="count limit"):
        evaluation.load_scenarios(tmp_path)
    monkeypatch.setattr(evaluation, "MAX_SCENARIOS", 10)
    monkeypatch.setattr(evaluation, "MAX_DATASET_BYTES", 2)
    with pytest.raises(ValueError, match="byte limit"):
        evaluation.load_scenarios(tmp_path)
    monkeypatch.setattr(evaluation, "MAX_DATASET_BYTES", 10000)
    (tmp_path / "link.json").symlink_to(tmp_path / "0.json")
    with pytest.raises(ValueError, match="symlinks"):
        evaluation.load_scenarios(tmp_path)


def test_policy_decimal_comparison_preserves_large_integer_thresholds():
    from tracefi.analysis import check_policy

    nav = 10**100
    result = check_policy(
        {"action": "SUPPLY", "asset": "USDC", "amount": 35 * 10**98 + 1},
        {"USDC": nav},
        {"max_exposure": 0.35},
    )
    assert not result["approved"]


def test_counterfactual_adapter_exceptions_do_not_mutate_traces():
    from tracefi.counterfactual import counterfactual
    from tracefi.hashing import state_hash

    class FailOnIntervention:
        calls = 0

        def decide(self, state):
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("SECRET_SENTINEL")
            return load_adapter("deterministic").decide(state)

    trace = make_trace()
    original = state_hash(trace)
    with pytest.raises(RuntimeError):
        counterfactual(trace, FailOnIntervention(), "context.liquidity", 1)
    assert state_hash(trace) == original


def test_missing_adapter_dependency_has_safe_actionable_cli_error(tmp_path):
    db = tmp_path / "db"
    storage = SQLiteStorage(db)
    storage.save(make_trace())
    storage.close()
    stream = io.StringIO()
    with redirect_stderr(stream):
        assert (
            main(
                [
                    "--db",
                    str(db),
                    "replay",
                    "latest",
                    "--adapter",
                    "MISSING_SECRET_SENTINEL:factory",
                ]
            )
            == 2
        )
    assert "dependency unavailable" in stream.getvalue()
    assert "SECRET_SENTINEL" not in stream.getvalue()


def test_export_creation_failure_preserves_error_and_cleans_temp_files(tmp_path, monkeypatch):
    import tracefi.security.files as files

    def denied(**kwargs):
        raise PermissionError("synthetic failure")

    with monkeypatch.context() as patched:
        patched.setattr(files.tempfile, "NamedTemporaryFile", denied)
        with pytest.raises(PermissionError):
            write_export(tmp_path / "output", "data")
    with pytest.raises(UnicodeEncodeError):
        write_export(tmp_path / "invalid", "\ud800")
    assert list(tmp_path.iterdir()) == []


def test_export_publication_stays_on_destination_filesystem(tmp_path, monkeypatch):
    import tracefi.security.files as files

    link = files.os.link

    def same_filesystem(source, destination):
        assert os.path.dirname(source) == str(destination.parent)
        link(source, destination)

    monkeypatch.setattr(files.os, "link", same_filesystem)
    write_export(tmp_path / "report", "data")
    assert (tmp_path / "report").read_text() == "data"


def test_nonmonotonic_cli_diagnostic_is_explicit(tmp_path, monkeypatch):
    class Wavy:
        def decide(self, state):
            active = 3 <= state["context"]["liquidity"] < 7
            return {
                "action": "SUPPLY" if active else "HOLD",
                "asset": "USDC",
                "amount": int(active),
            }

    db = tmp_path / "db"
    storage = SQLiteStorage(db)
    storage.save(make_trace({"liquidity": 0}, adapter=Wavy()))
    storage.close()
    monkeypatch.setattr("tracefi.cli.load_adapter", lambda name: Wavy())
    stream = io.StringIO()
    with redirect_stderr(stream):
        assert (
            main(
                [
                    "--db",
                    str(db),
                    "counterfactual",
                    "latest",
                    "--adapter",
                    "wavy",
                    "--feature",
                    "context.liquidity",
                    "--low",
                    "0",
                    "--high",
                    "10",
                ]
            )
            == 2
        )
    assert "CF14: Non-monotonic" in stream.getvalue()


def test_boundary_invalid_path_type_is_diagnosed():
    with pytest.raises(ValueError, match="path must be a string"):
        boundary(make_trace(), load_adapter("deterministic"), None, 0, 1)
