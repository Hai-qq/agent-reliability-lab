#!/usr/bin/env python3
"""Run the deterministic v0.8 state-conflict recovery experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_conflict.experiment import run_conflict_experiment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--traces-dir", required=True, type=Path)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "pyproject.toml",
            project_root / "src/arl/core/types.py",
            project_root / "src/arl/envs/workspace.py",
            project_root / "src/arl/runtime/journal.py",
            *project_root.glob("src/arl_r2/**/*.py"),
            *project_root.glob("src/arl_multitask/**/*.py"),
            *project_root.glob("src/arl_conflict/**/*.py"),
            project_root / "scripts/run_conflict_recovery.py",
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


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    if args.traces_dir.exists():
        raise SystemExit(f"Refusing to overwrite traces directory: {args.traces_dir}")
    result = run_conflict_experiment(args.traces_dir, project_root)
    result["metadata"]["source_manifest"] = source_manifest(project_root)
    result["metadata"]["trace_manifest"] = trace_manifest(args.traces_dir)
    write_json_atomic(args.output, result)
    print(
        "Wrote "
        f"{len(result['episodes'])} episodes, "
        f"{len(list(args.traces_dir.glob('*.jsonl')))} traces, and {args.output}"
    )


if __name__ == "__main__":
    main()
