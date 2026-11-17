import contextlib
import io

import pytest

from tests.helpers import adapter_module, make_trace, save
from tracefi.cli import main

LEAKING_ADAPTER = """
class Leaking:
    def decide(self, state):
        raise RuntimeError("SECRET_SENTINEL")

def factory():
    return Leaking()
"""
WAVY_ADAPTER = """
class Wavy:
    def decide(self, state):
        active = 3 <= state["context"]["liquidity"] < 7
        return {"action": "SUPPLY" if active else "HOLD", "asset": "USDC", "amount": int(active)}

def factory():
    return Wavy()
"""


def run(*arguments):
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors):
        code = main(list(arguments))
    return code, errors.getvalue()


def test_argument_errors_do_not_echo_credentials():
    errors = io.StringIO()
    with contextlib.redirect_stderr(errors), pytest.raises(SystemExit):
        main(["list", "--limit", "SECRET_SENTINEL"])
    assert "SECRET_SENTINEL" not in errors.getvalue()


def test_read_commands_do_not_create_missing_database(tmp_path):
    db = tmp_path / "missing.sqlite3"
    for command in ("list", "show", "analyze"):
        code, errors = run("--db", str(db), command)
        assert code == 2
        assert "missing" in errors.lower()
        assert not db.exists()


def test_adapter_exception_never_enters_cli_errors(tmp_path, monkeypatch):
    db = save(tmp_path / "trace.sqlite3", make_trace())
    adapter = adapter_module(tmp_path, monkeypatch, LEAKING_ADAPTER)
    code, errors = run("--db", str(db), "replay", "latest", "--adapter", adapter)
    assert code == 2
    assert "RuntimeError" in errors
    assert "SECRET_SENTINEL" not in errors
    assert "Traceback" not in errors


def test_missing_adapter_dependency_has_safe_actionable_error(tmp_path):
    db = save(tmp_path / "db", make_trace())
    code, errors = run(
        "--db", str(db), "replay", "latest", "--adapter", "MISSING_SECRET_SENTINEL:factory"
    )
    assert code == 2
    assert "dependency unavailable" in errors
    assert "SECRET_SENTINEL" not in errors


def test_nonmonotonic_boundary_diagnostic_is_explicit(tmp_path, monkeypatch):
    adapter = adapter_module(tmp_path, monkeypatch, WAVY_ADAPTER)
    module, _ = adapter.split(":")
    wavy = __import__(module).factory()
    db = save(tmp_path / "db", make_trace({"liquidity": 0}, adapter=wavy))
    code, errors = run(
        "--db", str(db), "counterfactual", "latest", "--adapter", adapter,
        "--feature", "context.liquidity", "--low", "0", "--high", "10",
    )  # fmt: skip
    assert code == 2
    assert "CF14: Non-monotonic" in errors


def test_replay_exit_code_reflects_divergence(tmp_path):
    db = save(tmp_path / "db", make_trace())
    assert run("--db", str(db), "replay", "latest", "--adapter", "deterministic")[0] == 0
    assert run("--db", str(db), "replay", "latest", "--adapter", "agent-v2")[0] == 1
