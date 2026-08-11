#!/usr/bin/env python3
"""Build a clearly labeled exploratory v0.29 analysis after readiness failure."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from arl_holdout_v29.analysis import analyze_study
from arl_holdout_v29.integrity import source_manifest
from arl_study.scheduler import write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20_260_809)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = json.loads(args.input.read_text(encoding="utf-8"))
    project_root = Path(__file__).resolve().parents[1]
    current_sources = source_manifest(project_root)
    if (
        summary.get("metadata", {}).get("source_manifest", {}).get("sha256")
        != current_sources["sha256"]
    ):
        raise RuntimeError("v0.29 exploratory source manifest does not match the formal input")
    analysis = analyze_study(
        summary,
        iterations=args.iterations,
        seed=args.seed,
        confirmatory=False,
    )
    analysis["metadata"] = {
        "input_file": args.input.name,
        "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "source_manifest": current_sources,
    }
    write_json_atomic(args.output, analysis, refuse_overwrite=True)
    if json.loads(args.output.read_text(encoding="utf-8")) != analysis:
        raise RuntimeError("Written v0.29 exploratory analysis did not round-trip")
    print(f"Wrote exploratory-only v0.29 analysis to {args.output}")


if __name__ == "__main__":
    main()
