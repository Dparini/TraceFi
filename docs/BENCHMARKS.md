# Local performance measurements

Run from an installed checkout:

```bash
python benchmarks/run.py --repetitions 100 --sizes 1000 10000 \
  --output /tmp/tracefi-benchmark-new.json
```

Use a new output filename. No network, financial API or special service is used.
The script measures with `perf_counter_ns`, performs five warmups, collects 100
repetitions per latency operation and reports median, 25th/75th percentiles and
min/max. Storage density is measured in one freshly created SQLite DB at exactly
1,000 and 10,000 traces, committed individually. It includes trace, span and artifact
payloads and indexes; it does not include a retained journal or WAL.

The fixture is a synthetic USDC decision with six capture spans and ten retrieval
labels, approximately 4,028 serialized bytes. Density fixtures get fresh trace/span
UUIDs. SQLite uses DELETE journal mode and synchronous=2 (FULL). Filesystem caches
are warm. This is a local experiment, not a throughput or durability guarantee.

## Measured 2026-10-13

Python 3.14.6, macOS 26.5.2 arm64, Apple M1, eight logical CPUs, 8 GiB RAM.
[Raw report with methodology and variability](assets/benchmarks-v0.1.0.json).
All following values are measured medians; parentheses contain the interquartile range.

- Capture/finalization without database: **4.234 ms** (2.714–6.425).
- SQLite write including preparation and committed transaction: **6.104 ms** (3.990–9.807).
- Unverified read including strict JSON parsing: **0.900 ms** (0.872–1.224).
- Verified read including all integrity checks: **2.822 ms** (2.686–3.239).
- Paired verification increment: **2.537 ms** (1.917–4.943).
- Full matching replay comparison: **0.349 ms** (0.333–0.355).
- JSON export serialization: **0.025 ms** (0.025–0.025).
- Standalone HTML rendering: **4.519 ms** (4.336–5.356).
- Storage at 1,000 traces: **8,925,184 bytes**, approximately 8925 bytes per trace.
- Storage at 10,000 traces: **89,079,808 bytes**, approximately 8908 bytes per trace.

Export measurements exclude output-file I/O. The SDK capture measurement excludes
SQLite via a discard sink but includes redaction, hashing and a deterministic
proposal. The write maximum was 19.443 ms: medians should not be read as tail-latency
promises. Other workloads, hardware, schema evolution, contention and cold caches
can produce substantially different results. Benchmarks have no release gate on
an arbitrary latency number and do not establish financial correctness.

Local mutation testing ran concurrently during this final run; CPU/load isolation
was not imposed. The raw report includes hashes of the measured core source tree
and benchmark script so the measurement snapshot can be identified.
