#!/usr/bin/env python3
"""Run or resume the deterministic v0.10 ARL resilience study."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_study.experiment import (
    build_study_summary,
    execute_resilience_job,
    resilience_study_manifest,
    study_artifact_manifests,
)
from arl_study.scheduler import StudyScheduler, write_json_atomic
from arl_study.viewer import build_trace_viewer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--viewer", type=Path)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "pyproject.toml",
            project_root / "src/arl/core/types.py",
            project_root / "src/arl/runtime/journal.py",
            *project_root.glob("src/arl_retail/**/*.py"),
            *project_root.glob("src/arl_travel/**/*.py"),
            *project_root.glob("src/arl_resilience/**/*.py"),
            *project_root.glob("src/arl_study/**/*.py"),
            project_root / "scripts/run_resilience_study.py",
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


def write_text_atomic(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite text artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def validate_run_arguments(args: argparse.Namespace, *, job_count: int) -> None:
    """Reject output contracts that could strand or overwrite study evidence."""
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    viewer = args.viewer.resolve() if args.viewer is not None else None
    if output.is_relative_to(workspace):
        raise SystemExit("--output must be outside --workspace")
    if viewer is not None and viewer.is_relative_to(workspace):
        raise SystemExit("--viewer must be outside --workspace")
    if viewer is not None and output == viewer:
        raise SystemExit("--output and --viewer must be different paths")
    if args.resume:
        if args.stop_after is not None:
            raise SystemExit("--stop-after is only valid for the initial study phase")
        if viewer is None:
            raise SystemExit("A resumed study requires --viewer")
        return
    if args.stop_after is None:
        if viewer is None:
            raise SystemExit("A complete study requires --viewer")
        return
    if not 1 <= args.stop_after < job_count:
        raise SystemExit(f"--stop-after must be between 1 and {job_count - 1}")
    if viewer is not None:
        raise SystemExit("An intentionally interrupted study does not produce --viewer")


def main() -> None:
    args = parse_args()
    manifest = resilience_study_manifest()
    validate_run_arguments(args, job_count=len(manifest.jobs))
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    if args.viewer is not None and args.viewer.exists():
        raise SystemExit(f"Refusing to overwrite viewer: {args.viewer}")

    project_root = Path(__file__).resolve().parents[1]
    scheduler = (
        StudyScheduler.resume(args.workspace, manifest)
        if args.resume
        else StudyScheduler.create(args.workspace, manifest)
    )
    report = scheduler.run(execute_resilience_job, max_new_jobs=args.stop_after)
    summary = build_study_summary(scheduler, report, project_root)
    summary["metadata"]["source_manifest"] = source_manifest(project_root)
    summary["metadata"].update(study_artifact_manifests(args.workspace))

    if report.status == "complete":
        if args.viewer is None:  # pragma: no cover - guarded before state mutation
            raise AssertionError("Complete study has no viewer path")
        viewer = build_trace_viewer(summary, args.workspace / "traces")
        write_text_atomic(args.viewer, viewer)
        summary["metadata"]["viewer"] = {
            "file": args.viewer.name,
            "sha256": hashlib.sha256(args.viewer.read_bytes()).hexdigest(),
            "self_contained": True,
            "external_dependencies": 0,
        }
        summary["validity"]["read_only_viewer"] = {
            "contains_embedded_data": 'id="arl-data"' in viewer,
            "external_script_count": viewer.count("<script src="),
            "network_api_markers": [
                marker for marker in ("fetch(", "XMLHttpRequest", "WebSocket") if marker in viewer
            ],
            "passed": 'id="arl-data"' in viewer
            and "<script src=" not in viewer
            and all(marker not in viewer for marker in ("fetch(", "XMLHttpRequest", "WebSocket")),
        }
        summary["validity"]["all_selected_checks_passed"] = all(
            value["passed"]
            for key, value in summary["validity"].items()
            if key != "all_selected_checks_passed"
        )
        if not summary["validity"]["all_selected_checks_passed"]:
            raise AssertionError("Viewer validity gate failed")
    elif args.viewer is not None:  # pragma: no cover - guarded before state mutation
        raise AssertionError("Interrupted study unexpectedly has a viewer path")

    write_json_atomic(args.output, summary, refuse_overwrite=True)
    print(
        f"Study {report.status}: {report.completed_count}/{report.total_count} jobs complete; "
        f"wrote {args.output} and {scheduler.state_path}"
    )


if __name__ == "__main__":
    main()
