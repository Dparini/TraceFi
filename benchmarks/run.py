"""Reproducible local latency/density measurements, not performance guarantees."""

import argparse
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from time import perf_counter_ns
from uuid import uuid4

import tracefi
from tracefi import TraceFi
from tracefi.analysis import replay
from tracefi.cli.render import export_html
from tracefi.models import decision_state, load_adapter
from tracefi.security.files import write_export
from tracefi.storage import SQLiteStorage


class DiscardStorage:
    def save(self, trace):
        self.last = trace

    def close(self):
        pass


def capture(collector):
    with collector.decision(
        "benchmark",
        "1",
        portfolio={"USDC": 100000},
        agent_config={"version": "1"},
        policy_config={"max_exposure": 0.35},
    ) as trace:
        trace.capture_context(
            {"apy": 0.067, "liquidity": 21_000_000, "price": 1, "oracle_age_seconds": 20}
        )
        trace.capture_retrieval(
            {
                "included_features": ["apy", "liquidity", "price"],
                "documents": [f"local-record-{i}" for i in range(10)],
            }
        )
        trace.capture_decision(load_adapter("deterministic").decide(decision_state(trace.record)))
        trace.capture_policy({"approved": True})
        trace.capture_simulation({"success": True, "mode": "synthetic"})
        trace.capture_execution({"status": "success", "mode": "synthetic"})


def fresh(record):
    result = deepcopy(record)
    result["trace_id"] = "tr_" + uuid4().hex
    for span in result["spans"]:
        span["id"] = "sp_" + uuid4().hex
    return result


def summary(values):
    quartiles = statistics.quantiles(values, n=4, method="inclusive")
    return {
        "samples": len(values),
        "median_ms": statistics.median(values),
        "p25_ms": quartiles[0],
        "p75_ms": quartiles[2],
        "min_ms": min(values),
        "max_ms": max(values),
    }


def measured(function, repetitions):
    values = []
    for _ in range(5):
        function()
    for _ in range(repetitions):
        start = perf_counter_ns()
        function()
        values.append((perf_counter_ns() - start) / 1e6)
    return summary(values)


def hardware():
    result = {"logical_cpus": os.cpu_count(), "machine": platform.machine()}
    if sys.platform == "darwin":
        for key, field in (
            ("machdep.cpu.brand_string", "processor"),
            ("hw.memsize", "memory_bytes"),
        ):
            probe = subprocess.run(
                ["sysctl", "-n", key], capture_output=True, text=True, check=False
            )
            if probe.returncode == 0:
                result[field] = probe.stdout.strip()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, default=100)
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 10 or any(size < 1 for size in args.sizes):
        parser.error("Use at least 10 repetitions and positive storage sizes")
    discard = DiscardStorage()
    collector = TraceFi(storage=discard)
    capture(collector)
    fixture = discard.last
    with tempfile.TemporaryDirectory(prefix="tracefi-benchmark-") as directory:
        db = SQLiteStorage(Path(directory) / "latency.sqlite3")
        try:
            db.save(fixture)
            adapter = load_adapter("deterministic")
            assert replay(fixture, adapter)["equal"]
            latencies = {
                "capture_without_database": measured(lambda: capture(collector), args.repetitions),
                "sqlite_write": measured(lambda: db.save(fresh(fixture)), args.repetitions),
                "sqlite_read_unverified": measured(
                    lambda: db.get(fixture["trace_id"], verify=False), args.repetitions
                ),
                "sqlite_read_verified": measured(
                    lambda: db.get(fixture["trace_id"]), args.repetitions
                ),
                "replay_comparison": measured(lambda: replay(fixture, adapter), args.repetitions),
                "json_export_serialization": measured(
                    lambda: json.dumps(fixture, ensure_ascii=False), args.repetitions
                ),
                "html_export_rendering": measured(lambda: export_html(fixture), args.repetitions),
            }
            paired = []
            for index in range(args.repetitions):
                timings = {}
                for verified in (False, True) if index % 2 else (True, False):
                    start = perf_counter_ns()
                    db.get(fixture["trace_id"], verify=verified)
                    timings[verified] = (perf_counter_ns() - start) / 1e6
                paired.append(timings[True] - timings[False])
            latencies["verification_paired_increment"] = summary(paired)
        finally:
            db.close()
        density = SQLiteStorage(Path(directory) / "density.sqlite3")
        sizes = []
        try:
            journal_mode = density.connection.execute("PRAGMA journal_mode").fetchone()[0]
            synchronous = density.connection.execute("PRAGMA synchronous").fetchone()[0]
            for index in range(1, max(args.sizes) + 1):
                density.save(fresh(fixture))
                if index in args.sizes:
                    size = Path(density.path).stat().st_size
                    sizes.append(
                        {"traces": index, "database_bytes": size, "bytes_per_trace": size / index}
                    )
        finally:
            density.close()
    package_root = Path(tracefi.__file__).parent
    source_digest = hashlib.sha256()
    for path in sorted(package_root.rglob("*.py")):
        source_digest.update(path.relative_to(package_root).as_posix().encode())
        source_digest.update(path.read_bytes())
    report = {
        "core_source_sha256": source_digest.hexdigest(),
        "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": sys.version,
        "os": platform.platform(),
        "hardware": hardware(),
        "methodology": {
            "clock": "perf_counter_ns",
            "warmups": 5,
            "repetitions": args.repetitions,
            "sqlite_journal_mode": journal_mode,
            "sqlite_synchronous": synchronous,
            "dataset": "Synthetic USDC decision, 6 capture spans, 10 retrieval labels; same payload with fresh trace/span UUIDs.",
            "serialized_trace_bytes": len(json.dumps(fixture).encode()),
            "write_scope": "Fresh UUID/deepcopy preparation plus canonicalization, hashing and committed SQLite transaction; no network.",
            "read_scope": "Strict JSON parsing included in both; verified reads additionally verify all stored snapshots/spans/artifacts.",
            "storage_scope": "One database populated sequentially with an individual transaction per trace; no WAL, compression or retained journal.",
            "caveat": "Warm local filesystem caches. Export excludes disk output. Machine-specific measurements, not guarantees.",
        },
        "latencies": latencies,
        "storage": sizes,
    }
    write_export(args.output, json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
