"""SQLite trace collector with atomic writes and snapshot integrity checks."""
import json
import os
import sqlite3
from pathlib import Path
from agenttrace.hashing import canonicalize, state_hash


class IntegrityError(ValueError):
    pass


class SQLiteStorage:
    def __init__(self, path=".agenttrace/traces.sqlite3"):
        self.path = str(path)
        if self.path != ":memory:":
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Create private files from the outset; do not chmod existing shared files.
            fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
            os.close(fd)
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.execute("PRAGMA foreign_keys = ON")
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

    def save(self, trace):
        raw = canonicalize(trace).decode("utf-8")
        with self.connection:
            self.connection.execute("INSERT INTO traces VALUES (?,?,?,?,?,?,?,?)", (
                trace["trace_id"], trace["agent"]["name"], trace["agent"]["version"],
                trace["timestamp"], trace["context_hash"], trace["status"], raw, state_hash(trace)))
            for span in trace["spans"]:
                self.connection.execute("INSERT INTO spans VALUES (?,?,?,?,?,?,?)", (
                    span["id"], trace["trace_id"], span["parent_id"], span["type"],
                    span["start"], span["end"], canonicalize(span).decode()))
            for kind in ("context", "portfolio", "agent_configuration", "policy_configuration"):
                self.connection.execute("INSERT INTO artifacts VALUES (?,?,?,?,?)", (
                    trace["trace_id"] + ":" + kind, trace["trace_id"], kind,
                    state_hash(trace[kind]), canonicalize(trace[kind]).decode()))

    def get(self, trace_id="latest", verify=True):
        if trace_id == "latest":
            row = self.connection.execute("SELECT payload,hash,agent,version,timestamp,context_hash,status FROM traces ORDER BY timestamp DESC,id DESC LIMIT 1").fetchone()
        else:
            row = self.connection.execute("SELECT payload,hash,agent,version,timestamp,context_hash,status FROM traces WHERE id=?", (trace_id,)).fetchone()
        if not row:
            raise KeyError(f"Trace not found: {trace_id}")
        trace = json.loads(row[0])
        if verify:
            if trace.get("schema_version") != 1 or trace.get("canonical_version") != "agenttrace-json-v1":
                raise IntegrityError("Unsupported trace schema or canonicalization version")
            metadata = (trace["agent"]["name"], trace["agent"]["version"], trace["timestamp"], trace["context_hash"], trace["status"])
            if tuple(row[2:]) != metadata:
                raise IntegrityError("Indexed trace metadata integrity check failed")
            if trace_id != "latest" and trace["trace_id"] != trace_id:
                raise IntegrityError("Trace identifier integrity check failed")
            if state_hash(trace) != row[1]:
                raise IntegrityError("Trace payload integrity check failed")
            for field, hashed in (("context", "context_hash"), ("portfolio", "portfolio_hash"),
                                  ("policy_configuration", "policy_hash"), ("agent_configuration", "agent_config_hash")):
                if state_hash(trace[field]) != trace[hashed]:
                    raise IntegrityError(f"Snapshot integrity check failed: {field}")
            state = {key: trace[key] for key in ("context", "portfolio", "agent_configuration", "policy_configuration")}
            if state_hash(state) != trace["state_hash"]:
                raise IntegrityError("Combined state integrity check failed")
            spans = self.connection.execute("SELECT id,parent_id,type,start,end,payload FROM spans WHERE trace_id=?", (trace["trace_id"],)).fetchall()
            actual = {}
            for span_id, parent, kind, start, end, payload in spans:
                value = json.loads(payload)
                if (span_id, parent, kind, start, end) != tuple(value[key] for key in ("id", "parent_id", "type", "start", "end")):
                    raise IntegrityError("Indexed span metadata integrity check failed")
                actual[span_id] = value
            if actual != {span["id"]: span for span in trace["spans"]}:
                raise IntegrityError("Span integrity check failed")
            artifacts = self.connection.execute("SELECT id,type,hash,payload FROM artifacts WHERE trace_id=?", (trace["trace_id"],)).fetchall()
            if len(artifacts) != 4:
                raise IntegrityError("Missing snapshot artifacts")
            for artifact_id, kind, digest, payload in artifacts:
                if artifact_id != trace["trace_id"] + ":" + kind:
                    raise IntegrityError("Artifact identifier integrity check failed")
                value = json.loads(payload)
                if value != trace[kind] or state_hash(value) != digest:
                    raise IntegrityError(f"Artifact integrity check failed: {kind}")
        return trace

    def list(self, limit=50):
        rows = self.connection.execute("SELECT id,agent,version,timestamp,status FROM traces ORDER BY timestamp DESC,id DESC LIMIT ?", (limit,)).fetchall()
        for row in rows:
            self.get(row[0])
        return [dict(zip(("id", "agent", "version", "timestamp", "status"), row)) for row in rows]

    def close(self):
        self.connection.close()
