#!/usr/bin/env python3
"""Run the public-safe Qwen structured-tool protocol probe for v0.28."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from pathlib import Path

from arl.core.types import canonical_json
from arl_opencode_v28.backend import OpenCodeQwenV28Backend, fetch_catalog_attestation
from arl_opencode_v28.probe import run_qwen_protocol_probe
from arl_study.scheduler import write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, object]:
    paths = (
        project_root / "pyproject.toml",
        project_root / "scripts/probe_opencode_go_v28.py",
        project_root / "src/arl/core/types.py",
        project_root / "src/arl_mainstudy/model.py",
        project_root / "src/arl_modelpilot/deepseek.py",
        project_root / "src/arl_opencode_v28/backend.py",
        project_root / "src/arl_opencode_v28/contract.py",
        project_root / "src/arl_opencode_v28/probe.py",
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
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite probe evidence: {args.output}")
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive")
    api_key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENCODE_GO_API_KEY is required and is never accepted on the CLI")
    catalog = fetch_catalog_attestation(api_key, timeout_seconds=args.timeout_seconds)
    backend = OpenCodeQwenV28Backend(
        api_key=api_key,
        timeout_seconds=args.timeout_seconds,
    )
    result = run_qwen_protocol_probe(backend, catalog_attestation=catalog)
    project_root = Path(__file__).resolve().parents[1]
    result["metadata"].update(
        {
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "source_manifest": source_manifest(project_root),
        }
    )
    serialized = canonical_json(result)
    if api_key in serialized:
        raise RuntimeError("Credential leak gate rejected the v0.28 probe payload")
    write_json_atomic(args.output, result, refuse_overwrite=True)
    if json.loads(args.output.read_text(encoding="utf-8")) != result:
        raise RuntimeError("Written v0.28 probe did not round-trip")
    print(
        f"Wrote digest-only Qwen protocol probe to {args.output}; "
        f"calls={len(result['provider_calls'])}, passed={result['passed']}",
        flush=True,
    )
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
