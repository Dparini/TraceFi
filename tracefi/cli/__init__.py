"""CLI: all commands operate locally unless an Ollama adapter is selected."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, NoReturn

from tracefi import TraceFi
from tracefi.analysis import analyze, diff, replay
from tracefi.cli.render import (
    counterfactual_report,
    diff_report,
    export_html,
    postmortem,
    regression_report,
    replay_report,
    why_change_report,
)
from tracefi.counterfactual import boundary, counterfactual, why_change
from tracefi.evals import compare, load_scenarios
from tracefi.hashing import load_json
from tracefi.models import load_adapter
from tracefi.storage import SQLiteStorage


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, "tracefi: invalid arguments; use --help for usage.\n")


def parser() -> argparse.ArgumentParser:
    root = SafeArgumentParser(
        prog="tracefi",
        description="Financial decision provenance → failure attribution → counterfactual debugging",
    )
    root.add_argument("--db", default=".tracefi/traces.sqlite3", help="Local SQLite path")
    root.add_argument("--version", action="version", version="TraceFi 0.1.0")
    commands = root.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="List recent traces")
    listing.add_argument("--limit", type=int, default=50)
    for command in ("show", "analyze", "replay", "export", "counterfactual"):
        sub = commands.add_parser(command)
        sub.add_argument("trace", nargs="?", default="latest")
        if command in ("replay", "counterfactual"):
            sub.add_argument("--json", action="store_true")
            sub.add_argument(
                "--adapter", required=True, help="Explicit adapter: deterministic or module:factory"
            )
        if command == "export":
            sub.add_argument("--format", choices=("json", "html"), default="json")
            sub.add_argument("--output", type=Path)
        if command == "analyze":
            sub.add_argument("--json", action="store_true")
        if command == "counterfactual":
            sub.add_argument("--feature", required=True, help="e.g. context.liquidity")
            sub.add_argument("--value", help="JSON value for a single intervention")
            sub.add_argument("--low", type=float)
            sub.add_argument("--high", type=float)
    for command in ("diff", "why-change"):
        sub = commands.add_parser(command)
        sub.add_argument("trace_a")
        sub.add_argument("trace_b")
        sub.add_argument("--json", action="store_true")
        if command == "why-change":
            sub.add_argument("--adapter", required=True)
    evaluation = commands.add_parser("eval")
    evaluation.add_argument("--json", action="store_true")
    evaluation.add_argument("--baseline", required=True)
    evaluation.add_argument("--candidate", required=True)
    evaluation.add_argument("--dataset", type=Path, default=Path(__file__).parents[1] / "datasets")
    evaluation.add_argument("--fail-on-regression", action="store_true")
    runner = commands.add_parser("run", help="Capture offline scenarios with injected test faults")
    runner.add_argument("--adapter", default="deterministic")
    runner.add_argument("--dataset", type=Path, default=Path(__file__).parents[1] / "datasets")
    commands.add_parser("demo")
    serve = commands.add_parser("serve", help="Local read-only timeline dashboard")
    serve.add_argument("--port", type=int, default=8765)
    return root


def emit(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "demo":
            from tracefi.demo import run_demo

            with TraceFi(db=args.db) as collector:
                ids = run_demo(collector)
                print("TRACEFI DEMO · offline synthetic decisions")
                for trace_id in ids:
                    trace = collector.storage.get(trace_id)
                    print(
                        trace_id,
                        trace["proposal"]["action"],
                        trace["proposal"]["amount"],
                        trace["status"].upper(),
                    )
                print("\n" + postmortem(collector.storage.get(ids[-1])))
                print(
                    "\n"
                    + why_change_report(
                        why_change(
                            collector.storage.get(ids[0]),
                            collector.storage.get(ids[1]),
                            load_adapter("deterministic"),
                        )
                    )
                )
            return 0
        if args.command == "run":
            from tracefi.evals import run_scenarios

            with TraceFi(db=args.db) as collector:
                ids = run_scenarios(
                    collector, load_adapter(args.adapter), load_scenarios(args.dataset)
                )
                emit({"traces": ids, "synthetic": True})
            return 0
        if args.command == "eval":
            report = compare(
                load_adapter(args.baseline),
                load_adapter(args.candidate),
                load_scenarios(args.dataset),
            )
            emit(report) if args.json else print(regression_report(report))
            return 1 if args.fail_on_regression and report["regressions"] else 0
        if args.command == "serve":
            from tracefi.dashboard import serve

            serve(args.db, args.port)
            return 0
        storage = SQLiteStorage(args.db)
        try:
            if args.command == "list":
                if args.limit < 1:
                    raise ValueError("Limit must be positive")
                emit(storage.list(args.limit))
            elif args.command in ("diff", "why-change"):
                a, b = storage.get(args.trace_a), storage.get(args.trace_b)
                report = (
                    diff(a, b)
                    if args.command == "diff"
                    else why_change(a, b, load_adapter(args.adapter))
                )
                render = diff_report if args.command == "diff" else why_change_report
                emit(report) if args.json else print(render(report))
            else:
                trace = storage.get(args.trace)
                if args.command == "show":
                    emit(trace)
                elif args.command == "analyze":
                    emit(analyze(trace)) if args.json else print(postmortem(trace))
                elif args.command == "replay":
                    report = replay(trace, load_adapter(args.adapter))
                    emit(report) if args.json else print(replay_report(report))
                    return 0 if report["equal"] else 1
                elif args.command == "counterfactual":
                    adapter = load_adapter(args.adapter)
                    if args.value is not None:
                        if args.low is not None or args.high is not None:
                            raise ValueError("Use --value or --low/--high")
                        report = counterfactual(trace, adapter, args.feature, load_json(args.value))
                    elif args.low is not None and args.high is not None:
                        report = boundary(trace, adapter, args.feature, args.low, args.high)
                    else:
                        raise ValueError("Provide --value or both --low and --high")
                    emit(report) if args.json else print(counterfactual_report(report))
                elif args.command == "export":
                    value = (
                        export_html(trace)
                        if args.format == "html"
                        else json.dumps(trace, indent=2, ensure_ascii=False)
                    )
                    if args.output:
                        args.output.write_text(value, encoding="utf-8")
                        print(f"Exported {args.output}")
                    else:
                        print(value)
        finally:
            storage.close()
        return 0
    except Exception as exc:
        # Never echo adapter/tool exception messages that may contain credentials.
        print(
            f"tracefi: {type(exc).__name__}: operation failed; check inputs, adapter and trace integrity.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
