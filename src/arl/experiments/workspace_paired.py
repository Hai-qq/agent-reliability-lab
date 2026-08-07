"""Clean/fault paired experiment for the first ARL Workspace task."""

from __future__ import annotations

import hashlib
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from arl import __version__
from arl.core.types import Observation, ToolAction, digest_value
from arl.envs.workspace import (
    ENV_VERSION,
    SCHEMA_VERSION,
    WORKSPACE_TASK_ID,
    WorkspaceEnvironment,
)
from arl.evaluators.workspace import evaluate_workspace
from arl.runtime.journal import EventJournal
from arl.runtime.loop import GuardedRuntime

SEEDS = (0, 1, 2)
RUNTIMES = ("r0_raw", "r1_guarded")
CONDITIONS = ("clean", "fault")
RUN_ID = "workspace-paired-v0.1.0"


def oracle_actions(observation: Observation) -> list[ToolAction]:
    task = observation.visible_task
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
    fault_mode = "none" if condition == "clean" else "invites_precommit_timeout_once"
    episode_id = f"workspace-seed-{seed}-{runtime_name}-{condition}"
    environment = WorkspaceEnvironment(fault_mode=fault_mode)
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
        execution = GuardedRuntime(runtime_name).execute(
            environment,
            oracle_actions(observation),
            journal,
        )
        final_snapshot = environment.snapshot()
        evaluation = evaluate_workspace(
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
            "final_state_counts": {
                "calendar_events": len(world["calendar_events"]),
                "invitations": len(world["invitations"]),
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
                episode_id = f"workspace-seed-{seed}-{runtime_name}-{condition}"
                trace_path = traces_dir / f"{episode_id}.jsonl" if traces_dir is not None else None
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
        retry_count = sum(episode["retry_count"] for episode in selected)
        paired_clean_success_seeds = {
            episode["seed"] for episode in clean if episode["evaluation"]["task_success"]
        }
        recovered_fault_seeds = {
            episode["seed"]
            for episode in fault
            if episode["seed"] in paired_clean_success_seeds
            and episode["evaluation"]["task_success"]
        }
        denominator = len(paired_clean_success_seeds)
        by_runtime[runtime_name] = {
            "episode_count": len(selected),
            "clean_successes": clean_successes,
            "clean_total": len(clean),
            "fault_successes": fault_successes,
            "fault_total": len(fault),
            "safe_successes": safe_successes,
            "safe_total": len(selected),
            "retry_count": retry_count,
            "recovery_rate": len(recovered_fault_seeds) / denominator if denominator else None,
            "recovered_fault_seeds": sorted(recovered_fault_seeds),
        }
    return {
        "episode_count": len(episodes),
        "task_count": 1,
        "seed_count": len(SEEDS),
        "runtime_count": len(RUNTIMES),
        "condition_count": len(CONDITIONS),
        "by_runtime": by_runtime,
        "paired_recovery_rate_delta_r1_minus_r0": (
            by_runtime["r1_guarded"]["recovery_rate"] - by_runtime["r0_raw"]["recovery_rate"]
        ),
    }


def _validity_checks(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    reset_hashes: dict[str, list[str]] = {}
    for seed in SEEDS:
        environment = WorkspaceEnvironment()
        try:
            hashes = [environment.reset(WORKSPACE_TASK_ID, seed).state_hash for _ in range(20)]
            reset_hashes[str(seed)] = sorted(set(hashes))
        finally:
            environment.close()

    snapshot_environment = WorkspaceEnvironment()
    try:
        observation = snapshot_environment.reset(WORKSPACE_TASK_ID, 0)
        initial_hash = snapshot_environment.state_hash()
        snapshot = snapshot_environment.snapshot()
        snapshot_environment.step(oracle_actions(observation)[0])
        changed_hash = snapshot_environment.state_hash()
        snapshot_environment.restore(snapshot)
        restored_hash = snapshot_environment.state_hash()
    finally:
        snapshot_environment.close()

    rollback_environment = WorkspaceEnvironment()
    try:
        rollback_observation = rollback_environment.reset(WORKSPACE_TASK_ID, 0)
        rollback_environment.step(oracle_actions(rollback_observation)[0])
        rollback_before = rollback_environment.state_hash()
        recipient = rollback_observation.visible_task["recipients"][0]
        rollback_result = rollback_environment.step(
            ToolAction(
                tool_name="messages.send_invitations",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "event_id": rollback_observation.visible_task["event_id"],
                    "recipients": [recipient, recipient],
                },
                expected_state_version=1,
            )
        )
        rollback_after = rollback_environment.state_hash()
        rollback_invitation_count = len(rollback_environment.export_world()["invitations"])
    finally:
        rollback_environment.close()

    empty_environment = WorkspaceEnvironment()
    try:
        empty_observation = empty_environment.reset(WORKSPACE_TASK_ID, 0)
        empty_pre = empty_environment.snapshot()
        do_nothing_report = evaluate_workspace(empty_pre, empty_environment.snapshot(), [])
        claim_journal = EventJournal(
            run_id="validity",
            episode_id="claim-success",
            task_id=WORKSPACE_TASK_ID,
            seed=0,
        )
        current_hash = empty_environment.state_hash()
        claim_journal.append(
            timestamp_logical=empty_environment.logical_time,
            actor="policy",
            event_type="claim_success",
            state_hash_before=current_hash,
            state_hash_after=current_hash,
            output_digest=digest_value({"message": "completed"}),
        )
        claim_report = evaluate_workspace(
            empty_pre,
            empty_environment.snapshot(),
            claim_journal.as_dicts(),
        )
        visible_key_text = " ".join(empty_observation.visible_task).lower()
    finally:
        empty_environment.close()

    mutation_environment = WorkspaceEnvironment()
    try:
        mutation_observation = mutation_environment.reset(WORKSPACE_TASK_ID, 0)
        mutation_pre = mutation_environment.snapshot()
        mutation_journal = EventJournal(
            run_id="validity",
            episode_id="collateral-mutation",
            task_id=WORKSPACE_TASK_ID,
            seed=0,
        )
        GuardedRuntime("r1_guarded").execute(
            mutation_environment,
            oracle_actions(mutation_observation),
            mutation_journal,
        )
        mutation_environment.step(
            ToolAction(
                tool_name="calendar.create_event",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "event_id": "forbidden-extra-event",
                    "title": "Unrequested synthetic event",
                    "start_at": "2026-09-30T12:00:00Z",
                    "organizer": "owner@synthetic.invalid",
                    "participants": [],
                },
                expected_state_version=2,
            )
        )
        mutation_report = evaluate_workspace(
            mutation_pre,
            mutation_environment.snapshot(),
            mutation_journal.as_dicts(),
        )
    finally:
        mutation_environment.close()

    paired_initial_hashes_match = all(
        len({episode["initial_state_hash"] for episode in episodes if episode["seed"] == seed}) == 1
        for seed in SEEDS
    )
    checks = {
        "reset_determinism": {
            "repeats_per_seed": 20,
            "unique_hash_count_by_seed": {
                seed: len(hashes) for seed, hashes in reset_hashes.items()
            },
            "passed": all(len(hashes) == 1 for hashes in reset_hashes.values()),
        },
        "snapshot_restore": {
            "initial_hash": initial_hash,
            "changed_hash": changed_hash,
            "restored_hash": restored_hash,
            "passed": initial_hash != changed_hash and initial_hash == restored_hash,
        },
        "transaction_rollback": {
            "error_code": rollback_result.error_code,
            "state_hash_before": rollback_before,
            "state_hash_after": rollback_after,
            "invitation_count_after": rollback_invitation_count,
            "passed": (
                rollback_result.error_code == "duplicate_invitation"
                and rollback_before == rollback_after
                and rollback_invitation_count == 0
            ),
        },
        "do_nothing_rejected": not do_nothing_report.task_success,
        "claim_success_rejected": not claim_report.task_success,
        "collateral_mutation": {
            "task_success": mutation_report.task_success,
            "safe_success": mutation_report.safe_success,
            "minefields": list(mutation_report.minefields_triggered),
            "passed": (
                mutation_report.task_success
                and not mutation_report.safe_success
                and "extra_calendar_event" in mutation_report.minefields_triggered
            ),
        },
        "ground_truth_isolation": {
            "forbidden_visible_keys": [
                key
                for key in ("oracle", "expected", "evaluator", "hidden", "minefield")
                if key in visible_key_text
            ],
            "passed": not any(
                key in visible_key_text
                for key in ("oracle", "expected", "evaluator", "hidden", "minefield")
            ),
        },
        "paired_initial_hashes_match": paired_initial_hashes_match,
    }
    assert checks["reset_determinism"]["passed"]
    assert checks["snapshot_restore"]["passed"]
    assert checks["transaction_rollback"]["passed"]
    assert checks["do_nothing_rejected"]
    assert checks["claim_success_rejected"]
    assert checks["collateral_mutation"]["passed"]
    assert checks["ground_truth_isolation"]["passed"]
    assert checks["paired_initial_hashes_match"]
    return checks


def _normalize_for_comparison(episodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for episode in episodes:
        item = dict(episode)
        item.pop("trace_file", None)
        normalized.append(item)
    return normalized


def run_workspace_paired_experiment(traces_dir: Path) -> dict[str, Any]:
    primary_episodes = _run_matrix(traces_dir)
    shadow_episodes = _run_matrix(None)
    repeat_results_deterministic = _normalize_for_comparison(
        primary_episodes
    ) == _normalize_for_comparison(shadow_episodes)
    validity = _validity_checks(primary_episodes)
    validity["repeat_results_deterministic"] = repeat_results_deterministic
    validity["all_selected_checks_passed"] = all(
        (value["passed"] if isinstance(value, dict) and "passed" in value else bool(value))
        for key, value in validity.items()
        if key != "all_selected_checks_passed"
    )
    assert repeat_results_deterministic
    assert validity["all_selected_checks_passed"]

    aggregate = _aggregate(primary_episodes)
    r0 = aggregate["by_runtime"]["r0_raw"]
    r1 = aggregate["by_runtime"]["r1_guarded"]
    assert r0["clean_successes"] == 3
    assert r0["fault_successes"] == 0
    assert r0["recovery_rate"] == 0.0
    assert r1["clean_successes"] == 3
    assert r1["fault_successes"] == 3
    assert r1["recovery_rate"] == 1.0
    assert aggregate["paired_recovery_rate_delta_r1_minus_r0"] == 1.0

    return {
        "metadata": {
            "arl_version": __version__,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "environment_version": ENV_VERSION,
            "task_id": WORKSPACE_TASK_ID,
            "seeds": list(SEEDS),
            "runtimes": list(RUNTIMES),
            "conditions": list(CONDITIONS),
            "fault": "single pre-commit timeout on the first invitation attempt",
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
            "R1 covers typed errors, bounded retry, and result validation only.",
            "No R2 idempotency, schema adaptation, conflict recovery, or compensation.",
            "No Retail/Travel domains, user simulator, parallel scheduler, or trace UI.",
        ],
    }
