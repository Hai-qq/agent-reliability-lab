"""Two-task R1/R2 paired experiment and validity gates for ARL v0.3."""

from __future__ import annotations

import hashlib
import platform
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from arl.core.types import Observation, SnapshotRef, ToolAction, digest_value
from arl.envs.workspace import SCHEMA_VERSION, WORKSPACE_TASK_ID
from arl.runtime.journal import EventJournal
from arl_multitask import __version__
from arl_multitask.env import (
    ENV_VERSION,
    RESCHEDULE_TASK_ID,
    TASK_IDS,
    MultiTaskWorkspaceEnvironment,
)
from arl_multitask.evaluator import evaluate_workspace_multitask
from arl_multitask.runtime import MultiTaskRuntime

SEEDS = (0, 1, 2)
RUNTIMES = ("r1_guarded", "r2_confirmed")
CONDITIONS = ("clean", "fault")
RUN_ID = "workspace-multitask-v0.3.0"


def task_actions(observation: Observation, runtime_name: str) -> list[ToolAction]:
    task = observation.visible_task
    use_idempotency = runtime_name == "r2_confirmed"

    def key(operation: str) -> str | None:
        if not use_idempotency:
            return None
        return f"arl:{observation.task_id}:{observation.seed}:{operation}"

    if observation.task_id == WORKSPACE_TASK_ID:
        return [
            ToolAction(
                tool_name="calendar.create_event",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "event_id": task["event_id"],
                    "title": task["title"],
                    "start_at": task["start_at"],
                    "organizer": task["organizer"],
                    "participants": list(task["recipients"]),
                },
                idempotency_key=key("create-event"),
                expected_state_version=0,
            ),
            ToolAction(
                tool_name="messages.send_invitations",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "event_id": task["event_id"],
                    "recipients": list(task["recipients"]),
                },
                idempotency_key=key("send-invitations"),
                expected_state_version=1,
            ),
        ]

    return [
        ToolAction(
            tool_name="calendar.update_event_time",
            schema_version=SCHEMA_VERSION,
            arguments={
                "event_id": task["event_id"],
                "new_start_at": task["new_start_at"],
            },
            idempotency_key=key("update-event-time"),
            expected_state_version=0,
        ),
        ToolAction(
            tool_name="messages.send_reschedule_notifications",
            schema_version=SCHEMA_VERSION,
            arguments={
                "event_id": task["event_id"],
                "recipients": list(task["recipients"]),
                "target_start_at": task["new_start_at"],
            },
            idempotency_key=key("send-reschedule-notifications"),
            expected_state_version=1,
        ),
        ToolAction(
            tool_name="workspace.resolve_change_request",
            schema_version=SCHEMA_VERSION,
            arguments={"request_id": task["request_id"]},
            idempotency_key=key("resolve-change-request"),
            expected_state_version=2,
        ),
    ]


def _task_slug(task_id: str) -> str:
    return "schedule" if task_id == WORKSPACE_TASK_ID else "reschedule"


def _fault_mode(task_id: str, condition: str) -> str:
    if condition == "clean":
        return "none"
    if task_id == WORKSPACE_TASK_ID:
        return "event_postcommit_timeout_once"
    return "reschedule_notifications_postcommit_timeout_once"


