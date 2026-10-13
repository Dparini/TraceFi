"""Real-browser smoke test and optional 60–90 second synthetic demo recording."""

import argparse
import html
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

from tracefi import TraceFi
from tracefi.hashing import state_hash
from tracefi.storage import SQLiteStorage


def cli(db, *args):
    return subprocess.check_output(
        [sys.executable, "-m", "tracefi", "--db", str(db), *args], text=True
    )


def terminal_scene(page, command, output, duration):
    page.set_content(
        '<html lang="en"><body style="background:#0b1020;color:#dbeafe;padding:30px;font:15px monospace"><h1>TraceFi · offline synthetic demo</h1><pre style="white-space:pre-wrap">'
        + html.escape("$ " + command + "\n\n" + output)
        + "</pre></body></html>"
    )
    page.wait_for_timeout(duration * 1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--record-video", action="store_true")
    args = parser.parse_args()
    if args.record_video and not args.assets:
        parser.error("--record-video requires --assets")
    if args.assets:
        args.assets.mkdir(parents=True, exist_ok=True)
        for name in (
            "dashboard-investigation.png",
            "dashboard-counterfactual.png",
            "tracefi-demo.webm",
        ):
            if (args.assets / name).exists():
                parser.error("Output media already exists; choose a fresh output directory")
    with tempfile.TemporaryDirectory(prefix="tracefi-browser-") as directory:
        db = Path(directory) / "traces.sqlite3"
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        root = f"http://127.0.0.1:{port}"
        process = subprocess.Popen(
            [sys.executable, "-m", "tracefi", "--db", str(db), "serve", "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(100):
                try:
                    with urlopen(root, timeout=1):
                        break
                except URLError:
                    if process.poll() is not None:
                        raise RuntimeError("Dashboard failed to start") from None
                    time.sleep(0.05)
            else:
                raise RuntimeError("Dashboard startup deadline exceeded")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                options = {"viewport": {"width": 1440, "height": 1080}}
                if args.record_video:
                    options.update(
                        record_video_dir=str(args.assets),
                        record_video_size={"width": 1440, "height": 1080},
                    )
                context = browser.new_context(**options)
                page = context.new_page()
                failures = []
                page.on("pageerror", lambda error: failures.append(str(error)))
                page.goto(root)
                expect(page.get_by_text("No decisions recorded yet.", exact=False)).to_be_visible()
                demo = cli(db, "demo", "--case-study")
                stored = SQLiteStorage(db, read_only=True)
                try:
                    record = stored.get()
                    trace_id = record["trace_id"]
                    original_digest = state_hash(record)
                finally:
                    stored.close()
                duration = 9 if args.record_video else 0
                if args.record_video:
                    terminal_scene(page, "tracefi demo --case-study", demo, duration)
                    terminal_scene(page, "tracefi show latest", cli(db, "show", "latest"), duration)
                    terminal_scene(
                        page, "tracefi analyze latest", cli(db, "analyze", "latest"), duration
                    )
                    command = "tracefi counterfactual latest --adapter lending-v1 --feature context.markets.protocol_b.liquidity_trend_24h --value -0.41"
                    terminal_scene(
                        page,
                        command,
                        cli(
                            db,
                            "counterfactual",
                            "latest",
                            "--adapter",
                            "lending-v1",
                            "--feature",
                            "context.markets.protocol_b.liquidity_trend_24h",
                            "--value",
                            "-0.41",
                        ),
                        duration,
                    )
                page.goto(root)
                expect(page.locator("button.trace-link")).to_have_count(1)
                page.wait_for_timeout(duration * 1000)
                page.locator("button.trace-link").click()
                expect(page.get_by_text("Snapshot integrity verified", exact=False)).to_be_visible()
                assert page.locator(".timeline-item").count() >= 7
                page.get_by_role("button", name="context", exact=True).click()
                expect(page.locator(".json")).to_contain_text("total_value_usdc")
                page.get_by_role("button", name="evidence", exact=True).click()
                expect(page.locator(".json")).to_contain_text("-1821")
                page.get_by_role("button", name="Failure attribution", exact=True).click()
                expect(page.locator(".failure-class")).to_have_text("RETRIEVAL_FAILURE")
                if args.assets:
                    page.screenshot(
                        path=str(args.assets / "dashboard-investigation.png"), full_page=True
                    )
                page.wait_for_timeout(duration * 1000)
                page.get_by_role("button", name="counterfactual", exact=True).click()
                expect(page.get_by_label("Adapter")).to_have_value("lending-v1")
                expect(page.get_by_text("Not recorded", exact=True)).to_be_visible()
                page.get_by_role("button", name="Test this input", exact=True).click()
                expect(
                    page.get_by_text("Decision changes with this input", exact=True)
                ).to_be_visible()
                expect(page.locator(".experiment-comparison .json").nth(1)).to_contain_text(
                    "protocol_a"
                )
                if args.assets:
                    page.screenshot(
                        path=str(args.assets / "dashboard-counterfactual.png"), full_page=True
                    )
                page.wait_for_timeout(duration * 1000)
                stored = SQLiteStorage(db, read_only=True)
                try:
                    assert state_hash(stored.get(trace_id)) == original_digest
                finally:
                    stored.close()
                if args.record_video:
                    terminal_scene(
                        page,
                        "tracefi eval --baseline lending-v1 --candidate lending-v2 --dataset lending",
                        cli(
                            db,
                            "eval",
                            "--baseline",
                            "lending-v1",
                            "--candidate",
                            "lending-v2",
                            "--dataset",
                            "lending",
                        ),
                        duration,
                    )
                with TraceFi(db=db) as collector:
                    with collector.decision(
                        'xss-probe<img src=x onerror="window.__xss=1">', "1"
                    ) as trace:
                        trace.capture_context(
                            {
                                "metadata": "<script>window.__xss=1</script>",
                                "Authorization": "SYNTHETIC_SECRET_SENTINEL",
                            }
                        )
                        trace.capture_decision(
                            {"action": {"untrusted": "TRANSFER"}, "asset": ["USDC"], "amount": 0}
                        )
                page.goto(root)
                page.get_by_label("Search traces").fill("xss-probe")
                expect(page.locator("button.trace-link")).to_have_count(1)
                page.get_by_label("Status filter").select_option("rejected")
                expect(
                    page.get_by_text("No traces match these filters.", exact=True)
                ).to_be_visible()
                page.get_by_label("Status filter").select_option("all")
                page.locator("button.trace-link").click()
                page.get_by_role("button", name="context", exact=True).click()
                expect(page.locator(".json")).to_contain_text("[REDACTED]")
                assert "SYNTHETIC_SECRET_SENTINEL" not in page.content()
                assert page.evaluate("window.__xss") is None
                assert failures == [], failures
                video = page.video
                context.close()
                if args.record_video:
                    destination = args.assets / "tracefi-demo.webm"
                    source = Path(video.path())
                    os.link(source, destination)
                    source.unlink()
                browser.close()
                print(
                    json.dumps(
                        {
                            "browser": "Chromium",
                            "verified": [
                                "empty state",
                                "listing",
                                "search",
                                "status filter",
                                "details",
                                "timeline",
                                "context",
                                "evidence",
                                "failure attribution",
                                "counterfactual",
                                "immutable trace",
                                "HTML injection escaping",
                                "redaction",
                            ],
                            "page_errors": failures,
                            "recorded": args.record_video,
                        }
                    )
                )
        finally:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
