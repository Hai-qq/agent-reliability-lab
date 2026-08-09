#!/usr/bin/env python3
"""Run or resume the OpenCode Go two-model canary or 864-episode main."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_openstudy.backend import OPENCODE_GO_PRICING, fetch_catalog_attestation
from arl_openstudy.experiment import (
    build_openstudy_summary,
    execute_openstudy_job,
    openstudy_manifest,
)
from arl_study.scheduler import StudyScheduler, file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--stage", choices=("canary", "formal"), default="formal")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-new-jobs", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=90.0)
    return parser.parse_args()


def validate_paths(workspace: Path, summary: Path, *, resume: bool) -> None:
    if summary.exists():
        raise SystemExit(f"Refusing to overwrite summary: {summary}")
    if summary.resolve().is_relative_to(workspace.resolve()):
        raise SystemExit("--summary must be outside --workspace")
    if resume and not workspace.is_dir():
        raise SystemExit(f"Resume workspace does not exist: {workspace}")
    if not resume and workspace.exists():
        raise SystemExit(f"Refusing to reuse workspace without --resume: {workspace}")


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "pyproject.toml",
            project_root / "src/arl/core/types.py",
            project_root / "src/arl/runtime/journal.py",
            project_root / "src/arl_study/scheduler.py",
            *project_root.glob("src/arl_mainstudy/**/*.py"),
            *project_root.glob("src/arl_pilot/**/*.py"),
            *project_root.glob("src/arl_mainpack/**/*.py"),
            *project_root.glob("src/arl_modelpilot/**/*.py"),
            *project_root.glob("src/arl_mainmodel/**/*.py"),
            *project_root.glob("src/arl_openstudy/**/*.py"),
            project_root / "scripts/run_opencode_go_main.py",
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


def trace_manifest(workspace: Path) -> dict[str, Any]:
    files = {
        path.name: file_sha256(path) for path in sorted((workspace / "traces").glob("*.jsonl"))
    }
    return {
        "algorithm": "sha256(canonical_json({trace_filename: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest(),
        "files": files,
    }


def main() -> None:
    args = parse_args()
    validate_paths(args.workspace, args.summary, resume=args.resume)
    if args.max_new_jobs is not None and args.max_new_jobs < 1:
        raise SystemExit("--max-new-jobs must be positive")
    api_key = os.environ.get("OPENCODE_GO_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("OPENCODE_GO_API_KEY is required and is never accepted on the CLI")
    catalog = fetch_catalog_attestation(api_key, timeout_seconds=args.timeout_seconds)
    if not catalog["passed"]:
        raise RuntimeError("OpenCode Go catalog attestation failed")
    canary = args.stage == "canary"
    manifest = openstudy_manifest(canary=canary)
    scheduler = (
        StudyScheduler.resume(args.workspace, manifest)
        if args.resume
        else StudyScheduler.create(args.workspace, manifest)
    )
    progress = len(scheduler.completed_job_ids())

    def execute(job: Any, trace_path: Path) -> dict[str, Any]:
        nonlocal progress
        result = execute_openstudy_job(
            job,
            trace_path,
            api_key=api_key,
            timeout_seconds=args.timeout_seconds,
        )
        progress += 1
        print(
            f"[{progress}/{len(manifest.jobs)}] {job.job_id} "
            f"safe={int(result['evaluation']['safe_success'])} "
            f"calls={result['external_network_calls']}",
            flush=True,
        )
        return result

    report = scheduler.run(execute, max_new_jobs=args.max_new_jobs)
    if report.status != "complete":
        print(
            f"OpenCode Go study checkpointed: completed={report.completed_count}, "
            f"pending={report.pending_count}; resume with --resume",
            flush=True,
        )
        return
    project_root = Path(__file__).resolve().parents[1]
    summary = build_openstudy_summary(
        scheduler.completed_results(),
        workspace=args.workspace,
        project_root=project_root,
        api_key=api_key,
        catalog_attestation=catalog,
        canary=canary,
    )
    summary["metadata"].update(
        {
            "study_manifest_sha256": manifest.sha256,
            "study_state_sha256": file_sha256(args.workspace / "study-state.json"),
            "source_manifest": source_manifest(project_root),
            "trace_manifest": trace_manifest(args.workspace),
            "pricing": {
                **OPENCODE_GO_PRICING.as_dict(),
                "interpretation": "usage-value estimate, not incremental subscription charge",
            },
            "resume_used": report.resume_used,
        }
    )
    serialized = canonical_json(summary)
    if api_key in serialized:
        raise RuntimeError("Credential leak gate rejected the summary payload")
    write_json_atomic(args.summary, summary, refuse_overwrite=True)
    if json.loads(args.summary.read_text(encoding="utf-8")) != summary:
        raise RuntimeError("Written summary did not round-trip")
    usage = summary["aggregate"]["combined_usage"]
    print(
        f"Wrote {len(manifest.jobs)} OpenCode Go episodes and {args.summary}; "
        f"tokens={usage['total_tokens']}, "
        f"usage_value_usd={usage['estimated_usage_value_usd']:.6f}, "
        f"validity={summary['validity']['all_selected_checks_passed']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
