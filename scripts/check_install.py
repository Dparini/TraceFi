"""Build a clean local clone and smoke-test its wheel outside the source tree."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run(*args, cwd=None, env=None):
    return subprocess.check_output(args, cwd=cwd, env=env, text=True).strip()


def main():
    source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="tracefi-install-") as directory:
        work = Path(directory)
        clone = work / "clone"
        run("git", "clone", "--quiet", "--no-hardlinks", str(source), str(clone))
        assert not run("git", "status", "--porcelain", cwd=clone)
        wheels = work / "wheels"
        run(
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheels),
            str(clone),
        )
        run(sys.executable, "-m", "venv", str(work / "env"))
        binary = work / "env" / ("Scripts" if os.name == "nt" else "bin")
        python = binary / ("python.exe" if os.name == "nt" else "python")
        cli = binary / ("tracefi.exe" if os.name == "nt" else "tracefi")
        wheel = next(wheels.glob("tracefi-*.whl"))
        clean_env = {
            key: value
            for key, value in os.environ.items()
            if key not in ("PYTHONPATH", "PYTHONHOME")
        }
        run(
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            str(wheel),
            cwd=work,
            env=clean_env,
        )
        probe = run(
            str(python),
            "-c",
            'import tracefi,json; from importlib.metadata import metadata; from pathlib import Path; p=Path(tracefi.__file__).parent; print(json.dumps({"path":str(p),"scenarios":len(list((p/"datasets").rglob("*.json"))),"web":(p/"web/index.html").exists(),"requirements":metadata("tracefi").get_all("Requires-Dist",[])}))',
            cwd=work,
            env=clean_env,
        )
        info = json.loads(probe)
        assert str(clone) not in info["path"]
        assert info["scenarios"] == 30 and info["web"]
        assert all("extra ==" in item for item in info["requirements"])
        for args in (
            ("demo",),
            ("replay", "latest", "--adapter", "deterministic"),
            ("analyze", "latest", "--json"),
            ("eval", "--baseline", "agent-v1", "--candidate", "agent-v2", "--json"),
            ("export", "latest", "--format", "html", "--output", "postmortem.html"),
        ):
            run(str(cli), *args, cwd=work, env=clean_env)
        assert "TRACEFI POST-MORTEM" in (work / "postmortem.html").read_text()
        print(
            "Clean-clone wheel install passed: 30 scenarios, packaged dashboard, no runtime dependencies, demo/replay/analyze/eval/HTML export."
        )


if __name__ == "__main__":
    main()
