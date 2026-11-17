"""End-to-end checks for the installed CLI and loopback dashboard contract."""

import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from tests.helpers import make_trace
from tracefi import TraceFi
from tracefi.dashboard import experiment
from tracefi.demo import run_case_study
from tracefi.models.deterministic import DeterministicAgent
from tracefi.schema import decision_state


def lending_trace():
    with TraceFi(db=":memory:") as collector:
        return collector.storage.get(run_case_study(collector)["trace_id"])


def query(adapter, feature, value):
    return urlencode({"adapter": adapter, "feature": feature, "value": value})


def test_experiment_may_add_an_omitted_optional_input():
    result = experiment(
        lending_trace(),
        query("lending-v1", "context.markets.protocol_b.liquidity_trend_24h", "-0.41"),
    )
    assert result["decision_changed"]


def deterministic_trace_without_apy():
    with TraceFi(db=":memory:") as collector:
        with collector.decision("rule-agent", "1", portfolio={"USDC": 100_000}) as trace:
            trace.capture_context({"liquidity": 21_000_000, "price": 1, "oracle_age_seconds": 20})
            trace.capture_decision(DeterministicAgent().decide(trace.state()))
        return collector.storage.get(trace.trace_id)


def test_unrecorded_required_input_would_otherwise_change_the_decision():
    trace = deterministic_trace_without_apy()
    trace["context"]["apy"] = 0.067
    assert DeterministicAgent().decide(decision_state(trace))["action"] == "SUPPLY"


@pytest.mark.parametrize(
    "recorded,adapter,feature",
    [
        (lending_trace, "lending-v1", "context.markets.protocol_c.supply_apy"),
        (lending_trace, "lending-v1", "context.apy"),
        (lending_trace, "deterministic", "context.markets.protocol_b.supply_apy"),
        (make_trace, "lending-v1", "context.markets.protocol_b.liquidity_trend_24h"),
        (make_trace, "deterministic", "context.unused"),
        (make_trace, "agent-v1", "context.liquidity"),
        (deterministic_trace_without_apy, "deterministic", "context.apy"),
    ],
)
def test_experiment_refuses_inputs_the_adapter_does_not_read_or_were_not_recorded(
    recorded, adapter, feature
):
    with pytest.raises(ValueError):
        experiment(recorded(), query(adapter, feature, "1"))


class DashboardTests(unittest.TestCase):
    def test_local_api_and_origin_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "traces.sqlite3")
            subprocess.run(
                [sys.executable, "-m", "tracefi", "--db", db, "demo"],
                check=True,
                capture_output=True,
            )
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            process = subprocess.Popen(
                [sys.executable, "-m", "tracefi", "--db", db, "serve", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            root = f"http://127.0.0.1:{port}"
            try:
                for _ in range(100):
                    try:
                        with urlopen(root + "/api/traces", timeout=1) as response:
                            traces = json.load(response)
                        break
                    except URLError:
                        if process.poll() is not None:
                            self.fail("Dashboard server exited during startup")
                        time.sleep(0.05)
                else:
                    self.fail("Dashboard did not start")
                self.assertEqual(len(traces), 2)
                trace_id = traces[0]["id"]
                with urlopen(root + "/api/traces/" + trace_id) as response:
                    detail = json.load(response)
                self.assertEqual(detail["trace"]["status"], "rejected")
                query = urlencode(
                    {
                        "adapter": "deterministic",
                        "feature": "context.liquidity",
                        "value": "10000000",
                    }
                )
                with urlopen(
                    root + "/api/traces/" + trace_id + "/counterfactual?" + query
                ) as response:
                    experiment = json.load(response)
                self.assertTrue(experiment["decision_changed"])
                self.assertEqual(experiment["original"]["action"], "SUPPLY")
                self.assertEqual(experiment["counterfactual"]["action"], "HOLD")
                query = urlencode(
                    {
                        "adapter": "untrusted_module:factory",
                        "feature": "context.liquidity",
                        "value": "10000000",
                    }
                )
                with self.assertRaises(HTTPError) as error:
                    urlopen(root + "/api/traces/" + trace_id + "/counterfactual?" + query)
                self.assertEqual(error.exception.code, 422)
                error.exception.close()
                query = urlencode(
                    {"adapter": "deterministic", "feature": "context.liquidity", "value": "NaN"}
                )
                with self.assertRaises(HTTPError) as error:
                    urlopen(root + "/api/traces/" + trace_id + "/counterfactual?" + query)
                self.assertEqual(error.exception.code, 422)
                error.exception.close()
                with urlopen(root + "/api/traces/" + trace_id) as response:
                    self.assertEqual(json.load(response)["trace"], detail["trace"])
                with urlopen(root + "/api/traces/" + trace_id + "/export") as response:
                    self.assertIn(b"TRACEFI POST-MORTEM", response.read())
                with urlopen(root) as response:
                    body = response.read().decode()
                    self.assertIn('id="root"', body)
                    self.assertIn(
                        "frame-ancestors 'none'", response.headers["Content-Security-Policy"]
                    )
                for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}):
                    with self.assertRaises(HTTPError) as error:
                        urlopen(Request(root + "/api/traces", headers=headers))
                    self.assertEqual(error.exception.code, 403)
                    error.exception.close()
                for headers in (
                    (f"Host: 127.0.0.1:{port}", f"Host: localhost:{port}"),
                    (
                        f"Host: 127.0.0.1:{port}",
                        f"Origin: http://127.0.0.1:{port}",
                        "Origin: https://evil.example",
                    ),
                ):
                    with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
                        request = (
                            "GET /api/traces HTTP/1.1\r\n"
                            + "\r\n".join(headers)
                            + "\r\nConnection: close\r\n\r\n"
                        )
                        client.sendall(request.encode())
                        self.assertIn(b"403", client.recv(1024).split(b"\r\n")[0])
                with self.assertRaises(HTTPError) as error:
                    urlopen(root + "/../pyproject.toml")
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
                with self.assertRaises(HTTPError) as error:
                    urlopen(Request(root + "/api/traces", method="POST", data=b"{}"))
                self.assertEqual(error.exception.code, 501)
                error.exception.close()
            finally:
                process.terminate()
                process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
