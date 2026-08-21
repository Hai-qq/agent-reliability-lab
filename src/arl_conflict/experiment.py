"""Paired compatible/incompatible state-conflict experiment for ARL v0.8."""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from arl.core.types import Observation, StepResult, canonical_json, digest_value
from arl.history import verify_recorded_source_manifest
from arl.runtime.journal import EventJournal
from arl_conflict import __version__
from arl_conflict.env import (
    ENV_VERSION,
    TARGET_CONFLICT_FAULT_ID,
    UNRELATED_CONFLICT_FAULT_ID,
    ConflictMode,
    ConflictWorkspaceEnvironment,
    conflicting_start_for_seed,
)
from arl_conflict.evaluator import evaluate_workspace_conflict
from arl_conflict.runtime import ConflictAwareRuntime, ConflictGuard, ConflictPlanStep
from arl_multitask.env import RESCHEDULE_TASK_ID
from arl_multitask.experiment import task_actions
from arl_multitask.runtime import MultiTaskRuntime

SEEDS = (0, 1, 2)
RUNTIMES = ("r2_confirmed", "r2_conflict_aware")
CONDITIONS = ("clean", "compatible_conflict", "incompatible_conflict")
RUN_ID = "workspace-conflict-v0.8.0"

_HISTORICAL_SUMMARIES = {
    "v0.1": "artifacts/workspace_paired/summary.json",
    "v0.2": "artifacts/workspace_r2_postcommit/summary.json",
    "v0.3": "artifacts/workspace_multitask_v03/summary.json",
    "v0.4": "artifacts/workspace_validity_v04/summary.json",
    "v0.5": "artifacts/retail_minimal_v05/summary.json",
    "v0.6": "artifacts/travel_minimal_v06/summary.json",
    "v0.7": "artifacts/schema_adapter_v07/summary.json",
}


def conflict_plan(observation: Observation) -> list[ConflictPlanStep]:
    """Build guards only from the public observation and public read tools."""
    actions = task_actions(observation, "r2_confirmed")
    task = observation.visible_task
    expected_notifications = [
        {
            "event_id": task["event_id"],
            "recipient": recipient,
            "kind": "reschedule",
            "target_start_at": task["new_start_at"],
        }
        for recipient in sorted(task["recipients"])
    ]
    return [
        ConflictPlanStep(
            action=actions[0],
            guard=ConflictGuard(
                tool_name="calendar.get_event",
                arguments={"event_id": task["event_id"]},
                value_path=("event", "start_at"),
                expected_value=task["current_start_at"],
            ),
        ),
        ConflictPlanStep(
            action=actions[1],
            guard=ConflictGuard(
                tool_name="calendar.get_event",
                arguments={"event_id": task["event_id"]},
                value_path=("event", "start_at"),
                expected_value=task["new_start_at"],
            ),
        ),
        ConflictPlanStep(
            action=actions[2],
            guard=ConflictGuard(
                tool_name="messages.get_reschedule_notifications",
                arguments={"event_id": task["event_id"]},
                value_path=("notifications",),
                expected_value=expected_notifications,
            ),
        ),
    ]


def _conflict_mode(condition: str) -> ConflictMode:
    modes: dict[str, ConflictMode] = {
        "clean": "none",
        "compatible_conflict": "unrelated_state_change_before_update_once",
        "incompatible_conflict": "target_state_change_before_update_once",
    }
    return modes[condition]


