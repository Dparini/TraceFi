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
