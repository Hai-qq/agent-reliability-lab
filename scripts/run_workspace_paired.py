#!/usr/bin/env python3
"""Run the first deterministic ARL clean/fault paired experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from arl.experiments.workspace_paired import run_workspace_paired_experiment


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--traces-dir", required=True, type=Path)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        [*project_root.glob("src/arl/**/*.py"), project_root / "scripts/run_workspace_paired.py"]
    )
    files = {
        str(path.relative_to(project_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    combined = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"sha256": combined, "files": files}


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
    result = run_workspace_paired_experiment(args.traces_dir)
    result["metadata"]["source_manifest"] = source_manifest(project_root)
    write_json_atomic(args.output, result)
    print(
        "Wrote "
        f"{len(result['episodes'])} episodes, "
        f"{len(list(args.traces_dir.glob('*.jsonl')))} traces, and {args.output}"
    )


if __name__ == "__main__":
    main()
