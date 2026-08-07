"""Workspace environment with deterministic concurrent-state conflicts."""

from __future__ import annotations

from typing import Literal

from arl.core.types import Observation, SnapshotRef, StepResult, ToolAction
from arl_multitask.env import (
    ENV_VERSION as MULTITASK_ENV_VERSION,
)
from arl_multitask.env import (
    RESCHEDULE_TASK_ID,
    MultiTaskWorkspaceEnvironment,
)

ENV_VERSION = "workspace-conflict-v0.8.0"
UNRELATED_CONFLICT_FAULT_ID = "fault.workspace.concurrent_metadata_change_once"
TARGET_CONFLICT_FAULT_ID = "fault.workspace.concurrent_event_time_change_once"

ConflictMode = Literal[
    "none",
    "unrelated_state_change_before_update_once",
    "target_state_change_before_update_once",
]


def conflicting_start_for_seed(seed: int) -> str:
    """Return a deterministic third-party time distinct from both task times."""
    return f"2026-09-{20 + seed:02d}T18:00:00Z"


class ConflictWorkspaceEnvironment(MultiTaskWorkspaceEnvironment):
    """Inject one atomic concurrent change before a compare-and-set write."""

    def __init__(self, conflict_mode: ConflictMode = "none") -> None:
        if conflict_mode not in {
            "none",
            "unrelated_state_change_before_update_once",
            "target_state_change_before_update_once",
        }:
            raise ValueError(f"Unknown conflict mode: {conflict_mode}")
        super().__init__(fault_mode="none")
        self.conflict_mode = conflict_mode

    def reset(self, task_id: str, seed: int) -> Observation:
        observation = super().reset(task_id, seed)
        return Observation(
            task_id=observation.task_id,
            seed=observation.seed,
            env_version=ENV_VERSION,
            state_version=observation.state_version,
            timestamp_logical=observation.timestamp_logical,
            state_hash=self.state_hash(),
            visible_task=observation.visible_task,
        )

    def export_world(self) -> dict[str, object]:
        world = super().export_world()
        world["env_version"] = ENV_VERSION
        return world

    def snapshot(self) -> SnapshotRef:
        payload = super().snapshot().load()
        payload["world"]["env_version"] = ENV_VERSION
        return SnapshotRef.from_value(payload)

    def restore(self, snapshot: SnapshotRef) -> None:
        payload = snapshot.load()
        if payload["world"]["env_version"] != ENV_VERSION:
            raise ValueError("Snapshot environment version mismatch")
        payload["world"]["env_version"] = MULTITASK_ENV_VERSION
        super().restore(SnapshotRef.from_value(payload))
        self.last_fault_id = None

    def _should_inject(self, action: ToolAction) -> bool:
        if self.conflict_mode == "none" or self.task.task_id != RESCHEDULE_TASK_ID:
            return False
        if action.tool_name != "calendar.update_event_time":
            return False
        if action.expected_state_version != self._state_version:
            return False
        attempts = self._fault_attempts.get("v08.concurrent_update", 0)
        return attempts == 0

    def _inject_concurrent_change(self, before_hash: str) -> StepResult:
        self._fault_attempts["v08.concurrent_update"] = 1
        self._logical_time += 1
        next_state_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            if self.conflict_mode == "unrelated_state_change_before_update_once":
                self._connection.execute(
                    "UPDATE workspace_metadata SET value = ? WHERE key = ?",
                    (f"external-observer:{self.task.seed}", "last_viewed_event_id"),
                )
                fault_id = UNRELATED_CONFLICT_FAULT_ID
            else:
                self._connection.execute(
                    "UPDATE calendar_events SET start_at = ? WHERE event_id = ?",
                    (conflicting_start_for_seed(self.task.seed), self.task.event_id),
                )
                fault_id = TARGET_CONFLICT_FAULT_ID
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        self._state_version = next_state_version
        self.last_fault_id = fault_id
        return self._result(
            status="conflict",
            before_hash=before_hash,
            error_code="state_version_conflict",
        )

    def step(self, action: ToolAction) -> StepResult:
        if self._should_inject(action):
            return self._inject_concurrent_change(self.state_hash())
        return super().step(action)
