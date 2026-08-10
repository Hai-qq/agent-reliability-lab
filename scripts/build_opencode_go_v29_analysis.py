#!/usr/bin/env python3
"""Build the fail-closed confirmatory v0.29 holdout analysis."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arl.core.types import canonical_json
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
        raise RuntimeError("v0.29 analysis source manifest does not match the formal input")
    analysis = analyze_study(
        summary,
        iterations=args.iterations,
        seed=args.seed,
        confirmatory=True,
    )
    analysis["metadata"] = {
        "input_file": args.input.name,
        "input_sha256": __import__("hashlib").sha256(args.input.read_bytes()).hexdigest(),
        "source_manifest": current_sources,
    }
    write_json_atomic(args.output, analysis, refuse_overwrite=True)
    if json.loads(args.output.read_text(encoding="utf-8")) != analysis:
        raise RuntimeError("Written v0.29 analysis did not round-trip")
    print(
        canonical_json(
            {
                "output": str(args.output),
                "primary_hypothesis_supported": analysis["outcome_gates"][
                    "primary_hypothesis_supported"
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
