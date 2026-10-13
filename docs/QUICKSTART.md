# Installation and CLI

Use Python 3.10+ and the repository checkout. From a tagged GitHub source archive,
create a virtual environment and run `python -m pip install .`; a release wheel
can be installed directly with `python -m pip install /path/tracefi-0.1.0-py3-none-any.whl`.
No PyPI package ownership/publication is asserted. Node is needed only to rebuild
the dashboard, not to run the installed one.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
tracefi --help
tracefi demo --case-study
tracefi list
tracefi show latest
tracefi analyze latest
tracefi replay latest --adapter lending-v1
tracefi export latest --format html --output investigation.html
tracefi serve --port 8765
```

Open `http://127.0.0.1:8765`. Stop with Ctrl+C. The server creates an empty DB on
first startup; inspection commands on a missing DB fail without creating it.
An empty existing DB lists zero traces; `show latest` reports that no trace exists.

The global DB option goes **before** the command:
`tracefi --db /path/investigation.sqlite3 demo --case-study`.
The default is `.tracefi/traces.sqlite3`. New DB files have mode 0600 on POSIX;
existing permissions are not tightened automatically. Final-path DB symlinks are refused.
Keep parent directories trusted. There is no schema migration that rewrites old traces.

## Workflow commands

- `demo`: original two-decision offline demo; `--case-study`: full lending investigation.
- `list --limit 50`, `show TRACE_ID`, `analyze TRACE_ID --json`.
- `replay TRACE_ID --adapter NAME --json`: explicit trusted adapter required.
- `diff TRACE_A TRACE_B --json`: structural input/proposal/policy changes.
- `counterfactual TRACE_ID --adapter NAME --feature PATH --value JSON`.
  Use `--low NUMBER --high NUMBER` instead of `--value` for a numerical bracket.
- `why-change TRACE_A TRACE_B --adapter NAME`: conditional single-change tests.
- `eval --baseline NAME --candidate NAME --dataset tracefi/datasets/`.
  `--dataset lending` selects the packaged lending fixtures; omitting the option
  selects the 30 packaged generic scenarios.
- `run --dataset tracefi/datasets/ --adapter deterministic`: capture explicitly injected
  generic test faults. This runner uses generic synthetic execution, not the richer
  lending simulator; use `demo --case-study` for that investigation.
- `export TRACE_ID --format json|html --output NEW_FILE`: atomic private output,
  no overwriting, including symlinks. Omit `--output` to print to stdout.
- `serve --port 8765`: loopback-only dashboard, no remote backend.

All trace arguments default to `latest` where supported. `latest` is ordered by
recorded timestamp and ID; unreliable host clocks can change apparent ordering.
Use explicit IDs for an investigation. `list` summarizes at most 1,000 verified
traces, including proposals; it does not count the entire database.

## Exit codes and errors

0: successful operation or matching replay.
1: replay divergence, or configured eval regression with `--fail-on-regression`.
2: invalid input, missing trace/DB/dependency, integrity failure or adapter error.

`--help` works on every subcommand. Counterfactual validation returns static,
actionable diagnostics; adapter exceptions are sanitized and never echo their
messages. Invalid command-line arguments are not echoed because they may contain
credentials. Trusted custom adapters can themselves print sensitive data or
perform side effects; TraceFi cannot sandbox arbitrary Python code.

See [replay](REPLAY.md), [counterfactuals](COUNTERFACTUALS.md),
[regression gates](REGRESSION_TESTING.md) and the [API contract](API.md).
