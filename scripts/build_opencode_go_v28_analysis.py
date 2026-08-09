#!/usr/bin/env python3
"""Build the paired analysis for a valid and qualified v0.28 main."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_opencode_v28.analysis import analyze_study
from arl_study.scheduler import file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20_260_809)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "src/arl/core/types.py",
            project_root / "src/arl_analysis/__init__.py",
            project_root / "src/arl_analysis/bootstrap.py",
            project_root / "src/arl_opencode_v28/__init__.py",
            project_root / "src/arl_opencode_v28/analysis.py",
            project_root / "scripts/build_opencode_go_v28_analysis.py",
        }
    )
    files = {
        str(path.relative_to(project_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    return {
        "algorithm": "sha256(canonical_json({relative_path: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode()).hexdigest(),
        "files": files,
    }


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Input summary does not exist: {args.input}")
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    summary = json.loads(args.input.read_text())
    if not summary.get("validity", {}).get("all_selected_checks_passed"):
        raise RuntimeError("Analysis input must pass the infrastructure validity gate")
    if not summary.get("readiness", {}).get("ready_for_confirmatory_analysis"):
        raise RuntimeError("Analysis input must pass the model-quality readiness gate")
    analysis = analyze_study(summary, iterations=args.iterations, seed=args.seed)
    if not analysis["validity"]["all_selected_checks_passed"]:
        raise RuntimeError("OpenCode Go v0.28 analysis validity gate failed")
    project_root = Path(__file__).resolve().parents[1]
    result = {
        "metadata": {
            "input_summary_sha256": file_sha256(args.input),
            "input_run_id": summary.get("metadata", {}).get("run_id"),
            "input_bindings": summary.get("experiment", {}).get("bindings"),
            "source_manifest": source_manifest(project_root),
            "raw_model_content_persisted": False,
        },
        **analysis,
    }
    write_json_atomic(args.output, result, refuse_overwrite=True)
    print(
        f"Wrote {args.iterations} paired v0.28 task bootstrap samples to {args.output}; "
        f"hypothesis_supported={analysis['outcome_gates']['primary_hypothesis_supported']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
