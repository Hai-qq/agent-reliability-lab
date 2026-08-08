#!/usr/bin/env python3
"""Run or resume the deterministic four-worker ARL v0.11 study."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_parallel.experiment import (
    EXPIRE_JOB_ID,
    HEARTBEAT_JOB_ID,
    LEASE_DURATION_TICKS,
    LEAVE_LEASES,
    STOP_AFTER,
    WORKER_COUNT,
    build_parallel_summary,
    execute_parallel_resilience_job,
    parallel_artifact_manifests,
    parallel_resilience_manifest,
)
from arl_parallel.scheduler import ParallelStudyScheduler
from arl_study.scheduler import write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--leave-leases", type=int, default=0)
    return parser.parse_args()


def validate_run_arguments(args: argparse.Namespace) -> None:
    workspace = args.workspace.resolve()
    output = args.output.resolve()
    if output.is_relative_to(workspace):
        raise SystemExit("--output must be outside --workspace")
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    if args.resume:
        if args.stop_after is not None or args.leave_leases:
            raise SystemExit("Resume does not accept --stop-after or --leave-leases")
        return
    if args.stop_after != STOP_AFTER or args.leave_leases != LEAVE_LEASES:
        raise SystemExit(
            f"Initial formal phase requires --stop-after {STOP_AFTER} --leave-leases {LEAVE_LEASES}"
        )


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "pyproject.toml",
            project_root / "src/arl/core/types.py",
            project_root / "src/arl/runtime/journal.py",
            *project_root.glob("src/arl_retail/**/*.py"),
            *project_root.glob("src/arl_travel/**/*.py"),
            *project_root.glob("src/arl_resilience/**/*.py"),
            project_root / "src/arl_study/__init__.py",
            project_root / "src/arl_study/scheduler.py",
            project_root / "src/arl_study/experiment.py",
            *project_root.glob("src/arl_parallel/**/*.py"),
            project_root / "scripts/run_parallel_study.py",
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


def main() -> None:
    args = parse_args()
    validate_run_arguments(args)
    project_root = Path(__file__).resolve().parents[1]
    manifest = parallel_resilience_manifest()
    if args.resume:
        scheduler = ParallelStudyScheduler.resume(
            args.workspace,
            manifest,
            worker_count=WORKER_COUNT,
            lease_duration_ticks=LEASE_DURATION_TICKS,
        )
        scheduler.reclaim_all_leases()
    else:
        scheduler = ParallelStudyScheduler.create(
            args.workspace,
            manifest,
            worker_count=WORKER_COUNT,
            lease_duration_ticks=LEASE_DURATION_TICKS,
        )
    report = scheduler.run(
        execute_parallel_resilience_job,
        max_new_jobs=args.stop_after,
        leave_leases=args.leave_leases,
        expire_once_job_ids=(EXPIRE_JOB_ID,),
        heartbeat_once_job_ids=(HEARTBEAT_JOB_ID,),
    )
    summary = build_parallel_summary(scheduler, report, project_root)
    summary["metadata"]["source_manifest"] = source_manifest(project_root)
    summary["metadata"].update(parallel_artifact_manifests(args.workspace))
    write_json_atomic(args.output, summary, refuse_overwrite=True)
    print(
        f"Parallel study {report.status}: {report.completed_count}/{report.total_count} complete, "
        f"{report.leased_count} leased; wrote {args.output} and {scheduler.state_path}"
    )


if __name__ == "__main__":
    main()
