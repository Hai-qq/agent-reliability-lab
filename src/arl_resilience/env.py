"""Retail and Travel environments with deterministic concurrent-state changes."""

from __future__ import annotations

from typing import Literal

from arl.core.types import Observation, SnapshotRef, StepResult, ToolAction
from arl_retail.env import ENV_VERSION as RETAIL_ENV_VERSION
from arl_retail.env import PURCHASE_TASK_ID, RetailEnvironment
from arl_travel.env import ENV_VERSION as TRAVEL_ENV_VERSION
from arl_travel.env import RECOVERY_TASK_ID, TravelEnvironment

ENV_VERSION = "cross-domain-resilience-v0.9.0"

RETAIL_METADATA_CONFLICT_FAULT_ID = "fault.retail.concurrent_metadata_change_once"
RETAIL_ORDER_CONFLICT_FAULT_ID = "fault.retail.concurrent_order_status_change_once"
TRAVEL_METADATA_CONFLICT_FAULT_ID = "fault.travel.concurrent_metadata_change_once"
TRAVEL_RESERVATION_CONFLICT_FAULT_ID = "fault.travel.concurrent_reservation_status_change_once"

ConflictMode = Literal["none", "compatible_conflict", "incompatible_conflict"]


def _validate_mode(conflict_mode: ConflictMode) -> None:
    if conflict_mode not in {"none", "compatible_conflict", "incompatible_conflict"}:
        raise ValueError(f"Unknown conflict mode: {conflict_mode}")


class ResilientRetailEnvironment(RetailEnvironment):
    """Inject one concurrent change before purchase-request resolution."""

    def __init__(self, conflict_mode: ConflictMode = "none") -> None:
        _validate_mode(conflict_mode)
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
        return SnapshotRef.from_value(super().snapshot().load())

    def restore(self, snapshot: SnapshotRef) -> None:
        payload = snapshot.load()
        if payload["world"]["env_version"] != ENV_VERSION:
            raise ValueError("Snapshot environment version mismatch")
        payload["world"]["env_version"] = RETAIL_ENV_VERSION
        super().restore(SnapshotRef.from_value(payload))
        self.last_fault_id = None

    def _should_inject(self, action: ToolAction) -> bool:
        return bool(
            self.conflict_mode != "none"
            and self.task.task_id == PURCHASE_TASK_ID
            and action.tool_name == "retail.resolve_purchase_request"
            and action.expected_state_version == self._state_version
            and self._fault_attempts.get("v09.retail.resolve", 0) == 0
        )

    def _inject_concurrent_change(self, before_hash: str) -> StepResult:
        self._fault_attempts["v09.retail.resolve"] = 1
        self._logical_time += 1
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            if self.conflict_mode == "compatible_conflict":
                self._connection.execute(
                    "UPDATE retail_metadata SET value = ? WHERE key = 'last_viewed_record'",
                    (f"external-observer:{self.task.seed}",),
                )
                fault_id = RETAIL_METADATA_CONFLICT_FAULT_ID
            else:
                self._connection.execute(
                    "UPDATE orders SET status = 'externally_changed' WHERE order_id = ?",
                    (self.task.order_id,),
                )
                fault_id = RETAIL_ORDER_CONFLICT_FAULT_ID
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        self._state_version = next_version
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


class ResilientTravelEnvironment(TravelEnvironment):
    """Inject one concurrent change before a registered hotel compensation."""

    def __init__(self, conflict_mode: ConflictMode = "none") -> None:
        _validate_mode(conflict_mode)
        super().__init__(fault_mode="preferred_flight_unavailable")
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
        return SnapshotRef.from_value(super().snapshot().load())

    def restore(self, snapshot: SnapshotRef) -> None:
        payload = snapshot.load()
        if payload["world"]["env_version"] != ENV_VERSION:
            raise ValueError("Snapshot environment version mismatch")
        payload["world"]["env_version"] = TRAVEL_ENV_VERSION
        super().restore(SnapshotRef.from_value(payload))
        self.last_fault_id = None

    def _should_inject(self, action: ToolAction) -> bool:
        return bool(
            self.conflict_mode != "none"
            and self.task.task_id == RECOVERY_TASK_ID
            and action.tool_name == "hotels.cancel"
            and action.expected_state_version == self._state_version
            and self._fault_attempts.get("v09.travel.compensate", 0) == 0
        )

    def _inject_concurrent_change(self, before_hash: str) -> StepResult:
        self._fault_attempts["v09.travel.compensate"] = 1
        self._logical_time += 1
        next_version = self._state_version + 1
        self._connection.execute("BEGIN")
        try:
            if self.conflict_mode == "compatible_conflict":
                self._connection.execute(
                    "UPDATE travel_metadata SET value = ? WHERE key = 'last_viewed_booking'",
                    (f"external-observer:{self.task.seed}",),
                )
                fault_id = TRAVEL_METADATA_CONFLICT_FAULT_ID
            else:
                self._connection.execute(
                    """
                    UPDATE hotel_reservations SET status = 'externally_changed'
                    WHERE reservation_id = ?
                    """,
                    (self.task.preferred_hotel_reservation_id,),
                )
                fault_id = TRAVEL_RESERVATION_CONFLICT_FAULT_ID
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        self._state_version = next_version
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
