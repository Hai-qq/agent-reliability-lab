"""R1/R2 clean/fault paired experiment for ambiguous post-commit timeouts."""

from __future__ import annotations

import hashlib
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from arl.core.types import Observation, ToolAction, digest_value
from arl.envs.workspace import SCHEMA_VERSION, WORKSPACE_TASK_ID
from arl.runtime.journal import EventJournal
from arl.runtime.loop import GuardedRuntime
from arl_r2 import __version__
from arl_r2.env import ENV_VERSION, ReliableWorkspaceEnvironment
from arl_r2.evaluator import evaluate_workspace_r2
from arl_r2.runtime import ReliableRuntime

SEEDS = (0, 1, 2)
RUNTIMES = ("r1_guarded", "r2_confirmed")
CONDITIONS = ("clean", "fault")
RUN_ID = "workspace-r2-postcommit-v0.2.0"


def workspace_actions(observation: Observation, runtime_name: str) -> list[ToolAction]:
    task = observation.visible_task
    create_key = (
        f"arl:{observation.task_id}:{observation.seed}:create-event"
        if runtime_name == "r2_confirmed"
        else None
    )
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
            idempotency_key=create_key,
            expected_state_version=0,
        ),
        ToolAction(
            tool_name="messages.send_invitations",
            schema_version=SCHEMA_VERSION,
            arguments={
                "event_id": task["event_id"],
                "recipients": list(task["recipients"]),
            },
            expected_state_version=1,
        ),
    ]


def _trace_sha256(journal: EventJournal) -> str:
    return hashlib.sha256(journal.jsonl_bytes()).hexdigest()


