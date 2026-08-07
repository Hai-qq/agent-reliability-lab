"""Deterministic random-valid-tool and dump-state validity baselines."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

from arl.core.types import Observation, ToolAction, canonical_json, digest_value
from arl.envs.workspace import SCHEMA_VERSION, WORKSPACE_TASK_ID
from arl.runtime.journal import EventJournal
from arl_multitask.env import TASK_IDS, MultiTaskWorkspaceEnvironment
from arl_multitask.evaluator import evaluate_workspace_multitask

ENVIRONMENT_SEEDS = (0, 1, 2)
POLICY_SEEDS = tuple(range(20))
RANDOM_MAX_STEPS = 5
MAX_RANDOM_TASK_SUCCESS_RATE = 0.20
MAX_RANDOM_SAFE_SUCCESS_RATE = 0.10

_WRITE_TOOLS = {
    "calendar.create_event",
    "calendar.update_event_time",
    "messages.send_invitations",
    "messages.send_reschedule_notifications",
    "workspace.resolve_change_request",
}
_EXPECTED_TOOLS = sorted(
    {
        "calendar.create_event",
        "calendar.get_event",
        "calendar.update_event_time",
        "messages.get_reschedule_notifications",
        "messages.send_invitations",
        "messages.send_reschedule_notifications",
        "workspace.resolve_change_request",
    }
)


def _action_catalog(observation: Observation, policy_seed: int) -> tuple[dict[str, Any], ...]:
    task = observation.visible_task
    if observation.task_id == WORKSPACE_TASK_ID:
        distractor_id = f"synthetic-random-event-{observation.seed}-{policy_seed}"
        distractor = {
            "event_id": distractor_id,
            "title": f"Random baseline event {policy_seed}",
            "start_at": task["start_at"],
            "organizer": task["organizer"],
            "participants": list(task["recipients"]),
        }
        return (
            {
                "name": "create_target_event",
                "tool_name": "calendar.create_event",
                "arguments": {
                    "event_id": task["event_id"],
                    "title": task["title"],
                    "start_at": task["start_at"],
                    "organizer": task["organizer"],
                    "participants": list(task["recipients"]),
                },
            },
            {
                "name": "create_distractor_event",
                "tool_name": "calendar.create_event",
                "arguments": distractor,
            },
            {
                "name": "invite_target_participants",
                "tool_name": "messages.send_invitations",
                "arguments": {
                    "event_id": task["event_id"],
                    "recipients": list(task["recipients"]),
                },
            },
            {
                "name": "invite_distractor_participants",
                "tool_name": "messages.send_invitations",
                "arguments": {
                    "event_id": distractor_id,
                    "recipients": list(task["recipients"]),
                },
            },
            {
                "name": "read_target_event",
                "tool_name": "calendar.get_event",
                "arguments": {"event_id": task["event_id"]},
            },
            {
                "name": "read_distractor_event",
                "tool_name": "calendar.get_event",
                "arguments": {"event_id": distractor_id},
            },
        )

    wrong_time = f"2030-01-{10 + observation.seed:02d}T00:00:00Z"
    return (
        {
            "name": "update_to_requested_time",
            "tool_name": "calendar.update_event_time",
            "arguments": {
                "event_id": task["event_id"],
                "new_start_at": task["new_start_at"],
            },
        },
        {
            "name": "update_to_distractor_time",
            "tool_name": "calendar.update_event_time",
            "arguments": {
                "event_id": task["event_id"],
                "new_start_at": wrong_time,
            },
        },
        {
            "name": "notify_all_participants",
            "tool_name": "messages.send_reschedule_notifications",
            "arguments": {
                "event_id": task["event_id"],
                "recipients": list(task["recipients"]),
                "target_start_at": task["new_start_at"],
            },
        },
        {
            "name": "notify_one_participant",
            "tool_name": "messages.send_reschedule_notifications",
            "arguments": {
                "event_id": task["event_id"],
                "recipients": [task["recipients"][0]],
                "target_start_at": task["new_start_at"],
            },
        },
        {
            "name": "resolve_change_request",
            "tool_name": "workspace.resolve_change_request",
            "arguments": {"request_id": task["request_id"]},
        },
        {
            "name": "read_target_event",
            "tool_name": "calendar.get_event",
            "arguments": {"event_id": task["event_id"]},
        },
        {
            "name": "read_notifications",
            "tool_name": "messages.get_reschedule_notifications",
            "arguments": {"event_id": task["event_id"]},
        },
    )


def random_valid_action(
    observation: Observation,
    *,
    state_version: int,
    policy_seed: int,
    step_index: int,
) -> tuple[str, ToolAction]:
    """Choose a schema-valid action with a stable hash-derived pseudo-random index."""
    catalog = _action_catalog(observation, policy_seed)
    material = (
        f"arl-random-valid-v1|{observation.task_id}|{observation.seed}|{policy_seed}|{step_index}"
    ).encode()
    index = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % len(catalog)
    selected = catalog[index]
    tool_name = selected["tool_name"]
    idempotency_key = None
    if tool_name in _WRITE_TOOLS:
        idempotency_key = (
            f"arl:random-valid:{observation.task_id}:{observation.seed}:"
            f"{policy_seed}:{step_index}:{selected['name']}"
        )
    return selected["name"], ToolAction(
        tool_name=tool_name,
        schema_version=SCHEMA_VERSION,
        arguments=selected["arguments"],
        idempotency_key=idempotency_key,
        expected_state_version=state_version,
    )


def run_random_valid_rollout(
    task_id: str,
    environment_seed: int,
    policy_seed: int,
    *,
    max_steps: int = RANDOM_MAX_STEPS,
) -> dict[str, Any]:
    environment = MultiTaskWorkspaceEnvironment()
    try:
        observation = environment.reset(task_id, environment_seed)
        pre_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        action_records: list[dict[str, Any]] = []
        for step_index in range(max_steps):
            choice_name, action = random_valid_action(
                observation,
                state_version=environment.state_version,
                policy_seed=policy_seed,
                step_index=step_index,
            )
            before_hash = environment.state_hash()
            result = environment.step(action)
            action_records.append(
                {
                    "step_index": step_index,
                    "choice_name": choice_name,
                    "tool_name": action.tool_name,
                    "action_digest": digest_value(action.as_dict()),
                    "status": result.status,
                    "error_code": result.error_code,
                    "state_changed": before_hash != environment.state_hash(),
                }
            )
        report = evaluate_workspace_multitask(
            pre_snapshot,
            environment.snapshot(),
            [],
        )
        serialized_record = canonical_json(action_records)
        assert "@synthetic.invalid" not in serialized_record
        assert '"recipients"' not in serialized_record
        return {
            "task_id": task_id,
            "environment_seed": environment_seed,
            "policy_seed": policy_seed,
            "max_steps": max_steps,
            "initial_state_hash": initial_hash,
            "final_state_hash": environment.state_hash(),
            "successful_tool_calls": sum(record["status"] == "ok" for record in action_records),
            "schema_error_count": sum(
                record["error_code"]
                in {"invalid_arguments", "schema_version_unsupported", "unknown_tool"}
                for record in action_records
            ),
            "task_success": report.task_success,
            "safe_success": report.safe_success,
            "actions": action_records,
        }
    finally:
        environment.close()


def run_random_valid_tool_baseline(
    *,
    environment_seeds: Sequence[int] = ENVIRONMENT_SEEDS,
    policy_seeds: Sequence[int] = POLICY_SEEDS,
    max_steps: int = RANDOM_MAX_STEPS,
) -> dict[str, Any]:
    cases = [
        run_random_valid_rollout(task_id, environment_seed, policy_seed, max_steps=max_steps)
        for task_id in TASK_IDS
        for environment_seed in environment_seeds
        for policy_seed in policy_seeds
    ]
    task_successes = sum(case["task_success"] for case in cases)
    safe_successes = sum(case["safe_success"] for case in cases)
    observed_tools = sorted({action["tool_name"] for case in cases for action in case["actions"]})
    expected_tools = _EXPECTED_TOOLS
    rollout_count = len(cases)
    result = {
        "policy": "stable SHA-256-derived open-loop schema-valid tool selection",
        "rollout_count": rollout_count,
        "task_count": len(TASK_IDS),
        "environment_seed_count": len(environment_seeds),
        "policy_seed_count": len(policy_seeds),
        "max_steps": max_steps,
        "task_successes": task_successes,
        "task_success_rate": task_successes / rollout_count,
        "safe_successes": safe_successes,
        "safe_success_rate": safe_successes / rollout_count,
        "schema_error_count": sum(case["schema_error_count"] for case in cases),
        "observed_tools": observed_tools,
        "expected_tools": expected_tools,
        "cases": cases,
    }
    result["passed"] = (
        result["schema_error_count"] == 0
        and observed_tools == expected_tools
        and result["task_success_rate"] <= MAX_RANDOM_TASK_SUCCESS_RATE
        and result["safe_success_rate"] <= MAX_RANDOM_SAFE_SUCCESS_RATE
    )
    return result


def run_dump_state_baseline() -> dict[str, Any]:
    """Prove that visible/full state dumps cannot satisfy a state evaluator by text alone."""
    cases: list[dict[str, Any]] = []
    for task_id in TASK_IDS:
        for seed in ENVIRONMENT_SEEDS:
            for mode in ("visible_observation", "full_snapshot_probe"):
                environment = MultiTaskWorkspaceEnvironment()
                try:
                    observation = environment.reset(task_id, seed)
                    pre_snapshot = environment.snapshot()
                    before_hash = environment.state_hash()
                    payload: Any
                    if mode == "visible_observation":
                        payload = observation.as_dict()
                    else:
                        payload = pre_snapshot.load()
                    journal = EventJournal(
                        run_id="workspace-validity-v0.4.0",
                        episode_id=f"dump-{mode}-{seed}-{task_id}",
                        task_id=task_id,
                        seed=seed,
                    )
                    journal.append(
                        timestamp_logical=environment.logical_time,
                        actor="baseline",
                        event_type="state_dump_submitted",
                        state_hash_before=before_hash,
                        state_hash_after=before_hash,
                        output_digest=digest_value(payload),
                    )
                    report = evaluate_workspace_multitask(
                        pre_snapshot,
                        environment.snapshot(),
                        journal.as_dicts(),
                    )
                    visible_text = canonical_json(observation.as_dict()).lower()
                    journal_text = canonical_json(journal.as_dicts())
                    cases.append(
                        {
                            "task_id": task_id,
                            "seed": seed,
                            "mode": mode,
                            "dump_digest": digest_value(payload),
                            "state_hash_unchanged": before_hash == environment.state_hash(),
                            "task_success": report.task_success,
                            "safe_success": report.safe_success,
                            "visible_internal_term_count": sum(
                                term in visible_text
                                for term in (
                                    "fault_id",
                                    "idempotency_key",
                                    "evaluator",
                                    "oracle",
                                    "minefield",
                                )
                            ),
                            "journal_contains_raw_payload": any(
                                marker in journal_text
                                for marker in ("@synthetic.invalid", '"recipients"')
                            ),
                        }
                    )
                finally:
                    environment.close()
    return {
        "case_count": len(cases),
        "cases": cases,
        "passed": all(
            case["state_hash_unchanged"]
            and not case["task_success"]
            and not case["safe_success"]
            and case["visible_internal_term_count"] == 0
            and not case["journal_contains_raw_payload"]
            for case in cases
        ),
    }
