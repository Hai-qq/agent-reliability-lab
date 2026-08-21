#!/usr/bin/env python3
"""Install one wheel in a fresh venv and exercise only installed public surfaces."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import venv
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    if not wheel.is_file() or wheel.suffix != ".whl":
        raise FileNotFoundError(f"wheel does not exist: {wheel}")
    with tempfile.TemporaryDirectory(prefix="arl-clean-wheel-") as temporary:
        root = Path(temporary)
        environment = root / "venv"
        venv.EnvBuilder(with_pip=True, clear=False).create(environment)
        scripts = environment / ("Scripts" if __import__("os").name == "nt" else "bin")
        python = scripts / ("python.exe" if __import__("os").name == "nt" else "python")
        arl = scripts / ("arl.exe" if __import__("os").name == "nt" else "arl")
        run([str(python), "-m", "pip", "install", "--no-deps", str(wheel)])
        help_result = run([str(arl), "--help"])
        if "run" not in help_result.stdout or "verify" not in help_result.stdout:
            raise AssertionError("installed CLI help is incomplete")
        bundle = root / "smoke"
        smoke = run([str(arl), "run", "smoke", "--output", str(bundle)])
        smoke_result = json.loads(smoke.stdout)
        if smoke_result.get("verified") is not True:
            raise AssertionError("installed smoke did not verify")
        run([str(arl), "verify", str(bundle)])
    print("Clean wheel install, CLI help, smoke, and verifier passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
