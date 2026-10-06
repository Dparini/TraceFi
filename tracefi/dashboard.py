"""Loopback-only, read-only dashboard API. No CORS or mutation endpoints."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from tracefi.analysis import analyze
from tracefi.cli.render import export_html
from tracefi.counterfactual import counterfactual
from tracefi.hashing import load_json
from tracefi.models import load_adapter
from tracefi.models.deterministic import finite_number
from tracefi.storage import SQLiteStorage

COUNTERFACTUAL_FEATURES = {
    "context.apy",
    "context.liquidity",
    "context.price",
    "context.oracle_age_seconds",
}


def serve(db: str | Path, port: int = 8765) -> None:
    assets = Path(__file__).parent / "web"
    if not (assets / "index.html").exists():
        raise ValueError(
            "Dashboard assets missing; run npm install and npm run build in dashboard/"
        )
    # Initialize schema before accepting concurrent read-only requests.
    SQLiteStorage(db).close()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass  # User input and trace IDs never enter server access logs.

        def send(self, status: int, body: bytes, mime: str = "application/json") -> None:
            self.send_response(status)
            self.send_header(
                "Content-Type",
                mime
                + (
                    "; charset=utf-8"
                    if mime.startswith("text/") or mime == "application/json"
                    else ""
                ),
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in allowed:
                self.send(403, b'{"error":"Invalid host"}')
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in allowed}:
                self.send(403, b'{"error":"Invalid origin"}')
                return
            path = unquote(urlsplit(self.path).path)
            storage = None
            try:
                if path.startswith("/api/"):
                    storage = SQLiteStorage(db, read_only=True)
                    if path == "/api/traces":
                        rows = []
                        for row in storage.list(1000):
                            trace = storage.get(row["id"])
                            proposal = trace.get("proposal") or {}
                            rows.append(
                                {
                                    **row,
                                    "action": proposal.get("action"),
                                    "amount": proposal.get("amount"),
                                    "asset": proposal.get("asset"),
                                }
                            )
                        body = json.dumps(rows).encode()
                    elif path.startswith("/api/traces/"):
                        parts = path.split("/")
                        if (
                            len(parts) not in (4, 5)
                            or len(parts) == 5
                            and parts[4] not in ("export", "counterfactual")
                        ):
                            raise KeyError("Unknown route")
                        trace = storage.get(parts[3])
                        if len(parts) == 5 and parts[4] == "export":
                            self.send(200, export_html(trace).encode(), "text/html")
                            return
                        if len(parts) == 5 and parts[4] == "counterfactual":
                            try:
                                params = parse_qs(urlsplit(self.path).query)
                                if set(params) != {"adapter", "feature", "value"} or any(
                                    len(values) != 1 for values in params.values()
                                ):
                                    raise ValueError("Invalid experiment parameters")
                                if params["adapter"][0] != "deterministic":
                                    raise ValueError("Unsupported adapter")
                                feature = params["feature"][0]
                                value = load_json(params["value"][0])
                                if feature not in COUNTERFACTUAL_FEATURES or not finite_number(
                                    value
                                ):
                                    raise ValueError("Invalid financial input")
                                if feature.split(".")[1] not in trace["context"]:
                                    raise ValueError("Input was not recorded")
                                result = counterfactual(
                                    trace, load_adapter("deterministic"), feature, value
                                )
                                result["limitations"] = (
                                    "One-variable experiment on the synthetic deterministic adapter. No transaction, policy recheck or financial outcome is simulated."
                                )
                            except (ValueError, TypeError):
                                self.send(
                                    422,
                                    b'{"error":"Experiment unavailable. Select a recorded numeric input and an adapter that reproduces the original decision."}',
                                )
                                return
                            self.send(200, json.dumps(result).encode())
                            return
                        body = json.dumps({"trace": trace, "analysis": analyze(trace)}).encode()
                    else:
                        raise KeyError("Unknown route")
                    self.send(200, body)
                else:
                    target = (
                        assets / ("index.html" if path == "/" else path.lstrip("/"))
                    ).resolve()
                    if not target.is_relative_to(assets.resolve()) or not target.is_file():
                        raise KeyError("Unknown asset")
                    self.send(
                        200,
                        target.read_bytes(),
                        mimetypes.guess_type(target)[0] or "application/octet-stream",
                    )
            except KeyError:
                self.send(404, b'{"error":"Not found"}')
            except Exception:
                self.send(500, b'{"error":"Unable to load verified trace"}')
            finally:
                if storage:
                    storage.close()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"TraceFi dashboard: http://127.0.0.1:{port} · read only", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
