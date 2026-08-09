#!/usr/bin/env python3
"""Rebuild a model-pilot summary from immutable completed episode artifacts."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from run_model_pilot import source_manifest, trace_manifest

from arl.core.types import canonical_json
from arl_modelpilot.deepseek import DEFAULT_DEEPSEEK_PRICING
from arl_modelpilot.experiment import (
    V018_CONFIG,
    V019_CONFIG,
    ModelPilotConfig,
    build_model_pilot_summary,
)
from arl_study.scheduler import file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--config-version", choices=("0.18.0", "0.19.0"), required=True)
    parser.add_argument("--previous-summary", type=Path)
    return parser.parse_args()


def _config(version: str) -> ModelPilotConfig:
    return {"0.18.0": V018_CONFIG, "0.19.0": V019_CONFIG}[version]


def load_completed_results(workspace: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    state_path = workspace / "study-state.json"
    if not state_path.is_file():
        raise RuntimeError(f"Study state is missing: {state_path}")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("status") != "complete":
        raise RuntimeError("Only a completed study can be summarized")
    manifest = state.get("manifest")
    jobs = state.get("jobs")
    if not isinstance(manifest, dict) or not isinstance(jobs, dict):
        raise RuntimeError("Study state has invalid manifest or jobs")
    manifest_jobs = manifest.get("jobs")
    if not isinstance(manifest_jobs, list) or len(manifest_jobs) != 144:
        raise RuntimeError("Completed model pilot must contain exactly 144 jobs")

    results: list[dict[str, Any]] = []
    for manifest_job in manifest_jobs:
        if not isinstance(manifest_job, dict) or not isinstance(manifest_job.get("job_id"), str):
            raise RuntimeError("Study manifest job is invalid")
        job_id = manifest_job["job_id"]
        entry = jobs.get(job_id)
        if not isinstance(entry, dict) or entry.get("status") != "completed":
            raise RuntimeError(f"Study job is not complete: {job_id}")
        result_path = workspace / entry["result_file"]
        trace_path = workspace / entry["trace_file"]
        if file_sha256(result_path) != entry["result_sha256"]:
            raise RuntimeError(f"Result hash mismatch: {job_id}")
        if file_sha256(trace_path) != entry["trace_sha256"]:
            raise RuntimeError(f"Trace hash mismatch: {job_id}")
        record = json.loads(result_path.read_text(encoding="utf-8"))
        if record.get("trace_sha256") != entry["trace_sha256"]:
            raise RuntimeError(f"Result-to-trace link mismatch: {job_id}")
        result = record.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"Job result payload is invalid: {job_id}")
        results.append(result)
    return results, state


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    if args.output.resolve().is_relative_to(args.workspace.resolve()):
        raise SystemExit("--output must be outside --workspace")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is required only for the exact credential leak audit")

    project_root = Path(__file__).resolve().parents[1]
    episodes, state = load_completed_results(args.workspace)
    config = _config(args.config_version)
    summary = build_model_pilot_summary(
        episodes,
        workspace=args.workspace,
        project_root=project_root,
        api_key=api_key,
        config=config,
    )
    previous: dict[str, Any] | None = None
    if args.previous_summary is not None:
        previous = json.loads(args.previous_summary.read_text(encoding="utf-8"))
        if not isinstance(previous, dict):
            raise RuntimeError("Previous summary must be an object")
    current_source = source_manifest(project_root)
    previous_metadata = previous.get("metadata", {}) if previous else {}
    summary["metadata"].update(
        {
            "study_manifest_sha256": state["manifest_sha256"],
            "study_state_sha256": file_sha256(args.workspace / "study-state.json"),
            "source_manifest": previous_metadata.get("source_manifest", current_source),
            "summary_builder_source_manifest": current_source,
            "trace_manifest": trace_manifest(args.workspace),
            "pricing": DEFAULT_DEEPSEEK_PRICING.as_dict(),
            "resume_used": previous_metadata.get("resume_used", False),
            "summary_revision": "all-provider-call-billing-audit-v2",
            "previous_summary_sha256": (
                file_sha256(args.previous_summary) if args.previous_summary else None
            ),
            "api_episodes_rerun_for_summary_revision": 0,
        }
    )
    serialized = canonical_json(summary)
    if api_key in serialized:
        raise RuntimeError("Credential leak gate rejected the rebuilt summary")
    write_json_atomic(args.output, summary, refuse_overwrite=True)
    print(
        f"Rebuilt {len(episodes)} episodes into {args.output}; "
        f"tokens={summary['aggregate']['model_usage']['total_tokens']}, "
        f"validity={summary['validity']['all_selected_checks_passed']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