def run_episode(
    *,
    runtime_name: str,
    condition: str,
    seed: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    episode_id = f"conflict-reschedule-seed-{seed}-{runtime_name}-{condition}"
    environment = ConflictWorkspaceEnvironment(_conflict_mode(condition))
    try:
        observation = environment.reset(RESCHEDULE_TASK_ID, seed)
        initial_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=RUN_ID,
            episode_id=episode_id,
            task_id=RESCHEDULE_TASK_ID,
            seed=seed,
            path=trace_path,
        )
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="harness",
            event_type="episode_started",
            state_hash_before=initial_hash,
            state_hash_after=initial_hash,
            input_digest=digest_value(
                {
                    "runtime": runtime_name,
                    "condition": condition,
                    "observation": observation.as_dict(),
                }
            ),
        )
        plan = conflict_plan(observation)
        if runtime_name == "r2_conflict_aware":
            execution = ConflictAwareRuntime().execute(environment, plan, journal)
            execution_data = execution.as_dict()
        else:
            baseline = MultiTaskRuntime("r2_confirmed").execute(
                environment,
                [step.action for step in plan],
                journal,
            )
            execution_data = {
                **baseline.as_dict(),
                "conflict_count": int(baseline.failure_code == "state_version_conflict"),
                "conflict_probe_count": 0,
                "conflict_rebase_count": 0,
                "conflict_abort_count": int(baseline.failure_code == "state_version_conflict"),
            }

        final_snapshot = environment.snapshot()
        evaluation = evaluate_workspace_conflict(
            initial_snapshot,
            final_snapshot,
            journal.as_dicts(),
        )
        final_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="evaluator",
            event_type="evaluation_completed",
            state_hash_before=final_hash,
            state_hash_after=final_hash,
            output_digest=digest_value(evaluation.as_dict()),
        )
        world = environment.export_world()
        event = next(
            item
            for item in world["calendar_events"]
            if item["event_id"] == observation.visible_task["event_id"]
        )
        request = next(
            item
            for item in world["change_requests"]
            if item["request_id"] == observation.visible_task["request_id"]
        )
        metadata = next(
            item for item in world["workspace_metadata"] if item["key"] == "last_viewed_event_id"
        )
        fault_ids = sorted(
            {event.fault_id for event in journal.events if event.fault_id is not None}
        )
        return {
            "episode_id": episode_id,
            "task_id": RESCHEDULE_TASK_ID,
            "seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "conflict_mode": _conflict_mode(condition),
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "execution": execution_data,
            "evaluation": evaluation.as_dict(),
            "observed_fault_ids": fault_ids,
            "final_state": {
                "event_start_at": event["start_at"],
                "notification_count": len(world["reschedule_notifications"]),
                "request_status": request["status"],
                "idempotency_record_count": len(world["idempotency_records"]),
                "metadata_value": metadata["value"],
            },
            "trace_file": trace_path.name if trace_path is not None else None,
            "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
            "trace_event_count": len(journal.events),
        }
    finally:
        environment.close()


def _run_matrix(traces_dir: Path | None) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for runtime_name in RUNTIMES:
        for condition in CONDITIONS:
            for seed in SEEDS:
                episode_id = f"conflict-reschedule-seed-{seed}-{runtime_name}-{condition}"
                trace_path = traces_dir / f"{episode_id}.jsonl" if traces_dir else None
                episodes.append(
                    run_episode(
                        runtime_name=runtime_name,
                        condition=condition,
                        seed=seed,
                        trace_path=trace_path,
                    )
                )
    return episodes


def _runtime_aggregate(episodes: Sequence[dict[str, Any]], runtime_name: str) -> dict[str, Any]:
    selected = [episode for episode in episodes if episode["runtime"] == runtime_name]
    by_condition = {
        condition: {
            "task_successes": sum(
                episode["evaluation"]["task_success"]
                for episode in selected
                if episode["condition"] == condition
            ),
            "safe_successes": sum(
                episode["evaluation"]["safe_success"]
                for episode in selected
                if episode["condition"] == condition
            ),
            "total": sum(episode["condition"] == condition for episode in selected),
        }
        for condition in CONDITIONS
    }
    compatible = by_condition["compatible_conflict"]
    incompatible = [
        episode for episode in selected if episode["condition"] == "incompatible_conflict"
    ]
    classified_aborts = sum(
        episode["execution"]["failure_code"] == "conflict_precondition_changed"
        for episode in incompatible
    )
    return {
        "episode_count": len(selected),
        "by_condition": by_condition,
        "compatible_conflict_recovery_rate": (
            compatible["task_successes"] / compatible["total"] if compatible["total"] else None
        ),
        "incompatible_conflict_classified_abort_rate": (
            classified_aborts / len(incompatible) if incompatible else None
        ),
        "conflict_count": sum(episode["execution"]["conflict_count"] for episode in selected),
        "conflict_probe_count": sum(
            episode["execution"]["conflict_probe_count"] for episode in selected
        ),
        "conflict_rebase_count": sum(
            episode["execution"]["conflict_rebase_count"] for episode in selected
        ),
        "conflict_abort_count": sum(
            episode["execution"]["conflict_abort_count"] for episode in selected
        ),
    }


