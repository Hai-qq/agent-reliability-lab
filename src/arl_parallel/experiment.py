"""Fixed four-worker resilience study for the ARL v0.11 increment."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json, digest_value
from arl.history import verify_recorded_source_manifest
from arl_parallel import __version__
from arl_parallel.scheduler import ParallelRunReport, ParallelStudyScheduler
from arl_study.experiment import execute_resilience_job, resilience_study_manifest
from arl_study.scheduler import StudyJob, StudyManifest

STUDY_ID = "parallel-resilience-study-v0.11.0"
WORKER_COUNT = 4
LEASE_DURATION_TICKS = 100
STOP_AFTER = 12
LEAVE_LEASES = 4
REFERENCE_SUMMARY = "artifacts/cross_domain_resilience_v09/summary.json"
REFERENCE_TRACES = "artifacts/cross_domain_resilience_v09/traces"
CRASH_JOB_ID = "resilience-retail-seed-1-r2_contract_guarded-incompatible_conflict"
EXPIRE_JOB_ID = "resilience-travel-seed-2-r2_confirmed-control"
HEARTBEAT_JOB_ID = "resilience-travel-seed-0-r2_confirmed-incompatible_conflict"

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
    "v0.10": "artifacts/study_runtime_v10/summary.json",
}


class SimulatedWorkerCrash(RuntimeError):
    """Typed local failure used to validate lease retry semantics."""


def parallel_resilience_manifest() -> StudyManifest:
    reference = resilience_study_manifest()
    return StudyManifest(
        study_id=STUDY_ID,
        experiment_version="parallel-resilience-v0.11.0",
        jobs=reference.jobs,
    )


def execute_parallel_resilience_job(job: StudyJob, trace_path: Path) -> dict[str, Any]:
    if job.job_id == CRASH_JOB_ID and trace_path.name.endswith(".lease-1.jsonl"):
        event = {
            "event_id": "worker-failure:0001",
            "parent_event_id": None,
            "timestamp_logical": 1,
            "actor": "parallel-worker",
            "event_type": "worker_crash_simulated",
            "tool_name": None,
            "error_code": "simulated_worker_crash",
            "fault_id": "worker-crash-once",
            "job_digest": digest_value(job.as_dict()),
            "input_digest": None,
            "output_digest": None,
            "state_hash_before": None,
            "state_hash_after": None,
        }
        trace_path.write_bytes((canonical_json(event) + "\n").encode("utf-8"))
        raise SimulatedWorkerCrash(job.job_id)
    return execute_resilience_job(job, trace_path)


def _file_manifest(paths: list[Path]) -> dict[str, Any]:
    files = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(paths)}
    return {
        "algorithm": "sha256(canonical_json({filename: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest(),
        "files": files,
    }


def parallel_artifact_manifests(workspace: Path) -> dict[str, Any]:
    return {
        "result_manifest": _file_manifest(list((workspace / "results").glob("*.json"))),
        "trace_manifest": _file_manifest(list((workspace / "traces").glob("*.jsonl"))),
        "attempt_manifest": _file_manifest(list((workspace / "attempts").glob("*.jsonl"))),
        "state_sha256": hashlib.sha256(
            (workspace / "parallel-study-state.json").read_bytes()
        ).hexdigest(),
    }


def historical_source_manifest_check(project_root: Path) -> dict[str, Any]:
    increments: dict[str, Any] = {}
    for version, relative_summary in _HISTORICAL_SUMMARIES.items():
        summary = json.loads((project_root / relative_summary).read_text(encoding="utf-8"))
        expected = summary["metadata"]["source_manifest"]
        increments[version] = {
            "summary": relative_summary,
            **verify_recorded_source_manifest(project_root, expected),
        }
    return {
        "increments": increments,
        "passed": all(item["matched"] for item in increments.values()),
    }


def _reference_check(
    scheduler: ParallelStudyScheduler,
    episodes: list[dict[str, Any]],
    project_root: Path,
) -> dict[str, Any]:
    reference = json.loads((project_root / REFERENCE_SUMMARY).read_text(encoding="utf-8"))
    reference_by_id = {item["episode_id"]: item for item in reference["episodes"]}
    episode_matches = {
        episode["episode_id"]: episode == reference_by_id.get(episode["episode_id"])
        for episode in episodes
    }
    trace_matches = {}
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
        "passed": all(episode_matches.values()) and all(trace_matches.values()),
    }


def _digest_only_check(workspace: Path) -> dict[str, Any]:
    paths = sorted((workspace / "traces").glob("*.jsonl")) + sorted(
        (workspace / "attempts").glob("*.jsonl")
    )
    serialized = b"".join(path.read_bytes() for path in paths)
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
        "files_checked": len(paths),
        "forbidden_payload_markers": [marker.decode() for marker in forbidden],
        "passed": not forbidden,
    }


def _event_items(state: dict[str, Any], event_type: str) -> list[dict[str, Any]]:
    return [item for item in state["history"] if item["event_type"] == event_type]


def build_parallel_summary(
    scheduler: ParallelStudyScheduler,
    report: ParallelRunReport,
    project_root: Path,
) -> dict[str, Any]:
    state = scheduler.state
    episodes = scheduler.completed_results()
    reference = json.loads((project_root / REFERENCE_SUMMARY).read_text(encoding="utf-8"))
    complete = report.status == "complete"
    aggregate = (
        reference["aggregate"]
        if complete
        else {
            "episode_count": len(episodes),
            "safe_successes": sum(item["evaluation"]["safe_success"] for item in episodes),
            "compatible_recovery_rate_delta": 0.0,
        }
    )
    attempts = {job_id: entry["attempt_count"] for job_id, entry in state["jobs"].items()}
    commits = {job_id: entry["commit_count"] for job_id, entry in state["jobs"].items()}
    expirations = _event_items(state, "lease_expired")
    reclaimed = _event_items(state, "resume_reclaimed_leases")
    reference_check = _reference_check(scheduler, episodes, project_root)
    validity: dict[str, Any] = {
        "parallel_manifest": {
            "jobs": len(scheduler.manifest.jobs),
            "workers": scheduler.worker_count,
            "max_leased_count": report.max_leased_count,
            "passed": len(scheduler.manifest.jobs) == 36
            and scheduler.worker_count == WORKER_COUNT
            and report.max_leased_count == WORKER_COUNT,
        },
        "progress_consistency": {
            "completed": report.completed_count,
            "pending": report.pending_count,
            "leased": report.leased_count,
            "total": report.total_count,
            "passed": report.completed_count + report.pending_count + report.leased_count
            == report.total_count
            and report.completed_count == len(episodes),
        },
        "reference_equivalence": reference_check,
        "digest_only_traces": _digest_only_check(scheduler.workspace),
        "at_most_one_final_commit": {
            "commit_counts": commits,
            "passed": all(count in {0, 1} for count in commits.values()),
        },
    }
    if complete:
        expired_ids = [item["job_id"] for item in expirations]
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
                    and report.preexisting_completed_count == STOP_AFTER
                    and report.preexisting_results_preserved is True,
                },
                "lease_recovery": {
                    "lease_acquisitions": report.lease_acquisition_count,
                    "lease_expirations": report.lease_expiration_count,
                    "expired_job_ids": expired_ids,
                    "resume_reclaimed_events": reclaimed,
                    "passed": report.lease_acquisition_count == 42
                    and report.lease_expiration_count == 5
                    and len(reclaimed) == 1
                    and len(reclaimed[0]["reclaimed_job_ids"]) == LEAVE_LEASES,
                },
                "fault_recovery": {
                    "worker_failures": report.worker_failure_count,
                    "stale_commit_rejections": report.stale_commit_rejection_count,
                    "heartbeats": report.heartbeat_count,
                    "attempt_counts": attempts,
                    "attempt_trace_files": len(
                        list((scheduler.workspace / "attempts").glob("*.jsonl"))
                    ),
                    "passed": report.worker_failure_count == 1
                    and report.stale_commit_rejection_count == 1
                    and report.heartbeat_count == 1
                    and attempts[CRASH_JOB_ID] == 2
                    and attempts[EXPIRE_JOB_ID] == 2
                    and len(list((scheduler.workspace / "attempts").glob("*.jsonl"))) == 2,
                },
                "exactly_one_final_commit": {
                    "commit_counts": commits,
                    "passed": all(count == 1 for count in commits.values()),
                },
                "historical_source_manifests": historical_source_manifest_check(project_root),
            }
        )
    else:
        validity["intentional_stop_shape"] = {
            "completed": report.completed_count,
            "pending": report.pending_count,
            "leased": report.leased_count,
            "passed": report.completed_count == STOP_AFTER
            and report.pending_count == 36 - STOP_AFTER - LEAVE_LEASES
            and report.leased_count == LEAVE_LEASES,
        }
    validity["all_selected_checks_passed"] = all(
        value["passed"] for key, value in validity.items() if key != "all_selected_checks_passed"
    )
    if not validity["all_selected_checks_passed"]:
        raise AssertionError("Parallel study validity gate failed")

    return {
        "metadata": {
            "increment_version": __version__,
            "root_project_version": "0.3.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "study_id": scheduler.manifest.study_id,
            "study_manifest_sha256": scheduler.manifest.sha256,
            "worker_count": scheduler.worker_count,
            "lease_duration_ticks": scheduler.lease_duration_ticks,
            "reference_increment": "v0.9",
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "status": report.status,
        "progress": {
            "completed_count": report.completed_count,
            "pending_count": report.pending_count,
            "leased_count": report.leased_count,
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
        "parallel": {
            "lease_acquisition_count": report.lease_acquisition_count,
            "lease_expiration_count": report.lease_expiration_count,
            "stale_commit_rejection_count": report.stale_commit_rejection_count,
            "worker_failure_count": report.worker_failure_count,
            "heartbeat_count": report.heartbeat_count,
            "max_leased_count": report.max_leased_count,
        },
        "episodes": episodes,
        "aggregate": aggregate,
        "state_history": state["history"],
        "validity": validity,
        "limitations": [
            "Four local threads with deterministic coordinator commits; no distributed hosts.",
            "Logical lease ticks, not wall-clock time or network heartbeats.",
            "At-least-once execution attempts with exactly one accepted final artifact commit.",
            "One fixed worker crash, one forced lease expiry, and one heartbeat in the formal run.",
            "No model, symbolic user, external network, account, credential, or real system.",
        ],
    }
