"""SQLite collector: atomic writes, bounded reads and semantic integrity checks."""

import os
import sqlite3
from pathlib import Path
from typing import Any

from tracefi.hashing import (
    SUPPORTED_CANONICAL_VERSIONS,
    canonicalize,
    load_json,
    snapshot,
    state_hash,
)

_STATE_HASHES = (
    ("context", "context_hash"),
    ("portfolio", "portfolio_hash"),
    ("policy_configuration", "policy_hash"),
    ("agent_configuration", "agent_config_hash"),
)


class IntegrityError(ValueError):
    pass


class SQLiteStorage:
    def __init__(
        self, path: str | Path = ".tracefi/traces.sqlite3", *, read_only: bool = False
    ) -> None:
        self.path = str(path)
        if read_only:
            if self.path == ":memory:":
                raise ValueError("An in-memory database cannot be opened read-only")
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            self.connection = sqlite3.connect(uri, uri=True)
        else:
            if self.path != ":memory:":
                target = Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
                os.close(fd)
            self.connection = sqlite3.connect(self.path)
        self.connection.execute("PRAGMA foreign_keys = ON")
        if not read_only:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS traces (
                    id TEXT PRIMARY KEY, agent TEXT NOT NULL, version TEXT,
                    timestamp TEXT NOT NULL, context_hash TEXT NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL, hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS spans (
                    id TEXT PRIMARY KEY, trace_id TEXT NOT NULL REFERENCES traces(id),
                    parent_id TEXT, type TEXT, start TEXT, end TEXT, payload TEXT
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id TEXT PRIMARY KEY, trace_id TEXT NOT NULL REFERENCES traces(id),
                    type TEXT, hash TEXT, payload TEXT
                );
                CREATE INDEX IF NOT EXISTS traces_timestamp ON traces(timestamp);
            """)

    def save(self, trace: dict[str, Any]) -> None:
        trace = snapshot(trace)
        raw = canonicalize(trace).decode("utf-8")
        with self.connection:
            self.connection.execute(
                "INSERT INTO traces VALUES (?,?,?,?,?,?,?,?)",
                (
                    trace["trace_id"],
                    trace["agent"]["name"],
                    trace["agent"]["version"],
                    trace["timestamp"],
                    trace["context_hash"],
                    trace["status"],
                    raw,
                    state_hash(trace),
                ),
            )
            for span in trace["spans"]:
                self.connection.execute(
                    "INSERT INTO spans VALUES (?,?,?,?,?,?,?)",
                    (
                        span["id"],
                        trace["trace_id"],
                        span["parent_id"],
                        span["type"],
                        span["start"],
                        span["end"],
                        canonicalize(span).decode(),
                    ),
                )
            for kind, _ in _STATE_HASHES:
                self.connection.execute(
                    "INSERT INTO artifacts VALUES (?,?,?,?,?)",
                    (
                        trace["trace_id"] + ":" + kind,
                        trace["trace_id"],
                        kind,
                        state_hash(trace[kind]),
                        canonicalize(trace[kind]).decode(),
                    ),
                )

    def get(self, trace_id: str = "latest", verify: bool = True) -> dict[str, Any]:
        columns = "id,payload,hash,agent,version,timestamp,context_hash,status"
        if trace_id == "latest":
            row = self.connection.execute(
                f"SELECT {columns} FROM traces ORDER BY timestamp DESC,id DESC LIMIT 1"
            ).fetchone()
        else:
            row = self.connection.execute(
                f"SELECT {columns} FROM traces WHERE id=?", (trace_id,)
            ).fetchone()
        if not row:
            raise KeyError("Trace not found")
        try:
            trace = load_json(row[1])
            if not isinstance(trace, dict):
                raise IntegrityError("Trace payload is not an object")
            if verify:
                self._verify(trace, row)
            return trace
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            raise IntegrityError("Trace integrity check failed") from None

    def _verify(self, trace: dict[str, Any], row: tuple[Any, ...]) -> None:
        if (
            trace.get("schema_version") != 1
            or isinstance(trace.get("schema_version"), bool)
            or trace.get("canonical_version") not in SUPPORTED_CANONICAL_VERSIONS
        ):
            raise IntegrityError("Unsupported trace format")
        if trace["trace_id"] != row[0] or state_hash(trace) != row[2]:
            raise IntegrityError("Trace payload or identifier mismatch")
        metadata = (
            trace["agent"]["name"],
            trace["agent"]["version"],
            trace["timestamp"],
            trace["context_hash"],
            trace["status"],
        )
        if tuple(row[3:]) != metadata:
            raise IntegrityError("Indexed trace metadata mismatch")
        for field, hashed in _STATE_HASHES:
            if not isinstance(trace[field], dict) or state_hash(trace[field]) != trace[hashed]:
                raise IntegrityError("Snapshot mismatch")
        state = {key: trace[key] for key, _ in _STATE_HASHES}
        if state_hash(state) != trace["state_hash"]:
            raise IntegrityError("Combined state mismatch")
        spans = self.connection.execute(
            "SELECT id,parent_id,type,start,end,payload FROM spans WHERE trace_id=?",
            (trace["trace_id"],),
        ).fetchall()
        actual = {}
        for span_id, parent, kind, start, end, payload in spans:
            value = load_json(payload)
            if (span_id, parent, kind, start, end) != tuple(
                value[key] for key in ("id", "parent_id", "type", "start", "end")
            ):
                raise IntegrityError("Indexed span metadata mismatch")
            actual[span_id] = value
        expected = {span["id"]: span for span in trace["spans"]}
        if len(expected) != len(trace["spans"]) or canonicalize(actual) != canonicalize(expected):
            raise IntegrityError("Span mismatch")
        artifacts = self.connection.execute(
            "SELECT id,type,hash,payload FROM artifacts WHERE trace_id=?", (trace["trace_id"],)
        ).fetchall()
        if len(artifacts) != 4:
            raise IntegrityError("Missing snapshot artifacts")
        for artifact_id, kind, digest, payload in artifacts:
            if kind not in state or artifact_id != trace["trace_id"] + ":" + kind:
                raise IntegrityError("Artifact identifier mismatch")
            value = load_json(payload)
            if state_hash(value) != digest or digest != state_hash(trace[kind]):
                raise IntegrityError("Artifact mismatch")

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("List limit must be an integer between 1 and 1000")
        ids = self.connection.execute(
            "SELECT id FROM traces ORDER BY timestamp DESC,id DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for (trace_id,) in ids:
            trace = self.get(trace_id)
            result.append(
                {
                    "id": trace["trace_id"],
                    "agent": trace["agent"]["name"],
                    "version": trace["agent"]["version"],
                    "timestamp": trace["timestamp"],
                    "status": trace["status"],
                }
            )
        return result

    def close(self) -> None:
        self.connection.close()
