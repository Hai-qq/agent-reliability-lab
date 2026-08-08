#!/usr/bin/env python3
"""Build, verify, or restore deterministic ARL public artifact bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_release.bundles import (
    build_bundle_catalog,
    restore_bundles,
    verify_bundle_dir,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build")
    build.add_argument("--output-dir", required=True, type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--bundle-dir", required=True, type=Path)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--bundle-dir", required=True, type=Path)
    restore.add_argument("--project-root", required=True, type=Path)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "pyproject.toml",
            project_root / "src/arl/core/types.py",
            *project_root.glob("src/arl_release/**/*.py"),
            project_root / "scripts/manage_artifact_bundles.py",
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


def _write_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build(project_root: Path, output_dir: Path) -> None:
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite output directory: {output_dir}")
    manifest, payloads = build_bundle_catalog(project_root)
    manifest["metadata"]["source_manifest"] = source_manifest(project_root)
    output_dir.mkdir(parents=True)
    for relative_path, payload in sorted(payloads.items()):
        target = output_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(target, payload)
    manifest_payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _write_atomic(output_dir / "manifest.json", manifest_payload)
    verification = verify_bundle_dir(output_dir)
    print(
        f"Wrote {verification['bundle_count']} deterministic bundles with "
        f"{manifest['validity']['formal_repeat_trees']['file_count']} files to {output_dir}"
    )


def main() -> None:
    args = parse_args()
    project_root = Path(__file__).resolve().parents[1]
    if args.command == "build":
        build(project_root, args.output_dir)
    elif args.command == "verify":
        result = verify_bundle_dir(args.bundle_dir)
        print(f"Verified {result['bundle_count']} deterministic bundles")
    else:
        result = restore_bundles(args.bundle_dir, args.project_root)
        print(
            f"Restored {len(result['restored_targets'])} artifact targets with "
            f"{result['restored_file_writes']} file writes"
        )


if __name__ == "__main__":
    main()
