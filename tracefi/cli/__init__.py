"""CLI: all commands operate locally unless an Ollama adapter is selected."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NoReturn

from tracefi import TraceFi, __version__
from tracefi.analysis import analyze, diff
from tracefi.counterfactual import CounterfactualError, boundary, counterfactual, replay, why_change
from tracefi.dashboard import serve
from tracefi.demo import run_case_study, run_demo, run_scenarios
from tracefi.evals import compare, load_scenarios, regression_directions
from tracefi.hashing import load_json
from tracefi.registry import (
    ADAPTERS,
    DEFAULT_DATASET,
    METRICS_MODELS,
    dataset_path,
    load_adapter,
)
from tracefi.reports import (
    counterfactual_report,
    diff_report,
    export_html,
    postmortem,
    regression_report,
    replay_report,
    why_change_report,
)
from tracefi.security.files import write_export
from tracefi.storage import DEFAULT_DB, IntegrityError, SQLiteStorage

Command = Callable[[argparse.Namespace], int]
ADAPTER_HELP = "Explicit adapter: " + ", ".join(ADAPTERS) + " or module:factory"


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "tracefi: invalid arguments; use --help for usage.\n")


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def _report(args: argparse.Namespace, report: Any, render: Callable[[Any], str]) -> None:
    emit(report) if args.json else print(render(report))


@contextmanager
def _reading(args: argparse.Namespace) -> Iterator[SQLiteStorage]:
    storage = SQLiteStorage(args.db, read_only=True)
    try:
        yield storage
    finally:
        storage.close()


def _list(args: argparse.Namespace) -> int:
    with _reading(args) as storage:
        emit(storage.list(args.limit))
    return 0


def _show(args: argparse.Namespace) -> int:
    with _reading(args) as storage:
        emit(storage.get(args.trace))
    return 0


def _analyze(args: argparse.Namespace) -> int:
    with _reading(args) as storage:
        trace = storage.get(args.trace)
    emit(analyze(trace)) if args.json else print(postmortem(trace))
    return 0


def _replay(args: argparse.Namespace) -> int:
    with _reading(args) as storage:
        trace = storage.get(args.trace)
    report = replay(trace, load_adapter(args.adapter))
    _report(args, report, replay_report)
    return 0 if report["equal"] else 1


def _counterfactual(args: argparse.Namespace) -> int:
    with _reading(args) as storage:
        trace = storage.get(args.trace)
    adapter = load_adapter(args.adapter)
    if args.value is not None:
        if args.low is not None or args.high is not None:
            raise ValueError("Use --value or --low/--high")
        report = counterfactual(trace, adapter, args.feature, load_json(args.value))
    elif args.low is not None and args.high is not None:
        report = boundary(trace, adapter, args.feature, args.low, args.high)
    else:
        raise ValueError("Provide --value or both --low and --high")
    _report(args, report, counterfactual_report)
    return 0


def _export(args: argparse.Namespace) -> int:
    with _reading(args) as storage:
        trace = storage.get(args.trace)
    value = (
        export_html(trace)
        if args.format == "html"
        else json.dumps(trace, indent=2, ensure_ascii=False)
    )
    if args.output:
        write_export(args.output, value)
        print(f"Exported {args.output}")
    else:
        print(value)
    return 0


def _diff(args: argparse.Namespace) -> int:
    with _reading(args) as storage:
        a, b = storage.get(args.trace_a), storage.get(args.trace_b)
    _report(args, diff(a, b), diff_report)
    return 0


def _why_change(args: argparse.Namespace) -> int:
    with _reading(args) as storage:
        a, b = storage.get(args.trace_a), storage.get(args.trace_b)
    _report(args, why_change(a, b, load_adapter(args.adapter)), why_change_report)
    return 0


def _eval(args: argparse.Namespace) -> int:
    report = compare(
        load_adapter(args.baseline),
        load_adapter(args.candidate),
        load_scenarios(args.dataset),
        regression_metrics=args.regression_metric,
        metrics_models=METRICS_MODELS,
    )
    _report(args, report, regression_report)
    return 1 if args.fail_on_regression and report["regressions"] else 0


def _run(args: argparse.Namespace) -> int:
    with TraceFi(db=args.db) as collector:
        adapter = load_adapter(args.adapter)
        ids = run_scenarios(collector, adapter, args.adapter, load_scenarios(args.dataset))
        emit({"traces": ids, "synthetic": True})
    return 0


def _demo(args: argparse.Namespace) -> int:
    with TraceFi(db=args.db) as collector:
        if args.case_study:
            result = run_case_study(collector)
            print("TRACEFI LENDING CASE STUDY · fully synthetic · no funds")
            print(postmortem(collector.storage.get(result["trace_id"])))
            print(counterfactual_report(result["counterfactual"]))
            return 0
        result = run_demo(collector)
        print("TRACEFI DEMO · offline synthetic decisions")
        for trace_id in result["trace_ids"]:
            trace = collector.storage.get(trace_id)
            print(
                trace_id,
                trace["proposal"]["action"],
                trace["proposal"]["amount"],
                trace["status"].upper(),
            )
        print("\n" + postmortem(collector.storage.get(result["trace_ids"][-1])))
        print("\n" + why_change_report(result["why_change"]))
    return 0


def _serve(args: argparse.Namespace) -> int:
    serve(args.db, args.port)
    return 0


def parser() -> argparse.ArgumentParser:
    root = SafeArgumentParser(
        prog="tracefi",
        description="Financial decision provenance → failure attribution → counterfactual debugging",
    )
    root.add_argument("--db", default=DEFAULT_DB, help="Local SQLite path")
    root.add_argument("--version", action="version", version=f"TraceFi {__version__}")
    commands = root.add_subparsers(dest="command", required=True)

    def command(name: str, handler: Command, help: str | None = None) -> argparse.ArgumentParser:
        sub = (
            commands.add_parser(name)
            if help is None
            else commands.add_parser(name, help=help, description=help)
        )
        sub.set_defaults(handler=handler)
        return sub

    def paired(name: str, handler: Command) -> argparse.ArgumentParser:
        sub = command(name, handler)
        sub.add_argument("trace_a")
        sub.add_argument("trace_b")
        sub.add_argument("--json", action="store_true")
        return sub

    def traced(name: str, handler: Command, help: str) -> argparse.ArgumentParser:
        sub = command(name, handler, help)
        sub.add_argument("trace", nargs="?", default="latest", help="Trace ID (default latest)")
        return sub

    listing = command("list", _list, "List recent traces")
    listing.add_argument(
        "--limit", type=int, default=50, help="1–1000 verified traces (default 50)"
    )
    traced("show", _show, "Show a verified trace")
    traced("analyze", _analyze, "Evidence-based failure findings").add_argument(
        "--json", action="store_true"
    )
    replaying = traced("replay", _replay, "Compare one explicit adapter replay")
    replaying.add_argument("--json", action="store_true")
    replaying.add_argument("--adapter", required=True, help=ADAPTER_HELP)
    export = traced("export", _export, "Create a private non-overwriting JSON/HTML report")
    export.add_argument("--format", choices=("json", "html"), default="json")
    export.add_argument("--output", type=Path)
    experiment = traced(
        "counterfactual", _counterfactual, "Test one input or a conditional numerical bracket"
    )
    experiment.add_argument("--json", action="store_true")
    experiment.add_argument("--adapter", required=True, help=ADAPTER_HELP)
    experiment.add_argument("--feature", required=True, help="e.g. context.liquidity")
    experiment.add_argument("--value", help="JSON value for a single intervention")
    experiment.add_argument("--low", type=float)
    experiment.add_argument("--high", type=float)
    paired("diff", _diff)
    paired("why-change", _why_change).add_argument("--adapter", required=True, help=ADAPTER_HELP)
    evaluation = command("eval", _eval)
    evaluation.add_argument("--json", action="store_true")
    evaluation.add_argument("--baseline", required=True)
    evaluation.add_argument("--candidate", required=True)
    evaluation.add_argument("--dataset", type=dataset_path, default=DEFAULT_DATASET)
    evaluation.add_argument("--fail-on-regression", action="store_true")
    evaluation.add_argument(
        "--regression-metric",
        action="append",
        choices=tuple(regression_directions(METRICS_MODELS)),
        help="Repeat to select CI regression gates",
    )
    runner = command("run", _run, "Capture offline scenarios with injected test faults")
    runner.add_argument("--adapter", default="deterministic")
    runner.add_argument("--dataset", type=dataset_path, default=DEFAULT_DATASET)
    command("demo", _demo, "Offline synthetic trace demo").add_argument(
        "--case-study", action="store_true", help="Run the two-market lending investigation"
    )
    command("serve", _serve, "Local read-only timeline dashboard").add_argument(
        "--port", type=int, default=8765, help="Loopback port, 1–65535 (default 8765)"
    )
    return root


_HINTS = {
    FileNotFoundError: "Database or input missing; run tracefi demo to create traces.",
    FileExistsError: "Output exists; choose a new filename. Existing files are never overwritten.",
    IntegrityError: "Trace integrity check failed; preserve the database and investigate corruption.",
    KeyError: "Trace not found; inspect tracefi list for available identifiers.",
    ModuleNotFoundError: "Adapter dependency unavailable; install the trusted adapter dependencies.",
}


def _hint(exc: Exception, command: str) -> str:
    if isinstance(exc, CounterfactualError):
        return f"{exc.code}: {exc}"
    if isinstance(exc, FileNotFoundError) and command == "export":
        return (
            "Database or output directory missing; use an existing trace and destination directory."
        )
    return _HINTS.get(type(exc), "Operation failed; check inputs, adapter and trace integrity.")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:
        # Never echo adapter/tool exception messages that may contain credentials.
        print(f"tracefi: {type(exc).__name__}: {_hint(exc, args.command)}", file=sys.stderr)
        return 2