def run_episode(
    *,
    runtime_name: str,
    condition: str,
    seed: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    fault_mode = "none" if condition == "clean" else "event_postcommit_timeout_once"
    episode_id = f"workspace-r2-seed-{seed}-{runtime_name}-{condition}"
    environment = ReliableWorkspaceEnvironment(fault_mode=fault_mode)
    try:
        observation = environment.reset(WORKSPACE_TASK_ID, seed)
        initial_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=RUN_ID,
            episode_id=episode_id,
            task_id=WORKSPACE_TASK_ID,
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
        actions = workspace_actions(observation, runtime_name)
        if runtime_name == "r1_guarded":
            execution = GuardedRuntime(runtime_name).execute(environment, actions, journal)
            confirmation_count = 0
        else:
            execution = ReliableRuntime().execute(environment, actions, journal)
            confirmation_count = execution.confirmation_count
        final_snapshot = environment.snapshot()
        evaluation = evaluate_workspace_r2(
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
            "task_id": WORKSPACE_TASK_ID,
            "seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "execution": execution.as_dict(),
            "evaluation": evaluation.as_dict(),
            "retry_count": execution.retry_count,
            "confirmation_count": confirmation_count,
            "final_state_counts": {
                "calendar_events": len(world["calendar_events"]),
                "invitations": len(world["invitations"]),
                "idempotency_records": len(world["idempotency_records"]),
            },
            "trace_file": trace_path.name if trace_path is not None else None,
            "trace_sha256": _trace_sha256(journal),
            "trace_event_count": len(journal.events),
        }
    finally:
        environment.close()


def _run_matrix(traces_dir: Path | None) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for runtime_name in RUNTIMES:
        for condition in CONDITIONS:
            for seed in SEEDS:
                episode_id = f"workspace-r2-seed-{seed}-{runtime_name}-{condition}"
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


def _aggregate(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_runtime: dict[str, Any] = {}
    for runtime_name in RUNTIMES:
        selected = [episode for episode in episodes if episode["runtime"] == runtime_name]
        clean = [episode for episode in selected if episode["condition"] == "clean"]
        fault = [episode for episode in selected if episode["condition"] == "fault"]
        clean_successes = sum(episode["evaluation"]["task_success"] for episode in clean)
        fault_successes = sum(episode["evaluation"]["task_success"] for episode in fault)
        safe_successes = sum(episode["evaluation"]["safe_success"] for episode in selected)
        clean_success_seeds = {
            episode["seed"] for episode in clean if episode["evaluation"]["task_success"]
        }
        recovered_fault_seeds = {
            episode["seed"]
            for episode in fault
            if episode["seed"] in clean_success_seeds and episode["evaluation"]["task_success"]
        }
        by_runtime[runtime_name] = {
            "episode_count": len(selected),
            "clean_successes": clean_successes,
            "clean_total": len(clean),
            "fault_successes": fault_successes,
            "fault_total": len(fault),
            "safe_successes": safe_successes,
            "safe_total": len(selected),
            "retry_count": sum(episode["retry_count"] for episode in selected),
            "confirmation_count": sum(episode["confirmation_count"] for episode in selected),
            "recovery_rate": (
                len(recovered_fault_seeds) / len(clean_success_seeds)
                if clean_success_seeds
                else None
            ),
            "recovered_fault_seeds": sorted(recovered_fault_seeds),
        }
    return {
        "episode_count": len(episodes),
        "task_count": 1,
        "seed_count": len(SEEDS),
        "runtime_count": len(RUNTIMES),
        "condition_count": len(CONDITIONS),
        "by_runtime": by_runtime,
        "paired_recovery_rate_delta_r2_minus_r1": (
            by_runtime["r2_confirmed"]["recovery_rate"] - by_runtime["r1_guarded"]["recovery_rate"]
        ),
    }


def _direct_validity_checks() -> dict[str, Any]:
    postcommit_environment = ReliableWorkspaceEnvironment(
        fault_mode="event_postcommit_timeout_once"
    )
    try:
        observation = postcommit_environment.reset(WORKSPACE_TASK_ID, 0)
        action = workspace_actions(observation, "r2_confirmed")[0]
        before_hash = postcommit_environment.state_hash()
        result = postcommit_environment.step(action)
        world = postcommit_environment.export_world()
        postcommit = {
            "error_code": result.error_code,
            "state_hash_changed": before_hash != postcommit_environment.state_hash(),
            "state_version": postcommit_environment.state_version,
            "calendar_event_count": len(world["calendar_events"]),
            "idempotency_record_count": len(world["idempotency_records"]),
        }
        postcommit["passed"] = (
            result.status == "retryable_error"
            and result.error_code == "tool_timeout_postcommit"
            and postcommit["state_hash_changed"]
            and postcommit["state_version"] == 1
            and postcommit["calendar_event_count"] == 1
            and postcommit["idempotency_record_count"] == 1
        )
    finally:
        postcommit_environment.close()

    replay_environment = ReliableWorkspaceEnvironment()
    try:
        observation = replay_environment.reset(WORKSPACE_TASK_ID, 0)
        action = workspace_actions(observation, "r2_confirmed")[0]
        first = replay_environment.step(action)
        before_replay_hash = replay_environment.state_hash()
        replay = replay_environment.step(action)
        after_replay_hash = replay_environment.state_hash()
        world = replay_environment.export_world()
        idempotent_replay = {
            "first_status": first.status,
            "replay_status": replay.status,
            "state_hash_unchanged": before_replay_hash == after_replay_hash,
            "state_version": replay_environment.state_version,
            "calendar_event_count": len(world["calendar_events"]),
            "idempotency_record_count": len(world["idempotency_records"]),
        }
        idempotent_replay["passed"] = (
            first.ok
            and replay.ok
            and idempotent_replay["state_hash_unchanged"]
            and idempotent_replay["state_version"] == 1
            and idempotent_replay["calendar_event_count"] == 1
            and idempotent_replay["idempotency_record_count"] == 1
        )

        changed_arguments = dict(action.arguments)
        changed_arguments["title"] = "Conflicting synthetic title"
        conflict_before_hash = replay_environment.state_hash()
        conflict = replay_environment.step(
            ToolAction(
                tool_name=action.tool_name,
                schema_version=action.schema_version,
                arguments=changed_arguments,
                idempotency_key=action.idempotency_key,
                expected_state_version=action.expected_state_version,
            )
        )
        key_conflict = {
            "status": conflict.status,
            "error_code": conflict.error_code,
            "state_hash_unchanged": conflict_before_hash == replay_environment.state_hash(),
        }
        key_conflict["passed"] = (
            conflict.status == "conflict"
            and conflict.error_code == "idempotency_key_reused"
            and key_conflict["state_hash_unchanged"]
        )
    finally:
        replay_environment.close()

    snapshot_environment = ReliableWorkspaceEnvironment()
    try:
        observation = snapshot_environment.reset(WORKSPACE_TASK_ID, 0)
        initial_snapshot = snapshot_environment.snapshot()
        initial_hash = snapshot_environment.state_hash()
        snapshot_environment.step(workspace_actions(observation, "r2_confirmed")[0])
        changed_hash = snapshot_environment.state_hash()
        snapshot_environment.restore(initial_snapshot)
        restored_world = snapshot_environment.export_world()
        snapshot_restore = {
            "initial_hash": initial_hash,
            "changed_hash": changed_hash,
            "restored_hash": snapshot_environment.state_hash(),
            "idempotency_record_count": len(restored_world["idempotency_records"]),
        }
        snapshot_restore["passed"] = (
            initial_hash != changed_hash
            and initial_hash == snapshot_restore["restored_hash"]
            and snapshot_restore["idempotency_record_count"] == 0
        )
    finally:
        snapshot_environment.close()

    return {
        "postcommit_fault_commits": postcommit,
        "idempotent_replay": idempotent_replay,
        "idempotency_key_conflict": key_conflict,
        "snapshot_restore_with_idempotency": snapshot_restore,
    }


def _validity_checks(episodes: Sequence[dict[str, Any]], traces_dir: Path) -> dict[str, Any]:
    checks = _direct_validity_checks()
    reset_hashes: dict[str, list[str]] = {}
    for seed in SEEDS:
        environment = ReliableWorkspaceEnvironment()
        try:
            reset_hashes[str(seed)] = sorted(
                {environment.reset(WORKSPACE_TASK_ID, seed).state_hash for _ in range(20)}
            )
        finally:
            environment.close()
    checks["reset_determinism"] = {
        "repeats_per_seed": 20,
        "unique_hash_count_by_seed": {seed: len(hashes) for seed, hashes in reset_hashes.items()},
        "passed": all(len(hashes) == 1 for hashes in reset_hashes.values()),
    }
    checks["paired_initial_hashes"] = {
        "passed": all(
            len({episode["initial_state_hash"] for episode in episodes if episode["seed"] == seed})
            == 1
            for seed in SEEDS
        )
    }
    r1_fault = [
        episode
        for episode in episodes
        if episode["runtime"] == "r1_guarded" and episode["condition"] == "fault"
    ]
    checks["r1_blind_retry_is_incomplete"] = {
        "failure_codes": [episode["execution"]["failure_code"] for episode in r1_fault],
        "event_counts": [episode["final_state_counts"]["calendar_events"] for episode in r1_fault],
        "invitation_counts": [episode["final_state_counts"]["invitations"] for episode in r1_fault],
        "passed": all(
            episode["execution"]["failure_code"] == "state_version_conflict"
            and episode["final_state_counts"]["calendar_events"] == 1
            and episode["final_state_counts"]["invitations"] == 0
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
        "retry_counts": [episode["retry_count"] for episode in r2_fault],
        "passed": all(
            episode["execution"]["completed_plan"]
            and episode["confirmation_count"] == 1
            and episode["retry_count"] == 0
            and episode["evaluation"]["safe_success"]
            and episode["final_state_counts"]["calendar_events"] == 1
            and episode["final_state_counts"]["invitations"] == 2
            for episode in r2_fault
        ),
    }
    serialized_traces = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden_payload_markers = [
        marker
        for marker in (b"@synthetic.invalid", b'"participants"', b'"recipients"')
        if marker in serialized_traces
    ]
    checks["digest_only_traces"] = {
        "forbidden_payload_markers": [marker.decode() for marker in forbidden_payload_markers],
        "passed": not forbidden_payload_markers,
    }
    observation_environment = ReliableWorkspaceEnvironment(
        fault_mode="event_postcommit_timeout_once"
    )
    try:
        observation = observation_environment.reset(WORKSPACE_TASK_ID, 0)
        observation_text = str(observation.as_dict()).lower()
        forbidden_visible_terms = [
            term
            for term in ("fault_id", "postcommit", "idempotency_key", "evaluator", "oracle")
            if term in observation_text
        ]
    finally:
        observation_environment.close()
    checks["fault_and_ground_truth_isolation"] = {
        "forbidden_visible_terms": forbidden_visible_terms,
        "passed": not forbidden_visible_terms,
    }
    return checks


def _normalize_for_comparison(episodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for episode in episodes:
        item = dict(episode)
        item.pop("trace_file", None)
        normalized.append(item)
    return normalized


def run_workspace_r2_experiment(traces_dir: Path) -> dict[str, Any]:
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
    assert r1["clean_successes"] == 3
    assert r1["fault_successes"] == 0
    assert r1["recovery_rate"] == 0.0
    assert r2["clean_successes"] == 3
    assert r2["fault_successes"] == 3
    assert r2["recovery_rate"] == 1.0
    assert aggregate["paired_recovery_rate_delta_r2_minus_r1"] == 1.0

    return {
        "metadata": {
            "r2_increment_version": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "environment_version": ENV_VERSION,
            "task_id": WORKSPACE_TASK_ID,
            "seeds": list(SEEDS),
            "runtimes": list(RUNTIMES),
            "conditions": list(CONDITIONS),
            "fault": "single post-commit timeout after the first event transaction commits",
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "episodes": primary_episodes,
        "aggregate": aggregate,
        "validity": validity,
        "limitations": [
            "One Workspace task with three deterministic seeds.",
            "A fixed oracle action plan, not an LLM or learned policy.",
            "R2 idempotency currently covers calendar.create_event only.",
            "The controlled post-commit fault occurs only on the first event write.",
            "No schema adaptation, conflict recovery, compensation, or parallel scheduler.",
            "No Retail/Travel domains, user simulator, trace UI, or benchmark score.",
        ],
    }
