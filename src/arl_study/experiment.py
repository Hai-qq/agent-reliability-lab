"""ARL v0.10 deterministic stop/resume study experiment."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl.history import verify_recorded_source_manifest
from arl_resilience.experiment import CONDITIONS, DOMAINS, RUNTIMES, SEEDS, run_episode
from arl_study import __version__
from arl_study.scheduler import StudyJob, StudyManifest, StudyRunReport, StudyScheduler

STUDY_ID = "cross-domain-resilience-study-v0.10.0"
INTERRUPT_AFTER = 13
REFERENCE_SUMMARY = "artifacts/cross_domain_resilience_v09/summary.json"
REFERENCE_TRACES = "artifacts/cross_domain_resilience_v09/traces"

_HISTORICAL_SUMMARIES = {
    "v0.1": "artifacts/workspace_paired/summary.json",
    "v0.2": "artifacts/workspace_r2_postcommit/summary.json",
    "v0.3": "artifacts/workspace_multitask_v03/summary.json",
    "v0.4": "artifacts/workspace_validity_v04/summary.json",
    "v0.5": "artifacts/retail_minimal_v05/summary.json",
    "v0.6": "artifacts/travel_minimal_v06/summary.json",
    "v0.7": "artifacts/schema_adapter_v07/summary.json",
    "v0.8": "artifacts/workspace_conflict_v08/summary.json",
    "v0.9": REFERENCE_SUMMARY,
}


def resilience_study_manifest() -> StudyManifest:
    jobs = []
    for domain in DOMAINS:
        for runtime in RUNTIMES:
            for condition in CONDITIONS:
                for seed in SEEDS:
                    job_id = f"resilience-{domain}-seed-{seed}-{runtime}-{condition}"
                    jobs.append(
                        StudyJob.from_payload(
                            job_id,
                            {
                                "domain": domain,
                                "runtime": runtime,
                                "condition": condition,
                                "seed": seed,
                            },
                        )
                    )
    return StudyManifest(
        study_id=STUDY_ID,
        experiment_version="cross-domain-resilience-v0.9.0",
        jobs=tuple(jobs),
    )


def execute_resilience_job(job: StudyJob, trace_path: Path) -> dict[str, Any]:
    payload = job.payload()
    result = run_episode(
        domain=payload["domain"],
        runtime_name=payload["runtime"],
        condition=payload["condition"],
        seed=payload["seed"],
        trace_path=trace_path,
    )
    result["trace_file"] = f"{job.job_id}.jsonl"
    return result


def _file_manifest(paths: list[Path]) -> dict[str, Any]:
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    return {
        "algorithm": "sha256(canonical_json({filename: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest(),
        "files": files,
    }


def study_artifact_manifests(workspace: Path) -> dict[str, Any]:
    return {
        "result_manifest": _file_manifest(list((workspace / "results").glob("*.json"))),
        "trace_manifest": _file_manifest(list((workspace / "traces").glob("*.jsonl"))),
        "state_sha256": hashlib.sha256((workspace / "study-state.json").read_bytes()).hexdigest(),
    }


def historical_source_manifest_check(project_root: Path) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for version, relative_summary in _HISTORICAL_SUMMARIES.items():
        summary = json.loads((project_root / relative_summary).read_text(encoding="utf-8"))
        manifest = summary["metadata"]["source_manifest"]
        details[version] = {
            "summary": relative_summary,
            **verify_recorded_source_manifest(project_root, manifest),
        }
    return {"increments": details, "passed": all(item["matched"] for item in details.values())}


def _reference_check(
    scheduler: StudyScheduler,
    episodes: list[dict[str, Any]],
    project_root: Path,
) -> dict[str, Any]:
    reference = json.loads((project_root / REFERENCE_SUMMARY).read_text(encoding="utf-8"))
    reference_by_id = {item["episode_id"]: item for item in reference["episodes"]}
    episode_matches = {
        episode["episode_id"]: episode == reference_by_id.get(episode["episode_id"])
        for episode in episodes
    }
    trace_matches: dict[str, bool] = {}
    for episode in episodes:
        name = episode["trace_file"]
        scheduled = scheduler.workspace / "traces" / name
        reference_trace = project_root / REFERENCE_TRACES / name
        trace_matches[name] = bool(
            reference_trace.is_file() and scheduled.read_bytes() == reference_trace.read_bytes()
        )
    return {
        "reference_summary": REFERENCE_SUMMARY,
        "episode_matches": episode_matches,
        "trace_matches": trace_matches,
        "passed": len(episodes) == len(episode_matches)
        and all(episode_matches.values())
        and all(trace_matches.values()),
    }


def _trace_payload_check(scheduler: StudyScheduler) -> dict[str, Any]:
    serialized = b"".join(
        path.read_bytes() for path in sorted((scheduler.workspace / "traces").glob("*.jsonl"))
    )
    forbidden = [
        marker
        for marker in (
            b"@synthetic.invalid",
            b'"arguments"',
            b'"visible_task"',
            b"external-observer:",
            b"synthetic-key",
        )
        if marker in serialized
    ]
    return {
        "forbidden_payload_markers": [marker.decode() for marker in forbidden],
        "passed": not forbidden,
    }


def _partial_aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "episode_count": len(episodes),
        "safe_successes": sum(item["evaluation"]["safe_success"] for item in episodes),
        "compatible_recovery_rate_delta": 0.0,
    }


def build_study_summary(
    scheduler: StudyScheduler,
    report: StudyRunReport,
    project_root: Path,
) -> dict[str, Any]:
    episodes = scheduler.completed_results()
    reference = json.loads((project_root / REFERENCE_SUMMARY).read_text(encoding="utf-8"))
    complete = report.status == "complete"
    aggregate = reference["aggregate"] if complete else _partial_aggregate(episodes)
    state = scheduler.state
    reference_check = _reference_check(scheduler, episodes, project_root)
    attempt_counts = {job_id: entry["attempt_count"] for job_id, entry in state["jobs"].items()}
    validity: dict[str, Any] = {
        "manifest_shape": {
            "jobs": len(scheduler.manifest.jobs),
            "unique_job_ids": len({job.job_id for job in scheduler.manifest.jobs}),
            "passed": len(scheduler.manifest.jobs) == 36
            and len({job.job_id for job in scheduler.manifest.jobs}) == 36,
        },
        "progress_consistency": {
            "completed": report.completed_count,
            "pending": report.pending_count,
            "total": report.total_count,
            "passed": report.completed_count + report.pending_count == report.total_count
            and report.completed_count == len(episodes),
        },
        "reference_equivalence": reference_check,
        "single_execution_per_completed_job": {
            "attempt_counts": attempt_counts,
            "passed": all(
                count == 1
                for job_id, count in attempt_counts.items()
                if state["jobs"][job_id]["status"] == "completed"
            ),
        },
        "digest_only_traces": _trace_payload_check(scheduler),
    }
    if complete:
        validity.update(
            {
                "complete_matrix": {
                    "episodes": len(episodes),
                    "passed": len(episodes) == 36 and episodes == reference["episodes"],
                },
                "resume_preserved_preexisting_results": {
                    "preexisting_completed_count": report.preexisting_completed_count,
                    "sha256_before": report.preexisting_results_sha256_before,
                    "sha256_after": report.preexisting_results_sha256_after,
                    "passed": report.resume_used
                    and report.preexisting_completed_count == INTERRUPT_AFTER
                    and report.preexisting_results_preserved is True,
                },
                "scheduler_state_complete": {
                    "status": state["status"],
                    "history_events": len(state["history"]),
                    "passed": state["status"] == "complete"
                    and all(entry["status"] == "completed" for entry in state["jobs"].values()),
                },
                "historical_source_manifests": historical_source_manifest_check(project_root),
            }
        )
    validity["all_selected_checks_passed"] = all(
        value["passed"] for key, value in validity.items() if key != "all_selected_checks_passed"
    )
    if not validity["all_selected_checks_passed"]:
        raise AssertionError("Study validity gate failed")

    return {
        "metadata": {
            "increment_version": __version__,
            "root_project_version": "0.3.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "study_id": scheduler.manifest.study_id,
            "study_manifest_sha256": scheduler.manifest.sha256,
            "scheduled_experiment_version": scheduler.manifest.experiment_version,
            "reference_increment": "v0.9",
            "interrupt_after": INTERRUPT_AFTER,
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "status": report.status,
        "progress": {
            "completed_count": report.completed_count,
            "pending_count": report.pending_count,
            "total_count": report.total_count,
            "new_jobs_completed": report.new_jobs_completed,
        },
        "resume": {
            "used": report.resume_used,
            "preexisting_completed_count": report.preexisting_completed_count,
            "preexisting_results_sha256_before": report.preexisting_results_sha256_before,
            "preexisting_results_sha256_after": report.preexisting_results_sha256_after,
            "preexisting_results_preserved": report.preexisting_results_preserved,
        },
        "episodes": episodes,
        "aggregate": aggregate,
        "state_history": state["history"],
        "validity": validity,
        "limitations": [
            "Sequential local scheduling only; no parallel workers, leases, or distributed queue.",
            "One intentional job-boundary interruption after 13 of 36 fixed synthetic jobs.",
            "Viewer is a generated read-only HTML artifact, not a mutable experiment API.",
            "No model, symbolic user, external network, account, credential, or real system.",
        ],
    }
