#!/usr/bin/env python3
"""Run and optionally save the no-provider v0.30 scripted preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arl.core.types import canonical_json
from arl.studies.preflight import run_scripted_preflight
from arl.studies.v030 import design_contract


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--design-output", type=Path)
    return parser.parse_args()


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write((canonical_json(value) + "\n").encode("utf-8"))


def main() -> int:
    args = parse_args()
    result = run_scripted_preflight()
    if args.output:
        write_new(args.output, result)
    if args.design_output:
        write_new(args.design_output, design_contract())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["all_selected_checks_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
