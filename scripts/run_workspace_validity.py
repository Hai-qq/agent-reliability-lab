#!/usr/bin/env python3
"""Run the deterministic ARL v0.4 validity-gate experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_validity.experiment import run_workspace_validity_experiment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        [
            *project_root.glob("src/arl/**/*.py"),
            *project_root.glob("src/arl_r2/**/*.py"),
            *project_root.glob("src/arl_multitask/**/*.py"),
            *project_root.glob("src/arl_validity/**/*.py"),
            project_root / "scripts/run_workspace_validity.py",
            project_root / "tests/golden/workspace_multitask_v03.json",
        ]
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
    result = run_workspace_validity_experiment(project_root)
    result["metadata"]["source_manifest"] = source_manifest(project_root)
    write_json_atomic(args.output, result)
    print(
        "Wrote "
        f"{result['validity']['random_valid_tool']['rollout_count']} random-valid rollouts, "
        f"{result['validity']['dump_state']['case_count']} dump-state cases, and {args.output}"
    )


if __name__ == "__main__":
    main()
