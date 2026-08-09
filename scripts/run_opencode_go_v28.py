#!/usr/bin/env python3
"""Run or resume the v0.28 OpenCode Go Flash + Qwen canary or main."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_opencode_v28.backend import MODEL_PRICING, fetch_catalog_attestation
from arl_opencode_v28.experiment import build_summary, execute_job, study_manifest
from arl_opencode_v28.prerequisites import validate_canary_summary, validate_protocol_probe
from arl_study.scheduler import StudyScheduler, file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--stage", choices=("canary", "formal"), default="formal")
    parser.add_argument("--protocol-probe", required=True, type=Path)
    parser.add_argument("--canary-summary", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-new-jobs", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
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
            *project_root.glob("src/arl_opencode_v28/**/*.py"),
            project_root / "scripts/probe_opencode_go_v28.py",
            project_root / "scripts/run_opencode_go_v28.py",
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
    project_root = Path(__file__).resolve().parents[1]
    current_sources = source_manifest(project_root)
    try:
        protocol_artifact = json.loads(args.protocol_probe.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("OpenCode Go v0.28 protocol probe could not be read") from error
    protocol_attestation = validate_protocol_probe(
        protocol_artifact,
        current_source_manifest=current_sources,
    )
    protocol_attestation["artifact_sha256"] = file_sha256(args.protocol_probe)
    if not protocol_attestation["passed"]:
        raise RuntimeError("OpenCode Go v0.28 protocol probe gate failed")
    prerequisite_attestations: dict[str, Any] = {
        "protocol_probe": protocol_attestation,
    }
    if args.stage == "formal":
        if args.canary_summary is None:
            raise SystemExit("--canary-summary is required for --stage formal")
        try:
            canary_artifact = json.loads(args.canary_summary.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError("OpenCode Go v0.28 canary summary could not be read") from error
        canary_attestation = validate_canary_summary(
            canary_artifact,
            current_source_manifest=current_sources,
        )
        canary_attestation["artifact_sha256"] = file_sha256(args.canary_summary)
        if not canary_attestation["passed"]:
            raise RuntimeError("OpenCode Go v0.28 canary prerequisite gate failed")
        prerequisite_attestations["canary_summary"] = canary_attestation
    elif args.canary_summary is not None:
        raise SystemExit("--canary-summary is only accepted for --stage formal")
    catalog = fetch_catalog_attestation(api_key, timeout_seconds=args.timeout_seconds)
    if not catalog["passed"]:
        raise RuntimeError("OpenCode Go v0.28 catalog attestation failed")
    canary = args.stage == "canary"
    manifest = study_manifest(canary=canary)
    scheduler = (
        StudyScheduler.resume(args.workspace, manifest)
        if args.resume
        else StudyScheduler.create(args.workspace, manifest)
    )
    progress = len(scheduler.completed_job_ids())

    def execute(job: Any, trace_path: Path) -> dict[str, Any]:
        nonlocal progress
        result = execute_job(
            job,
            trace_path,
            api_key=api_key,
            timeout_seconds=args.timeout_seconds,
        )
        progress += 1
        print(
            f"[{progress}/{len(manifest.jobs)}] {job.job_id} "
            f"safe={int(result['evaluation']['safe_success'])} "
            f"logical_calls={result['provider']['logical_call_count']} "
            f"transport_attempts={result['provider']['transport_attempt_count']}",
            flush=True,
        )
        return result

    report = scheduler.run(execute, max_new_jobs=args.max_new_jobs)
    if report.status != "complete":
        print(
            f"OpenCode Go v0.28 checkpointed: completed={report.completed_count}, "
            f"pending={report.pending_count}; resume with --resume",
            flush=True,
        )
        return
    summary = build_summary(
        scheduler.completed_results(),
        workspace=args.workspace,
        project_root=project_root,
        api_key=api_key,
        catalog_attestation=catalog,
        prerequisite_attestations=prerequisite_attestations,
        canary=canary,
    )
    summary["metadata"].update(
        {
            "study_manifest_sha256": manifest.sha256,
            "study_state_sha256": file_sha256(args.workspace / "study-state.json"),
            "source_manifest": current_sources,
            "trace_manifest": trace_manifest(args.workspace),
            "pricing": {
                slot: {
                    **MODEL_PRICING[slot].as_dict(),
                    "interpretation": "usage-value estimate, not incremental subscription charge",
                }
                for slot in ("flash", "qwen")
            },
            "resume_used": report.resume_used,
        }
    )
    serialized = canonical_json(summary)
    if api_key in serialized:
        raise RuntimeError("Credential leak gate rejected the v0.28 summary payload")
    write_json_atomic(args.summary, summary, refuse_overwrite=True)
    if json.loads(args.summary.read_text(encoding="utf-8")) != summary:
        raise RuntimeError("Written v0.28 summary did not round-trip")
    usage = summary["aggregate"]["combined_usage"]
    print(
        f"Wrote {len(manifest.jobs)} OpenCode Go v0.28 episodes and {args.summary}; "
        f"tokens={usage['total_tokens']}, "
        f"transport_retries={usage['transport_retries']}, "
        f"usage_value_usd={usage['estimated_usage_value_usd']:.6f}, "
        f"validity={summary['validity']['all_selected_checks_passed']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
