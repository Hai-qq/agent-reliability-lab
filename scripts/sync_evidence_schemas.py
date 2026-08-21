#!/usr/bin/env python3
"""Generate or check the published arl-evidence-v1 JSON Schemas."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from arl.evidence.schema import schema_documents


def payload(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    output = project_root / "schemas/arl-evidence-v1"
    if args.check:
        failures = [
            name
            for name, document in schema_documents().items()
            if not (output / name).is_file() or (output / name).read_bytes() != payload(document)
        ]
        if failures:
            print(f"Schema files are stale or missing: {', '.join(failures)}")
            return 1
        print(f"Verified {len(schema_documents())} generated schema files")
        return 0
    output.mkdir(parents=True, exist_ok=True)
    for name, document in schema_documents().items():
        (output / name).write_bytes(payload(document))
    print(f"Generated {len(schema_documents())} schema files in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
