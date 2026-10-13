"""Qualify sdist, wheel and editable installs from a clean committed clone."""

import json
import os
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


def run(*args, cwd=None, env=None, expected=0):
    result = subprocess.run(args, cwd=cwd, env=env, text=True, capture_output=True)
    if result.returncode != expected:
        raise RuntimeError(
            f"Command failed: {args[0]} (exit {result.returncode})\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def dashboard_smoke(cli, db, cwd, env):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [str(cli), "--db", str(db), "serve", "--port", str(port)],
        cwd=cwd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(100):
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/traces", timeout=1) as response:
                    assert json.load(response) == []
                with urlopen(f"http://127.0.0.1:{port}/") as response:
                    assert b'id="root"' in response.read()
                return
            except URLError:
                if process.poll() is not None:
                    raise RuntimeError("Installed dashboard exited during startup") from None
                time.sleep(0.05)
        raise RuntimeError("Installed dashboard startup deadline exceeded")
    finally:
        process.terminate()
        process.wait(timeout=10)


def qualify(cli, work, env):
    def command(*args, expected=0):
        return run(str(cli), *args, cwd=work, env=env, expected=expected)

    command("--help")
    assert command("--version") == "TraceFi 0.1.0"
    for name in (
        "demo",
        "list",
        "show",
        "analyze",
        "replay",
        "diff",
        "counterfactual",
        "eval",
        "export",
        "serve",
        "why-change",
        "run",
    ):
        command(name, "--help")
    command("show", expected=2)
    assert not (work / ".tracefi/traces.sqlite3").exists()
    dashboard_smoke(cli, work / "empty.sqlite3", work, env)
    command("demo")
    records = json.loads(command("list"))
    assert len(records) == 2
    original = json.loads(command("show", "latest"))
    command("analyze", "latest", "--json")
    command("replay", "latest", "--adapter", "deterministic")
    command("diff", records[0]["id"], records[1]["id"])
    command(
        "counterfactual",
        "latest",
        "--adapter",
        "deterministic",
        "--feature",
        "context.liquidity",
        "--value",
        "10000000",
    )
    command("export", "latest", "--format", "html", "--output", "postmortem.html")
    command("export", "latest", "--format", "json", "--output", "trace.json")
    assert "TRACEFI POST-MORTEM" in (work / "postmortem.html").read_text()
    assert json.loads((work / "trace.json").read_text()) == original
    command("export", "latest", "--output", "trace.json", expected=2)
    command(
        "eval",
        "--baseline",
        "agent-v1",
        "--candidate",
        "agent-v2",
        "--fail-on-regression",
        expected=1,
    )
    command("demo", "--case-study")
    report = json.loads(command("analyze", "latest", "--json"))
    assert report["likely_failure_class"] == "RETRIEVAL_FAILURE"
    command("replay", "latest", "--adapter", "lending-v1")
    command(
        "counterfactual",
        "latest",
        "--adapter",
        "lending-v1",
        "--feature",
        "context.markets.protocol_b.liquidity_trend_24h",
        "--value",
        "-0.41",
    )
    command(
        "eval",
        "--baseline",
        "lending-v1",
        "--candidate",
        "lending-v2",
        "--dataset",
        "lending",
        "--fail-on-regression",
        expected=1,
    )


def main():
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="tracefi-install-") as directory:
        work = Path(directory)
        clone = work / "clone"
        run("git", "clone", "--quiet", "--no-hardlinks", str(source), str(clone))
        assert not run("git", "status", "--porcelain", cwd=clone)
        artifacts = work / "artifacts"
        run(sys.executable, "-m", "build", "--no-isolation", "--outdir", str(artifacts), cwd=clone)
        wheel = next(artifacts.glob("tracefi-*.whl"))
        sdist = next(artifacts.glob("tracefi-*.tar.gz"))
        with zipfile.ZipFile(wheel) as package:
            names = package.namelist()
            assert (
                len(
                    [
                        name
                        for name in names
                        if name.startswith("tracefi/datasets/") and name.endswith(".json")
                    ]
                )
                == 30
            )
            assert (
                len(
                    [
                        name
                        for name in names
                        if name.startswith("tracefi/case_study/scenarios/")
                        and name.endswith(".json")
                    ]
                )
                == 8
            )
            assert "tracefi/web/index.html" in names
            assert not any(name.startswith(("tests/", "scripts/", ".venv/")) for name in names)
        with tarfile.open(sdist) as package:
            names = package.getnames()
            for suffix in (
                "/LICENSE",
                "/ARCHITECTURE.md",
                "/THREAT_MODEL.md",
                "/docs/QUICKSTART.md",
                "/tests/test_case_study.py",
                "/benchmarks/run.py",
            ):
                assert any(name.endswith(suffix) for name in names), suffix
            assert not any(
                "/.venv/" in name or "/mutants/" in name or name.endswith(".sqlite3")
                for name in names
            )
        # Rebuild from the sdist to catch source manifests that omit wheel inputs.
        run(
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(work / "rebuilt"),
            str(sdist),
        )
        clean_env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONPATH", "PYTHONHOME")
        }
        for mode in ("wheel", "editable"):
            run(sys.executable, "-m", "venv", str(work / mode))
            binary = work / mode / ("Scripts" if os.name == "nt" else "bin")
            python = binary / ("python.exe" if os.name == "nt" else "python")
            cli = binary / ("tracefi.exe" if os.name == "nt" else "tracefi")
            location = work / (mode + "-workspace")
            location.mkdir()
            if mode == "wheel":
                run(
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    str(wheel),
                    cwd=location,
                    env=clean_env,
                )
            else:
                run(
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    "pip>=26.2",
                    "setuptools>=77",
                    "wheel",
                    cwd=location,
                    env=clean_env,
                )
                run(
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--no-build-isolation",
                    "--no-deps",
                    "-e",
                    str(clone),
                    cwd=location,
                    env=clean_env,
                )
            info = json.loads(
                run(
                    str(python),
                    "-c",
                    'import tracefi,json; from importlib.metadata import metadata; print(json.dumps({"path":tracefi.__file__,"requirements":metadata("tracefi").get_all("Requires-Dist",[])}))',
                    cwd=location,
                    env=clean_env,
                )
            )
            assert (str(clone) in info["path"]) is (mode == "editable")
            assert all("extra ==" in requirement for requirement in info["requirements"])
            qualify(cli, location, clean_env)
        print(
            "Clean-clone sdist/wheel/editable passed: CLI help, missing/fresh DB, offline demos, replay, counterfactual, regression exits, exports and dashboard startup; no runtime dependencies."
        )


if __name__ == "__main__":
    main()
