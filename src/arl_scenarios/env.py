"""Existing Retail/Travel worlds with four registered conflict sites."""

from __future__ import annotations

from typing import Literal

from arl.core.types import StepResult, ToolAction
from arl_retail.env import SCHEMA_VERSION as RETAIL_SCHEMA_VERSION
from arl_retail.env import RetailEnvironment
from arl_scenarios.catalog import ReliabilityTaskTemplate
from arl_travel.env import RECOVERY_TASK_ID, TravelEnvironment
from arl_travel.env import SCHEMA_VERSION as TRAVEL_SCHEMA_VERSION

ConflictMode = Literal["none", "compatible_conflict", "incompatible_conflict"]


def _validate_mode(mode: ConflictMode) -> None:
    if mode not in {"none", "compatible_conflict", "incompatible_conflict"}:
        raise ValueError(f"Unknown conflict mode: {mode}")


class ScenarioRetailEnvironment(RetailEnvironment):
    """Inject one template-specific concurrent change before final resolution."""

    def __init__(self, template: ReliabilityTaskTemplate, mode: ConflictMode) -> None:
        if template.domain != "retail":
            raise ValueError("Retail scenario environment requires a Retail template")
        _validate_mode(mode)
        super().__init__(fault_mode="none")
        self.template = template
        self.conflict_mode = mode

    def _should_inject(self, action: ToolAction) -> bool:
        key = f"scenario:{self.template.template_id}"
        return bool(
            self.conflict_mode != "none"
            and self.task.task_id == self.template.task_id
            and action.tool_name == self.template.conflict_tool
            and action.schema_version == RETAIL_SCHEMA_VERSION
            and action.expected_state_version == self._state_version
            and self._fault_attempts.get(key, 0) == 0
        )

    def _inject(self, before_hash: str) -> StepResult:
        key = f"scenario:{self.template.template_id}"
        self._fault_attempts[key] = 1
        self._logical_time += 1
        self._connection.execute("BEGIN")
        try:
            if self.conflict_mode == "compatible_conflict":
                changed = self._connection.execute(
                    "UPDATE retail_metadata SET value = ? WHERE key = 'last_viewed_record'",
                    (f"scenario-observer:{self.task.seed}",),
                )
                fault_id = self.template.compatible_fault_id
            elif self.template.task_slug == "retail-purchase":
                changed = self._connection.execute(
                    "UPDATE orders SET status = 'externally_changed' WHERE order_id = ?",
                    (self.task.order_id,),
                )
                fault_id = self.template.incompatible_fault_id
            else:
                changed = self._connection.execute(
                    "UPDATE refunds SET status = 'externally_changed' WHERE refund_id = ?",
                    (self.task.refund_id,),
                )
                fault_id = self.template.incompatible_fault_id
            if changed.rowcount != 1:
                raise RuntimeError("Registered Retail conflict target does not exist")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        self._state_version += 1
        self.last_fault_id = fault_id
        return self._result(
            status="conflict",
            before_hash=before_hash,
            error_code="state_version_conflict",
        )

    def step(self, action: ToolAction) -> StepResult:
        if self._should_inject(action):
            return self._inject(self.state_hash())
        return super().step(action)


class ScenarioTravelEnvironment(TravelEnvironment):
    """Inject Travel conflicts and expose one typed booking-request read."""

    REQUEST_READ_TOOL = "travel.get_booking_request"

    def __init__(self, template: ReliabilityTaskTemplate, mode: ConflictMode) -> None:
        if template.domain != "travel":
            raise ValueError("Travel scenario environment requires a Travel template")
        _validate_mode(mode)
        fault_mode = (
            "preferred_flight_unavailable" if template.task_id == RECOVERY_TASK_ID else "none"
        )
        super().__init__(fault_mode=fault_mode)
        self.template = template
        self.conflict_mode = mode

    def _should_inject(self, action: ToolAction) -> bool:
        key = f"scenario:{self.template.template_id}"
        return bool(
            self.conflict_mode != "none"
            and self.task.task_id == self.template.task_id
            and action.tool_name == self.template.conflict_tool
            and action.schema_version == TRAVEL_SCHEMA_VERSION
            and action.expected_state_version == self._state_version
            and self._fault_attempts.get(key, 0) == 0
        )

    def _inject(self, before_hash: str) -> StepResult:
        key = f"scenario:{self.template.template_id}"
        self._fault_attempts[key] = 1
        self._logical_time += 1
        self._connection.execute("BEGIN")
        try:
            if self.conflict_mode == "compatible_conflict":
                changed = self._connection.execute(
                    "UPDATE travel_metadata SET value = ? WHERE key = 'last_viewed_booking'",
                    (f"scenario-observer:{self.task.seed}",),
                )
                fault_id = self.template.compatible_fault_id
            else:
                reservation_id = (
                    self.task.hotel_reservation_id
                    if self.template.task_slug == "travel-book"
                    else self.task.preferred_hotel_reservation_id
                )
                changed = self._connection.execute(
                    """
                    UPDATE hotel_reservations SET status = 'externally_changed'
                    WHERE reservation_id = ?
                    """,
                    (reservation_id,),
                )
                fault_id = self.template.incompatible_fault_id
            if changed.rowcount != 1:
                raise RuntimeError("Registered Travel conflict target does not exist")
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        self._state_version += 1
        self.last_fault_id = fault_id
        return self._result(
            status="conflict",
            before_hash=before_hash,
            error_code="state_version_conflict",
        )

    def _get_booking_request(self, action: ToolAction) -> StepResult:
        before_hash = self.state_hash()
        self._logical_time += 1
        self.last_fault_id = None
        if action.schema_version != TRAVEL_SCHEMA_VERSION:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="schema_version_unsupported",
            )
        if (
            action.expected_state_version is not None
            and action.expected_state_version != self._state_version
        ):
            return self._result(
                status="conflict",
                before_hash=before_hash,
                error_code="state_version_conflict",
            )
        if set(action.arguments) != {"request_id"} or not isinstance(
            action.arguments.get("request_id"), str
        ):
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="invalid_arguments",
            )
        request = self._connection.execute(
            "SELECT * FROM booking_requests WHERE request_id = ?",
            (action.arguments["request_id"],),
        ).fetchone()
        if request is None:
            return self._result(
                status="fatal_error",
                before_hash=before_hash,
                error_code="request_not_found",
            )
        return self._result(
            status="ok",
            before_hash=before_hash,
            value={"request": dict(request)},
        )

    def step(self, action: ToolAction) -> StepResult:
        if action.tool_name == self.REQUEST_READ_TOOL:
            return self._get_booking_request(action)
        if self._should_inject(action):
            return self._inject(self.state_hash())
        return super().step(action)
