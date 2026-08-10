#!/usr/bin/env python3
"""Run the zero-model v0.29 holdout validity gate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arl.core.types import canonical_json
from arl_holdout_v29.integrity import source_manifest, trace_manifest
from arl_holdout_v29.preflight import run_holdout_preflight


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--traces-dir", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    project_root = Path(__file__).resolve().parents[1]
    summary = run_holdout_preflight(args.traces_dir, project_root)
    summary["metadata"]["source_manifest"] = source_manifest(project_root)
    summary["metadata"]["trace_manifest"] = trace_manifest(args.traces_dir.parent)
    summary = json.loads(canonical_json(summary))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(canonical_json(summary) + "\n", encoding="utf-8")
    if json.loads(args.output.read_text(encoding="utf-8")) != summary:
        raise RuntimeError("Written v0.29 preflight summary did not round-trip")
    print(
        f"Wrote {summary['aggregate']['episode_count']} scripted holdout episodes to "
        f"{args.output}; validity={summary['validity']['all_selected_checks_passed']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
