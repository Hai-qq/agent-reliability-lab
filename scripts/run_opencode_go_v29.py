#!/usr/bin/env python3
"""Run or resume the v0.29 OpenCode Go holdout canary or formal matrix."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_holdout_v29.experiment import (
    MODEL_PRICING,
    build_summary,
    execute_job,
    study_manifest,
)
from arl_holdout_v29.integrity import source_manifest, trace_manifest
from arl_holdout_v29.prerequisites import (
    validate_canary_summary,
    validate_preflight_summary,
    validate_protocol_probe,
)
from arl_opencode_v28.backend import fetch_catalog_attestation
from arl_study.scheduler import StudyScheduler, file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--stage", choices=("canary", "formal"), default="formal")
    parser.add_argument("--preflight-summary", required=True, type=Path)
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


def _read_artifact(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"OpenCode Go v0.29 {label} could not be read") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"OpenCode Go v0.29 {label} is not a JSON object")
    return value


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

    preflight_path = args.preflight_summary
    preflight = _read_artifact(preflight_path, "zero-model preflight")
    preflight_attestation = validate_preflight_summary(
        preflight,
        current_source_manifest=current_sources,
    )
    preflight_attestation["artifact_sha256"] = file_sha256(preflight_path)
    if not preflight_attestation["passed"]:
        raise RuntimeError("OpenCode Go v0.29 preflight prerequisite gate failed")

    protocol = _read_artifact(args.protocol_probe, "protocol probe")
    protocol_attestation = validate_protocol_probe(
        protocol,
        current_source_manifest=current_sources,
    )
    protocol_attestation["artifact_sha256"] = file_sha256(args.protocol_probe)
    if not protocol_attestation["passed"]:
        raise RuntimeError("OpenCode Go v0.29 protocol prerequisite gate failed")
    prerequisites: dict[str, Any] = {
        "preflight": preflight_attestation,
        "protocol_probe": protocol_attestation,
    }
    if args.stage == "formal":
        if args.canary_summary is None:
            raise SystemExit("--canary-summary is required for --stage formal")
        canary = _read_artifact(args.canary_summary, "canary summary")
        canary_attestation = validate_canary_summary(
            canary,
            current_source_manifest=current_sources,
        )
        canary_attestation["artifact_sha256"] = file_sha256(args.canary_summary)
        if not canary_attestation["passed"]:
            raise RuntimeError("OpenCode Go v0.29 canary prerequisite gate failed")
        prerequisites["canary"] = canary_attestation
    elif args.canary_summary is not None:
        raise SystemExit("--canary-summary is only accepted for --stage formal")

    catalog = fetch_catalog_attestation(api_key, timeout_seconds=args.timeout_seconds)
    if not catalog["passed"]:
        raise RuntimeError("OpenCode Go v0.29 catalog attestation failed")
    is_canary = args.stage == "canary"
    manifest = study_manifest(canary=is_canary)
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
            f"OpenCode Go v0.29 checkpointed: completed={report.completed_count}, "
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
        prerequisite_attestations=prerequisites,
        canary=is_canary,
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
        raise RuntimeError("Credential leak gate rejected the v0.29 summary payload")
    write_json_atomic(args.summary, summary, refuse_overwrite=True)
    if json.loads(args.summary.read_text(encoding="utf-8")) != summary:
        raise RuntimeError("Written v0.29 summary did not round-trip")
    usage = summary["aggregate"]["combined_usage"]
    print(
        f"Wrote {len(manifest.jobs)} OpenCode Go v0.29 episodes and {args.summary}; "
        f"tokens={usage['total_tokens']}, transport_retries={usage['transport_retries']}, "
        f"usage_value_usd={usage['estimated_usage_value_usd']:.6f}, "
        f"validity={summary['validity']['all_selected_checks_passed']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
