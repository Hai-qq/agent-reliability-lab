#!/usr/bin/env python3
"""Create a small public aggregate from a complete local model-pilot summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arl_modelpilot.experiment import compact_model_pilot_summary
from arl_study.scheduler import file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Full summary does not exist: {args.input}")
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    if args.input.resolve() == args.output.resolve():
        raise SystemExit("--input and --output must differ")

    full_summary = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(full_summary, dict):
        raise RuntimeError("Full summary must be a JSON object")
    compact = compact_model_pilot_summary(
        full_summary,
        full_summary_sha256=file_sha256(args.input),
    )
    write_json_atomic(args.output, compact, refuse_overwrite=True)
    print(
        f"Wrote compact public summary for {compact['episode_evidence']['episode_count']} "
        f"episodes to {args.output}",
        flush=True,
    )


if __name__ == "__main__":
    main()