def _aggregate(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_runtime = {
        runtime_name: _runtime_aggregate(episodes, runtime_name) for runtime_name in RUNTIMES
    }
    return {
        "episode_count": len(episodes),
        "task_count": 1,
        "seed_count": len(SEEDS),
        "runtime_count": len(RUNTIMES),
        "condition_count": len(CONDITIONS),
        "by_runtime": by_runtime,
        "compatible_recovery_rate_delta": (
            by_runtime["r2_conflict_aware"]["compatible_conflict_recovery_rate"]
            - by_runtime["r2_confirmed"]["compatible_conflict_recovery_rate"]
        ),
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


def _guard_contract_checks() -> dict[str, Any]:
    guard = ConflictGuard(
        tool_name="calendar.get_event",
        arguments={"event_id": "synthetic-event"},
        value_path=("event", "start_at"),
        expected_value="2026-09-20T08:00:00Z",
    )

    def result(value: dict[str, Any]) -> StepResult:
        return StepResult(
            status="ok",
            value=value,
            error_code=None,
            state_version=1,
            retry_after_ms=None,
            state_hash_before="before",
            state_hash_after="after",
            timestamp_logical=1,
        )

    cases = {
        "exact_value_matches": guard.matches(
            result({"event": {"start_at": "2026-09-20T08:00:00Z"}})
        ),
        "changed_value_rejected": not guard.matches(
            result({"event": {"start_at": "2026-09-20T18:00:00Z"}})
        ),
        "missing_path_rejected": not guard.matches(result({"event": {}})),
        "wrong_shape_rejected": not guard.matches(result({"event": []})),
    }
    return {"cases": cases, "passed": all(cases.values())}


def _reset_snapshot_and_baseline_checks() -> dict[str, Any]:
    reset_hashes: dict[str, list[str]] = {}
    for mode in (
        "none",
        "unrelated_state_change_before_update_once",
        "target_state_change_before_update_once",
    ):
        environment = ConflictWorkspaceEnvironment(mode)
        try:
            reset_hashes[mode] = [
                environment.reset(RESCHEDULE_TASK_ID, 0).state_hash for _ in range(20)
            ]
        finally:
            environment.close()
    reset_passed = len({value for hashes in reset_hashes.values() for value in hashes}) == 1

    environment = ConflictWorkspaceEnvironment("unrelated_state_change_before_update_once")
    try:
        observation = environment.reset(RESCHEDULE_TASK_ID, 1)
        initial = environment.snapshot()
        initial_hash = environment.state_hash()
        first = environment.step(conflict_plan(observation)[0].action)
        changed_hash = environment.state_hash()
        environment.restore(initial)
        restored = bool(
            environment.state_hash() == initial_hash
            and environment.state_version == 0
            and environment.logical_time == 0
        )
        second = environment.step(conflict_plan(observation)[0].action)
        reinjected = bool(
            first.error_code == "state_version_conflict"
            and second.error_code == "state_version_conflict"
            and changed_hash == environment.state_hash()
        )
        do_nothing = evaluate_workspace_conflict(initial, initial, [])
        claim_only = evaluate_workspace_conflict(
            initial,
            initial,
            [
                {
                    "event_id": "claim-only:0001",
                    "event_type": "evaluation_completed",
                    "tool_name": None,
                    "error_code": None,
                    "fault_id": None,
                }
            ],
        )
    finally:
        environment.close()
    return {
        "reset_iterations_per_mode": 20,
        "reset_passed": reset_passed,
        "snapshot_restore_passed": restored,
        "fault_reinjection_after_restore_passed": reinjected,
        "do_nothing_rejected": not do_nothing.task_success,
        "claim_only_rejected": not claim_only.task_success,
        "passed": all(
            (
                reset_passed,
                restored,
                reinjected,
                not do_nothing.task_success,
                not claim_only.task_success,
            )
        ),
    }


def _validity_checks(
    episodes: Sequence[dict[str, Any]],
    traces_dir: Path,
    project_root: Path,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    trace_count = len(list(traces_dir.glob("*.jsonl")))
    checks["matrix_shape"] = {
        "episodes": len(episodes),
        "trace_files": trace_count,
        "passed": len(episodes) == 18 and trace_count == 18,
    }
    checks["paired_initial_states"] = {
        "unique_hashes_by_seed": {
            str(seed): sorted(
                {episode["initial_state_hash"] for episode in episodes if episode["seed"] == seed}
            )
            for seed in SEEDS
        },
        "passed": all(
            len({episode["initial_state_hash"] for episode in episodes if episode["seed"] == seed})
            == 1
            for seed in SEEDS
        ),
    }
    clean = [episode for episode in episodes if episode["condition"] == "clean"]
    checks["clean_control_success"] = {
        "successes": sum(episode["evaluation"]["safe_success"] for episode in clean),
        "total": len(clean),
        "passed": len(clean) == 6
        and all(episode["evaluation"]["safe_success"] for episode in clean),
    }
    compatible = [episode for episode in episodes if episode["condition"] == "compatible_conflict"]
    incompatible = [
        episode for episode in episodes if episode["condition"] == "incompatible_conflict"
    ]
    checks["single_registered_difference"] = {
        "compatible_fault_ids": {
            episode["episode_id"]: episode["observed_fault_ids"] for episode in compatible
        },
        "incompatible_fault_ids": {
            episode["episode_id"]: episode["observed_fault_ids"] for episode in incompatible
        },
        "passed": all(not episode["observed_fault_ids"] for episode in clean)
        and all(
            episode["observed_fault_ids"] == [UNRELATED_CONFLICT_FAULT_ID] for episode in compatible
        )
        and all(
            episode["observed_fault_ids"] == [TARGET_CONFLICT_FAULT_ID] for episode in incompatible
        ),
    }
    baseline_faults = [
        episode
        for episode in episodes
        if episode["runtime"] == "r2_confirmed" and episode["condition"] != "clean"
    ]
    checks["baseline_stops_on_state_conflict"] = {
        "failure_codes": [episode["execution"]["failure_code"] for episode in baseline_faults],
        "passed": len(baseline_faults) == 6
        and all(
            episode["execution"]["failure_code"] == "state_version_conflict"
            and episode["execution"]["conflict_probe_count"] == 0
            and not episode["evaluation"]["task_success"]
            for episode in baseline_faults
        ),
    }
    aware_compatible = [
        episode for episode in compatible if episode["runtime"] == "r2_conflict_aware"
    ]
    checks["compatible_conflict_recovered"] = {
        "episodes": [episode["episode_id"] for episode in aware_compatible],
        "passed": len(aware_compatible) == 3
        and all(
            episode["execution"]["completed_plan"]
            and episode["execution"]["conflict_count"] == 1
            and episode["execution"]["conflict_probe_count"] == 1
            and episode["execution"]["conflict_rebase_count"] == 1
            and episode["execution"]["conflict_abort_count"] == 0
            and len(episode["evaluation"]["recovery_events"]) == 1
            and episode["evaluation"]["safe_success"]
            for episode in aware_compatible
        ),
    }
    aware_incompatible = [
        episode for episode in incompatible if episode["runtime"] == "r2_conflict_aware"
    ]
    checks["incompatible_conflict_fails_closed"] = {
        "episodes": [episode["episode_id"] for episode in aware_incompatible],
        "passed": len(aware_incompatible) == 3
        and all(
            not episode["execution"]["completed_plan"]
            and episode["execution"]["failure_code"] == "conflict_precondition_changed"
            and episode["execution"]["conflict_probe_count"] == 1
            and episode["execution"]["conflict_rebase_count"] == 0
            and episode["execution"]["conflict_abort_count"] == 1
            and episode["final_state"]["event_start_at"]
            == conflicting_start_for_seed(episode["seed"])
            and episode["final_state"]["notification_count"] == 0
            and episode["final_state"]["request_status"] == "pending"
            and episode["final_state"]["idempotency_record_count"] == 0
            for episode in aware_incompatible
        ),
    }
    checks["guard_contract_mutations"] = _guard_contract_checks()
    checks["reset_snapshot_and_baselines"] = _reset_snapshot_and_baseline_checks()
    checks["historical_source_manifests"] = historical_source_manifest_check(project_root)

    observation_environment = ConflictWorkspaceEnvironment()
    try:
        observation = observation_environment.reset(RESCHEDULE_TASK_ID, 0)
        visible = canonical_json(observation.as_dict()).lower()
    finally:
        observation_environment.close()
    forbidden_visible = [
        marker
        for marker in ("fault_id", "conflict_mode", "evaluator", "oracle", "minefield")
        if marker in visible
    ]
    checks["ground_truth_isolation"] = {
        "forbidden_visible_markers": forbidden_visible,
        "passed": not forbidden_visible,
    }

    serialized_traces = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden_trace_markers = [
        marker
        for marker in (
            b"@synthetic.invalid",
            b'"arguments"',
            b'"visible_task"',
            b"external-observer:",
        )
        if marker in serialized_traces
    ]
    checks["digest_only_traces"] = {
        "forbidden_payload_markers": [marker.decode() for marker in forbidden_trace_markers],
        "passed": not forbidden_trace_markers,
    }
    return checks


def _normalize_for_comparison(episodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for episode in episodes:
        item = dict(episode)
        item.pop("trace_file", None)
        normalized.append(item)
    return normalized


def run_conflict_experiment(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    primary = _run_matrix(traces_dir)
    shadow = _run_matrix(None)
    repeat_deterministic = _normalize_for_comparison(primary) == _normalize_for_comparison(shadow)
    validity = _validity_checks(primary, traces_dir, project_root)
    validity["repeat_results_deterministic"] = {"passed": repeat_deterministic}
    validity["all_selected_checks_passed"] = all(
        value["passed"] for key, value in validity.items() if key != "all_selected_checks_passed"
    )
    assert validity["all_selected_checks_passed"]

    aggregate = _aggregate(primary)
    baseline = aggregate["by_runtime"]["r2_confirmed"]
    aware = aggregate["by_runtime"]["r2_conflict_aware"]
    assert baseline["by_condition"]["clean"]["task_successes"] == 3
    assert baseline["by_condition"]["compatible_conflict"]["task_successes"] == 0
    assert aware["by_condition"]["clean"]["task_successes"] == 3
    assert aware["by_condition"]["compatible_conflict"]["task_successes"] == 3
    assert aware["by_condition"]["incompatible_conflict"]["task_successes"] == 0
    assert aware["incompatible_conflict_classified_abort_rate"] == 1.0
    assert aggregate["compatible_recovery_rate_delta"] == 1.0

    return {
        "metadata": {
            "increment_version": __version__,
            "root_project_version": "0.3.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "environment_version": ENV_VERSION,
            "task_ids": [RESCHEDULE_TASK_ID],
            "seeds": list(SEEDS),
            "runtimes": list(RUNTIMES),
            "conditions": list(CONDITIONS),
            "registered_differences": {
                "compatible_conflict": "atomic unrelated metadata change before event update",
                "incompatible_conflict": "atomic target event-time change before event update",
            },
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "episodes": primary,
        "aggregate": aggregate,
        "validity": validity,
        "limitations": [
            "One existing synthetic Workspace reschedule task with three deterministic seeds.",
            "One conflict site and one guarded rebase maximum per action.",
            "Exact public-read preconditions, not automatic semantic merge or model inference.",
            "Fixed oracle action plan, not an LLM or learned policy.",
            "No scheduler, symbolic user, trace UI, real account, credential, or network access.",
        ],
    }
