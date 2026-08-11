#!/usr/bin/env python3
"""Build a compact 10,000-sample task-cluster bootstrap report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_analysis import __version__
from arl_analysis.bootstrap import task_cluster_bootstrap
from arl_study.scheduler import file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20_260_808)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "src/arl/core/types.py",
            *project_root.glob("src/arl_analysis/**/*.py"),
            project_root / "scripts/build_model_pilot_analysis.py",
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


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Input summary does not exist: {args.input}")
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    summary = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(summary, dict) or not isinstance(summary.get("episodes"), list):
        raise RuntimeError("Input must be a full model-pilot summary with episode records")
    if not summary.get("validity", {}).get("all_selected_checks_passed"):
        raise RuntimeError("Bootstrap input must pass the frozen infrastructure validity gate")

    analysis = task_cluster_bootstrap(
        summary["episodes"],
        iterations=args.iterations,
        seed=args.seed,
    )
    primary = summary.get("aggregate", {}).get("primary_effects", {})
    for name in (
        "fault_recovery_rate_at_3_delta_r2_minus_r1",
        "clean_safe_pass_at_3_delta_r2_minus_r1",
    ):
        if analysis["estimates"][name]["observed"] != primary.get(name):
            raise RuntimeError(
                f"Bootstrap observed estimate does not match input aggregate: {name}"
            )
    project_root = Path(__file__).resolve().parents[1]
    result = {
        "metadata": {
            "package_version": __version__,
            "input_summary_sha256": file_sha256(args.input),
            "input_run_id": summary.get("metadata", {}).get("run_id"),
            "input_binding": summary.get("model_pilot", {}).get("binding"),
            "source_manifest": source_manifest(project_root),
            "raw_model_content_persisted": False,
        },
        **analysis,
    }
    write_json_atomic(args.output, result, refuse_overwrite=True)
    print(
        f"Wrote {args.iterations} paired task-cluster bootstrap samples to {args.output}",
        flush=True,
    )


if __name__ == "__main__":
    main()
