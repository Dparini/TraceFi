import contextlib
import io
import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from tests.helpers import make_trace
from tracefi.cli import main
from tracefi.cli.render import decision_text, export_html, postmortem
from tracefi.evals import evaluate, load_scenarios
from tracefi.hashing import MAX_BYTES
from tracefi.models.ollama import OllamaAgent, _NoRedirect
from tracefi.storage import SQLiteStorage


def test_argument_errors_do_not_echo_credentials():
    stream = io.StringIO()
    with contextlib.redirect_stderr(stream), pytest.raises(SystemExit):
        main(["list", "--limit", "SECRET_SENTINEL"])
    assert "SECRET_SENTINEL" not in stream.getvalue()


def test_reports_redact_raw_trace_and_escape_control_characters():
    trace = make_trace()
    trace["context"]["private_key"] = "SECRET_SENTINEL"
    trace["agent"]["name"] = "\x1b[2Jmalicious"
    trace["proposal"]["protocol"] = "<script>alert(1)</script>"
    trace["retrieval"] = {"required_features": 42}
    for report in (postmortem(trace), export_html(trace)):
        assert "SECRET_SENTINEL" not in report
        assert "\x1b" not in report
    assert "<script>alert(1)</script>" not in export_html(trace)
    assert "Invalid observation" in postmortem(trace)
    assert "\x1b" not in decision_text({"action": "\x1b[2J"})


def test_ollama_transport_has_no_proxy_or_redirect_and_bounded_reads():
    response = MagicMock()
    response.read.return_value = json.dumps({"response": '{"action":"HOLD"}'}).encode()
    opener = MagicMock()
    opener.open.return_value.__enter__.return_value = response
    with patch("tracefi.models.ollama.build_opener", return_value=opener) as factory:
        assert OllamaAgent().decide({}) == {"action": "HOLD"}
    proxy, redirect = factory.call_args.args
    assert proxy.proxies == {}
    assert isinstance(redirect, _NoRedirect)
    assert redirect.redirect_request(None, None, 302, "", {}, "https://example.com") is None
    response.read.assert_called_once_with(MAX_BYTES + 1)
    request = opener.open.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:11434/api/generate"
    for payload in (
        b"[]",
        b'{"response": "[]"}',
        b'{"response": "{\\"x\\":NaN}"}',
        b"x" * (MAX_BYTES + 1),
    ):
        response.read.return_value = payload
        with (
            patch("tracefi.models.ollama.build_opener", return_value=opener),
            pytest.raises(ValueError),
        ):
            OllamaAgent().decide({})


def test_readonly_storage_rejects_writes(tmp_path):
    path = tmp_path / "traces.sqlite3"
    SQLiteStorage(path).close()
    reader = SQLiteStorage(path, read_only=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            reader.connection.execute("DELETE FROM traces")
    finally:
        reader.close()


def test_scenario_validation_and_invalid_decision_scoring(tmp_path):
    class InvalidAgent:
        def decide(self, state):
            return {"action": "HOLD", "amount": 12, "asset": []}

    report = evaluate(InvalidAgent(), [{"id": "bad", "state": {}}])
    assert report["metrics"]["valid_decisions"] == 0
    assert report["metrics"]["unsafe_proposals"] == 1
    for payload in ('{"state":{},"id":"a","id":"b"}', '{"state":{},"id":[]}'):
        (tmp_path / "a.json").write_text(payload)
        with pytest.raises(ValueError):
            load_scenarios(tmp_path)


def test_adapter_exception_never_enters_cli_errors(tmp_path):
    path = tmp_path / "trace.sqlite3"
    storage = SQLiteStorage(path)
    storage.save(make_trace())
    storage.close()
    adapter = MagicMock()
    adapter.decide.side_effect = RuntimeError("SECRET_SENTINEL")
    stream = io.StringIO()
    with (
        patch("tracefi.cli.load_adapter", return_value=adapter),
        contextlib.redirect_stderr(stream),
    ):
        assert main(["--db", str(path), "replay", "latest", "--adapter", "deterministic"]) == 2
    assert "RuntimeError" in stream.getvalue()
    assert "SECRET_SENTINEL" not in stream.getvalue()
    assert "Traceback" not in stream.getvalue()
