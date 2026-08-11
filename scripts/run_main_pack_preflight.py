#!/usr/bin/env python3
"""Run the deterministic 24-task, no-model ARL main-pack preflight."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_mainpack.experiment import run_main_pack_preflight
from arl_study.scheduler import write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--traces-dir", required=True, type=Path)
    return parser.parse_args()


def validate_paths(output: Path, traces_dir: Path) -> None:
    if output.exists():
        raise SystemExit(f"Refusing to overwrite output: {output}")
    if traces_dir.exists():
        raise SystemExit(f"Refusing to overwrite traces directory: {traces_dir}")
    if output.resolve().is_relative_to(traces_dir.resolve()):
        raise SystemExit("--output must be outside --traces-dir")


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "pyproject.toml",
            project_root / "src/arl/core/types.py",
            project_root / "src/arl/runtime/journal.py",
            project_root / "src/arl_study/scheduler.py",
            *project_root.glob("src/arl_mainstudy/**/*.py"),
            *project_root.glob("src/arl_pilot/**/*.py"),
            *project_root.glob("src/arl_mainpack/**/*.py"),
            project_root / "scripts/run_main_pack_preflight.py",
        }
    )
    files = {
        str(path.relative_to(project_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    return {
        "algorithm": "sha256(canonical_json({relative_path: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest(),
        "files": files,
    }


def trace_manifest(traces_dir: Path) -> dict[str, Any]:
    files = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(traces_dir.glob("*.jsonl"))
    }
    return {
        "algorithm": "sha256(canonical_json({trace_filename: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest(),
        "files": files,
    }


def main() -> None:
    args = parse_args()
    validate_paths(args.output, args.traces_dir)
    project_root = Path(__file__).resolve().parents[1]
    result = run_main_pack_preflight(args.traces_dir, project_root)
    result["metadata"]["source_manifest"] = source_manifest(project_root)
    result["metadata"]["trace_manifest"] = trace_manifest(args.traces_dir)
    write_json_atomic(args.output, result, refuse_overwrite=True)
    print(
        f"Wrote {len(result['episodes'])} main-pack scripted episodes, "
        f"{len(list(args.traces_dir.glob('*.jsonl')))} traces, and {args.output}"
    )


if __name__ == "__main__":
    main()
