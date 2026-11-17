"""Loopback-only, read-only dashboard API. No CORS or mutation endpoints."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from tracefi.analysis import analyze
from tracefi.counterfactual import counterfactual, resolve_path
from tracefi.hashing import finite_number, load_json
from tracefi.registry import DASHBOARD_ADAPTERS, OFFLINE_ADAPTERS
from tracefi.reports import export_html
from tracefi.schema import decision_state
from tracefi.storage import SQLiteStorage

ASSETS = Path(__file__).parent / "web"
JSON = "application/json"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
)
EXPERIMENT_UNAVAILABLE = (
    b'{"error":"Experiment unavailable. Select a recorded numeric input and an adapter that '
    b'reproduces the original decision."}'
)
Response = tuple[int, bytes, str]


def experiment(trace: dict[str, Any], query: str) -> dict[str, Any]:
    """One counterfactual on a built-in offline adapter, over an input that adapter reads."""
    params = parse_qs(query)
    if set(params) != {"adapter", "feature", "value"} or any(
        len(values) != 1 for values in params.values()
    ):
        raise ValueError("Invalid experiment parameters")
    name, feature = params["adapter"][0], params["feature"][0]
    if name not in DASHBOARD_ADAPTERS:
        raise ValueError("Unsupported adapter")
    value = load_json(params["value"][0])
    if not finite_number(value):
        raise ValueError("Invalid financial input")
    adapter = OFFLINE_ADAPTERS[name]()
    state = decision_state(trace)
    inputs = adapter.inputs(state)
    if feature not in inputs:
        raise ValueError("Input is not read by the adapter")
    if not inputs[feature] and not resolve_path(state, feature)[0]:
        raise ValueError("Input was not recorded")
    return counterfactual(trace, adapter, feature, value)


def _api(db: str | Path, path: str, query: str) -> Response:
    parts = path.split("/")
    if path != "/api/traces" and (
        len(parts) not in (4, 5)
        or parts[2] != "traces"
        or len(parts) == 5
        and parts[4] not in ("export", "counterfactual")
    ):
        raise KeyError("Unknown route")
    storage = SQLiteStorage(db, read_only=True)
    try:
        if path == "/api/traces":
            return 200, json.dumps(storage.list(1000)).encode(), JSON
        trace = storage.get(parts[3])
    finally:
        storage.close()
    action = parts[4] if len(parts) == 5 else None
    if action == "export":
        return 200, export_html(trace).encode(), "text/html"
    if action == "counterfactual":
        try:
            result = experiment(trace, query)
        except (ValueError, TypeError):
            return 422, EXPERIMENT_UNAVAILABLE, JSON
        return 200, json.dumps(result).encode(), JSON
    return 200, json.dumps({"trace": trace, "analysis": analyze(trace)}).encode(), JSON


def _asset(path: str) -> Response:
    target = (ASSETS / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
    if not target.is_relative_to(ASSETS.resolve()) or not target.is_file():
        raise KeyError("Unknown asset")
    return 200, target.read_bytes(), mimetypes.guess_type(target)[0] or "application/octet-stream"


def serve(db: str | Path, port: int = 8765) -> None:
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    if not (ASSETS / "index.html").exists():
        raise ValueError(
            "Dashboard assets missing; run npm install and npm run build in dashboard/"
        )
    SQLiteStorage(db).close()
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    origins = {"http://" + host for host in hosts}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass  # User input and trace IDs never enter server access logs.

        def send(self, status: int, body: bytes, mime: str = JSON) -> None:
            self.send_response(status)
            charset = mime.startswith("text/") or mime == JSON
            self.send_header("Content-Type", mime + ("; charset=utf-8" if charset else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if len(self.headers.get_all("Host", [])) != 1 or self.headers.get("Host") not in hosts:
                self.send(403, b'{"error":"Invalid host"}')
                return
            origin = self.headers.get("Origin")
            if len(self.headers.get_all("Origin", [])) > 1 or origin and origin not in origins:
                self.send(403, b'{"error":"Invalid origin"}')
                return
            url = urlsplit(self.path)
            path = unquote(url.path)
            try:
                self.send(
                    *(_api(db, path, url.query) if path.startswith("/api/") else _asset(path))
                )
            except KeyError:
                self.send(404, b'{"error":"Not found"}')
            except Exception:
                self.send(500, b'{"error":"Unable to load verified trace"}')

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"TraceFi dashboard: http://127.0.0.1:{port} · read only", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
