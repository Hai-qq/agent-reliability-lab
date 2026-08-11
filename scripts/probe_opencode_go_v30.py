#!/usr/bin/env python3
"""Run the repeated v0.30 two-model protocol and availability probe."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from arl.core.types import canonical_json
from arl_replication_v30.backend import fetch_catalog_attestation
from arl_replication_v30.integrity import source_manifest
from arl_replication_v30.prerequisites import validate_preflight_summary
from arl_replication_v30.probe import run_protocol_probe
from arl_study.scheduler import file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--preflight-summary", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite probe output: {args.output}")
    api_key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENCODE_GO_API_KEY is required and is never accepted on the CLI")
    project_root = Path(__file__).resolve().parents[1]
    current_sources = source_manifest(project_root)
    preflight = json.loads(args.preflight_summary.read_text(encoding="utf-8"))
    preflight_attestation = validate_preflight_summary(
        preflight,
        current_source_manifest=current_sources,
    )
    preflight_attestation["artifact_sha256"] = file_sha256(args.preflight_summary)
    if not preflight_attestation["passed"]:
        raise RuntimeError("OpenCode Go v0.30 zero-model preflight gate failed")
    catalog = fetch_catalog_attestation(api_key, timeout_seconds=args.timeout_seconds)
    if not catalog["passed"]:
        raise RuntimeError("OpenCode Go v0.30 catalog attestation failed")
    result = run_protocol_probe(
        api_key=api_key,
        timeout_seconds=args.timeout_seconds,
        catalog_attestation=catalog,
    )
    result["metadata"]["source_manifest"] = current_sources
    result["preflight_attestation"] = preflight_attestation
    serialized = canonical_json(result)
    if api_key in serialized:
        raise RuntimeError("Credential leak gate rejected the v0.30 probe payload")
    write_json_atomic(args.output, result, refuse_overwrite=True)
    if json.loads(args.output.read_text(encoding="utf-8")) != result:
        raise RuntimeError("Written v0.30 protocol probe did not round-trip")
    print(
        f"Wrote v0.30 two-model availability probe to {args.output}; "
        f"calls={result['logical_call_count']}; passed={result['passed']}",
        flush=True,
    )
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
