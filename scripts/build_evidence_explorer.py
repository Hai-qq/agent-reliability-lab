#!/usr/bin/env python3
"""Build the deterministic ARL v0.14 read-only evidence explorer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_evidence.catalog import collect_evidence
from arl_evidence.viewer import audit_viewer, build_explorer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def validate_output_dir(output_dir: Path) -> None:
    if output_dir.exists():
        raise SystemExit(f"Refusing to overwrite output directory: {output_dir}")


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "pyproject.toml",
            project_root / "src/arl/core/types.py",
            *project_root.glob("src/arl_evidence/**/*.py"),
            project_root / "scripts/build_evidence_explorer.py",
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


def write_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build_outputs(project_root: Path) -> tuple[dict[str, Any], str]:
    evidence = collect_evidence(project_root)
    evidence["metadata"]["source_manifest"] = source_manifest(project_root)
    evidence["validity"]["read_only_viewer"] = {"passed": True}
    provisional = build_explorer(evidence)
    viewer_audit = audit_viewer(provisional)
    evidence["validity"]["read_only_viewer"] = viewer_audit
    evidence["validity"]["all_selected_checks_passed"] = all(
        item["passed"]
        for key, item in evidence["validity"].items()
        if key != "all_selected_checks_passed"
    )
    if not evidence["validity"]["all_selected_checks_passed"]:
        raise AssertionError("Evidence explorer validity gates failed")
    document = build_explorer(evidence)
    if audit_viewer(document) != viewer_audit:
        raise AssertionError("Final viewer audit changed after embedding audit result")
    return evidence, document


def main() -> None:
    args = parse_args()
    validate_output_dir(args.output_dir)
    project_root = Path(__file__).resolve().parents[1]
    evidence, document = build_outputs(project_root)
    args.output_dir.mkdir(parents=True)
    evidence_payload = (json.dumps(evidence, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    write_atomic(args.output_dir / "evidence.json", evidence_payload)
    write_atomic(args.output_dir / "index.html", document.encode("utf-8"))
    print(
        f"Wrote {len(evidence['increments'])} verified increments, "
        f"{evidence['validity']['formal_repeat_traces']['file_count']} trace pairs, "
        f"and {args.output_dir / 'index.html'}"
    )


if __name__ == "__main__":
    main()