def run_episode(
    *,
    task_id: str,
    runtime_name: str,
    condition: str,
    seed: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    episode_id = f"workspace-{_task_slug(task_id)}-seed-{seed}-{runtime_name}-{condition}"
    environment = MultiTaskWorkspaceEnvironment(fault_mode=_fault_mode(task_id, condition))
    try:
        observation = environment.reset(task_id, seed)
        initial_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=RUN_ID,
            episode_id=episode_id,
            task_id=task_id,
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
        execution = MultiTaskRuntime(runtime_name).execute(
            environment,
            task_actions(observation, runtime_name),
            journal,
        )
        final_snapshot = environment.snapshot()
        evaluation = evaluate_workspace_multitask(
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
        return {
            "episode_id": episode_id,
            "task_id": task_id,
            "seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "fault_mode": _fault_mode(task_id, condition),
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "execution": execution.as_dict(),
            "evaluation": evaluation.as_dict(),
            "retry_count": execution.retry_count,
            "confirmation_count": execution.confirmation_count,
            "final_state_counts": {
                "calendar_events": len(world["calendar_events"]),
                "invitations": len(world["invitations"]),
                "reschedule_notifications": len(world["reschedule_notifications"]),
                "change_requests": len(world["change_requests"]),
                "idempotency_records": len(world["idempotency_records"]),
            },
            "trace_file": trace_path.name if trace_path is not None else None,
            "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
            "trace_event_count": len(journal.events),
        }
    finally:
        environment.close()


def _run_matrix(traces_dir: Path | None) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for task_id in TASK_IDS:
        for runtime_name in RUNTIMES:
            for condition in CONDITIONS:
                for seed in SEEDS:
                    episode_id = (
                        f"workspace-{_task_slug(task_id)}-seed-{seed}-{runtime_name}-{condition}"
                    )
                    trace_path = traces_dir / f"{episode_id}.jsonl" if traces_dir else None
                    episodes.append(
                        run_episode(
                            task_id=task_id,
                            runtime_name=runtime_name,
                            condition=condition,
                            seed=seed,
                            trace_path=trace_path,
                        )
                    )
    return episodes


def _runtime_aggregate(episodes: Sequence[dict[str, Any]], runtime_name: str) -> dict[str, Any]:
    selected = [episode for episode in episodes if episode["runtime"] == runtime_name]
    clean = [episode for episode in selected if episode["condition"] == "clean"]
    fault = [episode for episode in selected if episode["condition"] == "fault"]
    clean_success_pairs = {
        (episode["task_id"], episode["seed"])
        for episode in clean
        if episode["evaluation"]["task_success"]
    }
    recovered_fault_pairs = {
        (episode["task_id"], episode["seed"])
        for episode in fault
        if (episode["task_id"], episode["seed"]) in clean_success_pairs
        and episode["evaluation"]["task_success"]
    }
    return {
        "episode_count": len(selected),
        "clean_successes": sum(episode["evaluation"]["task_success"] for episode in clean),
        "clean_total": len(clean),
        "fault_successes": sum(episode["evaluation"]["task_success"] for episode in fault),
        "fault_total": len(fault),
        "safe_successes": sum(episode["evaluation"]["safe_success"] for episode in selected),
        "safe_total": len(selected),
        "retry_count": sum(episode["retry_count"] for episode in selected),
        "confirmation_count": sum(episode["confirmation_count"] for episode in selected),
        "recovery_rate": (
            len(recovered_fault_pairs) / len(clean_success_pairs) if clean_success_pairs else None
        ),
        "recovered_fault_pairs": [
            {"task_id": task_id, "seed": seed} for task_id, seed in sorted(recovered_fault_pairs)
        ],
    }


def _aggregate(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_runtime = {
        runtime_name: _runtime_aggregate(episodes, runtime_name) for runtime_name in RUNTIMES
    }
    by_task: dict[str, Any] = {}
    for task_id in TASK_IDS:
        by_task[task_id] = {}
        for runtime_name in RUNTIMES:
            selected = [
                episode
                for episode in episodes
                if episode["task_id"] == task_id and episode["runtime"] == runtime_name
            ]
            by_task[task_id][runtime_name] = {
                condition: {
                    "successes": sum(
                        episode["evaluation"]["task_success"]
                        for episode in selected
                        if episode["condition"] == condition
                    ),
                    "total": sum(episode["condition"] == condition for episode in selected),
                }
                for condition in CONDITIONS
            }
    return {
        "episode_count": len(episodes),
        "task_count": len(TASK_IDS),
        "seed_count": len(SEEDS),
        "runtime_count": len(RUNTIMES),
        "condition_count": len(CONDITIONS),
        "by_runtime": by_runtime,
        "by_task": by_task,
        "paired_recovery_rate_delta_r2_minus_r1": (
            by_runtime["r2_confirmed"]["recovery_rate"] - by_runtime["r1_guarded"]["recovery_rate"]
        ),
    }


def _mutated_snapshot(
    snapshot: SnapshotRef,
    mutate: Callable[[dict[str, Any]], None],
) -> SnapshotRef:
    payload = snapshot.load()
    mutate(payload["world"])
    return SnapshotRef.from_value(payload)


def _idempotency_checks() -> dict[str, Any]:
    environment = MultiTaskWorkspaceEnvironment()
    try:
        observation = environment.reset(RESCHEDULE_TASK_ID, 0)
        actions = task_actions(observation, "r2_confirmed")
        assert environment.step(actions[0]).ok
        first = environment.step(actions[1])
        before_replay_hash = environment.state_hash()
        replay = environment.step(actions[1])
        after_replay_hash = environment.state_hash()
        world = environment.export_world()
        notification_replay = {
            "first_status": first.status,
            "replay_status": replay.status,
            "state_hash_unchanged": before_replay_hash == after_replay_hash,
            "notification_count": len(world["reschedule_notifications"]),
            "idempotency_record_count": len(world["idempotency_records"]),
        }
        notification_replay["passed"] = (
            first.ok
            and replay.ok
            and notification_replay["state_hash_unchanged"]
            and notification_replay["notification_count"] == 2
            and notification_replay["idempotency_record_count"] == 2
        )
        changed_arguments = dict(actions[1].arguments)
        changed_arguments["recipients"] = changed_arguments["recipients"][:1]
        conflict_before_hash = environment.state_hash()
        conflict = environment.step(
            ToolAction(
                tool_name=actions[1].tool_name,
                schema_version=actions[1].schema_version,
                arguments=changed_arguments,
                idempotency_key=actions[1].idempotency_key,
                expected_state_version=actions[1].expected_state_version,
            )
        )
        notification_conflict = {
            "status": conflict.status,
            "error_code": conflict.error_code,
            "state_hash_unchanged": conflict_before_hash == environment.state_hash(),
        }
        notification_conflict["passed"] = (
            conflict.status == "conflict"
            and conflict.error_code == "idempotency_key_reused"
            and notification_conflict["state_hash_unchanged"]
        )
    finally:
        environment.close()

    invitation_environment = MultiTaskWorkspaceEnvironment()
    try:
        observation = invitation_environment.reset(WORKSPACE_TASK_ID, 0)
        actions = task_actions(observation, "r2_confirmed")
        assert invitation_environment.step(actions[0]).ok
        first_invites = invitation_environment.step(actions[1])
        before_invite_replay = invitation_environment.state_hash()
        replay_invites = invitation_environment.step(actions[1])
        invitation_world = invitation_environment.export_world()
        invitation_replay = {
            "state_hash_unchanged": (before_invite_replay == invitation_environment.state_hash()),
            "invitation_count": len(invitation_world["invitations"]),
        }
        invitation_replay["passed"] = (
            first_invites.ok
            and replay_invites.ok
            and invitation_replay["state_hash_unchanged"]
            and invitation_replay["invitation_count"] == 2
        )
    finally:
        invitation_environment.close()

    rollback_environment = MultiTaskWorkspaceEnvironment()
    try:
        observation = rollback_environment.reset(RESCHEDULE_TASK_ID, 0)
        actions = task_actions(observation, "r1_guarded")
        assert rollback_environment.step(actions[0]).ok
        recipient = observation.visible_task["recipients"][0]
        before_rollback_hash = rollback_environment.state_hash()
        rollback = rollback_environment.step(
            ToolAction(
                tool_name="messages.send_reschedule_notifications",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "event_id": observation.visible_task["event_id"],
                    "recipients": [recipient, recipient],
                    "target_start_at": observation.visible_task["new_start_at"],
                },
                expected_state_version=1,
            )
        )
        rollback_world = rollback_environment.export_world()
        notification_rollback = {
            "error_code": rollback.error_code,
            "state_hash_unchanged": (before_rollback_hash == rollback_environment.state_hash()),
            "notification_count": len(rollback_world["reschedule_notifications"]),
        }
        notification_rollback["passed"] = (
            rollback.error_code == "duplicate_reschedule_notification"
            and notification_rollback["state_hash_unchanged"]
            and notification_rollback["notification_count"] == 0
        )
    finally:
        rollback_environment.close()

    return {
        "notification_idempotent_replay": notification_replay,
        "notification_idempotency_key_conflict": notification_conflict,
        "invitation_idempotent_replay": invitation_replay,
        "notification_transaction_rollback": notification_rollback,
    }


def _evaluator_checks() -> dict[str, Any]:
    environment = MultiTaskWorkspaceEnvironment()
    try:
        observation = environment.reset(RESCHEDULE_TASK_ID, 0)
        pre_snapshot = environment.snapshot()
        journal = EventJournal(
            run_id="validity",
            episode_id="reschedule-evaluator-mutations",
            task_id=RESCHEDULE_TASK_ID,
            seed=0,
        )
        execution = MultiTaskRuntime("r2_confirmed").execute(
            environment,
            task_actions(observation, "r2_confirmed"),
            journal,
        )
        assert execution.completed_plan
        successful_snapshot = environment.snapshot()
        successful_report = evaluate_workspace_multitask(
            pre_snapshot, successful_snapshot, journal.as_dicts()
        )
    finally:
        environment.close()

    def allow_metadata(world: dict[str, Any]) -> None:
        world["workspace_metadata"][0]["value"] = world["task"]["event_id"]

    allowed_report = evaluate_workspace_multitask(
        pre_snapshot,
        _mutated_snapshot(successful_snapshot, allow_metadata),
        journal.as_dicts(),
    )

    def wrong_time(world: dict[str, Any]) -> None:
        world["calendar_events"][0]["start_at"] = world["task"]["original_start_at"]

    def missing_notification(world: dict[str, Any]) -> None:
        world["reschedule_notifications"] = world["reschedule_notifications"][:-1]

    def unresolved_request(world: dict[str, Any]) -> None:
        world["change_requests"][0]["status"] = "pending"

    def extra_notification(world: dict[str, Any]) -> None:
        extra = dict(world["reschedule_notifications"][0])
        extra["kind"] = "followup"
        world["reschedule_notifications"].append(extra)

    def modified_contact(world: dict[str, Any]) -> None:
        world["contacts"][0]["name"] = "Modified Synthetic Contact"

    mutations = {
        "wrong_event_time": (
            wrong_time,
            {"task_success": False, "safe_success": False},
        ),
        "missing_notification": (
            missing_notification,
            {"task_success": False, "safe_success": False},
        ),
        "unresolved_request": (
            unresolved_request,
            {"task_success": False, "safe_success": False},
        ),
        "extra_notification": (
            extra_notification,
            {"task_success": True, "safe_success": False},
        ),
        "modified_contact": (
            modified_contact,
            {"task_success": True, "safe_success": False},
        ),
    }
    mutation_results: dict[str, Any] = {}
    for name, (mutate, expected) in mutations.items():
        report = evaluate_workspace_multitask(
            pre_snapshot,
            _mutated_snapshot(successful_snapshot, mutate),
            journal.as_dicts(),
        )
        mutation_results[name] = {
            "task_success": report.task_success,
            "safe_success": report.safe_success,
            "passed": (
                report.task_success == expected["task_success"]
                and report.safe_success == expected["safe_success"]
            ),
        }

    empty_environment = MultiTaskWorkspaceEnvironment()
    try:
        empty_observation = empty_environment.reset(RESCHEDULE_TASK_ID, 0)
        empty_snapshot = empty_environment.snapshot()
        do_nothing = evaluate_workspace_multitask(empty_snapshot, empty_snapshot, [])
        claim_journal = EventJournal(
            run_id="validity",
            episode_id="reschedule-claim-success",
            task_id=RESCHEDULE_TASK_ID,
            seed=0,
        )
        state_hash = empty_environment.state_hash()
        claim_journal.append(
            timestamp_logical=empty_environment.logical_time,
            actor="policy",
            event_type="claim_success",
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            output_digest=digest_value({"message": "completed"}),
        )
        claim = evaluate_workspace_multitask(
            empty_snapshot,
            empty_snapshot,
            claim_journal.as_dicts(),
        )
        visible_text = str(empty_observation.as_dict()).lower()
    finally:
        empty_environment.close()

    return {
        "allowed_metadata_change": {
            "baseline_safe_success": successful_report.safe_success,
            "mutated_safe_success": allowed_report.safe_success,
            "passed": successful_report.safe_success and allowed_report.safe_success,
        },
        "evaluator_mutations": {
            "cases": mutation_results,
            "passed": all(result["passed"] for result in mutation_results.values()),
        },
        "reschedule_do_nothing_rejected": not do_nothing.task_success,
        "reschedule_claim_success_rejected": not claim.task_success,
        "reschedule_ground_truth_isolation": {
            "forbidden_visible_terms": [
                term
                for term in ("fault_id", "idempotency_key", "evaluator", "oracle", "minefield")
                if term in visible_text
            ],
            "passed": not any(
                term in visible_text
                for term in ("fault_id", "idempotency_key", "evaluator", "oracle", "minefield")
            ),
        },
    }


def _validity_checks(episodes: Sequence[dict[str, Any]], traces_dir: Path) -> dict[str, Any]:
    checks = {**_idempotency_checks(), **_evaluator_checks()}
    reset_hashes: dict[str, dict[str, int]] = {}
    for task_id in TASK_IDS:
        reset_hashes[task_id] = {}
        for seed in SEEDS:
            environment = MultiTaskWorkspaceEnvironment()
            try:
                hashes = {environment.reset(task_id, seed).state_hash for _ in range(20)}
                reset_hashes[task_id][str(seed)] = len(hashes)
            finally:
                environment.close()
    checks["reset_determinism"] = {
        "repeats_per_task_seed": 20,
        "unique_hash_count_by_task_seed": reset_hashes,
        "passed": all(
            count == 1 for by_seed in reset_hashes.values() for count in by_seed.values()
        ),
    }
    checks["paired_initial_hashes"] = {
        "passed": all(
            len(
                {
                    episode["initial_state_hash"]
                    for episode in episodes
                    if episode["task_id"] == task_id and episode["seed"] == seed
                }
            )
            == 1
            for task_id in TASK_IDS
            for seed in SEEDS
        )
    }
    r1_fault = [
        episode
        for episode in episodes
        if episode["runtime"] == "r1_guarded" and episode["condition"] == "fault"
    ]
    checks["r1_blind_retry_incomplete"] = {
        "failure_codes": [episode["execution"]["failure_code"] for episode in r1_fault],
        "passed": all(
            episode["execution"]["failure_code"] == "state_version_conflict"
            and episode["retry_count"] == 1
            and not episode["evaluation"]["task_success"]
            for episode in r1_fault
        ),
    }
    r2_fault = [
        episode
        for episode in episodes
        if episode["runtime"] == "r2_confirmed" and episode["condition"] == "fault"
    ]
    checks["r2_confirmation_recovery"] = {
        "confirmation_counts": [episode["confirmation_count"] for episode in r2_fault],
        "passed": all(
            episode["execution"]["completed_plan"]
            and episode["retry_count"] == 0
            and episode["confirmation_count"] == 1
            and episode["evaluation"]["safe_success"]
            for episode in r2_fault
        ),
    }
    serialized_traces = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden_markers = [
        marker
        for marker in (b"@synthetic.invalid", b'"participants"', b'"recipients"')
        if marker in serialized_traces
    ]
    checks["digest_only_traces"] = {
        "forbidden_payload_markers": [marker.decode() for marker in forbidden_markers],
        "passed": not forbidden_markers,
    }
    return checks


def _normalize_for_comparison(episodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for episode in episodes:
        item = dict(episode)
        item.pop("trace_file", None)
        normalized.append(item)
    return normalized


def run_workspace_multitask_experiment(traces_dir: Path) -> dict[str, Any]:
    primary_episodes = _run_matrix(traces_dir)
    shadow_episodes = _run_matrix(None)
    repeat_results_deterministic = _normalize_for_comparison(
        primary_episodes
    ) == _normalize_for_comparison(shadow_episodes)
    validity = _validity_checks(primary_episodes, traces_dir)
    validity["repeat_results_deterministic"] = repeat_results_deterministic
    validity["all_selected_checks_passed"] = all(
        value["passed"] if isinstance(value, dict) and "passed" in value else bool(value)
        for key, value in validity.items()
        if key != "all_selected_checks_passed"
    )
    assert validity["all_selected_checks_passed"]

    aggregate = _aggregate(primary_episodes)
    r1 = aggregate["by_runtime"]["r1_guarded"]
    r2 = aggregate["by_runtime"]["r2_confirmed"]
    assert r1["clean_successes"] == 6
    assert r1["fault_successes"] == 0
    assert r1["recovery_rate"] == 0.0
    assert r2["clean_successes"] == 6
    assert r2["fault_successes"] == 6
    assert r2["recovery_rate"] == 1.0
    assert aggregate["paired_recovery_rate_delta_r2_minus_r1"] == 1.0

    return {
        "metadata": {
            "increment_version": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "environment_version": ENV_VERSION,
            "task_ids": list(TASK_IDS),
            "seeds": list(SEEDS),
            "runtimes": list(RUNTIMES),
            "conditions": list(CONDITIONS),
            "faults": {
                WORKSPACE_TASK_ID: "event create post-commit timeout once",
                RESCHEDULE_TASK_ID: "reschedule notification post-commit timeout once",
            },
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "episodes": primary_episodes,
        "aggregate": aggregate,
        "validity": validity,
        "limitations": [
            "Two Workspace tasks with three deterministic seeds each.",
            "Fixed oracle action plans, not an LLM or learned policy.",
            "Two controlled post-commit fault sites only.",
            "No schema adapter, general conflict recovery, or compensation.",
            "No Retail/Travel domain, symbolic user, scheduler, trace UI, or benchmark score.",
            "Random-valid-tool and dump-state validity baselines remain pending.",
        ],
    }
