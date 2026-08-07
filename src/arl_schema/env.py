"""Local synthetic Travel wrapper exposing controlled public schema drift."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any, Literal

from arl.core.types import Observation, SnapshotRef, StepResult, ToolAction
from arl_travel.env import SCHEMA_VERSION, TravelEnvironment

ENV_VERSION = "schema-adapter-v0.7.0"
DRIFT_SCHEMA_VERSION = "2.0"

FLIGHT_ACTION_FAULT_ID = "fault.schema.flights_book.action_v2"
HOTEL_RESULT_FAULT_ID = "fault.schema.hotels_book.result_v2"

SchemaDriftMode = Literal[
    "none",
    "flight_action_schema_v2",
    "hotel_result_schema_v2",
]

_ACTION_FIELDS_V1: dict[str, tuple[str, ...]] = {
    "flights.book": (
        "booking_id",
        "flight_id",
        "user_id",
        "payment_id",
        "confirmed_nonrefundable",
    ),
    "hotels.book": (
        "reservation_id",
        "hotel_id",
        "user_id",
        "payment_id",
        "confirmed_nonrefundable",
    ),
    "travel.resolve_booking_request": (
        "request_id",
        "flight_booking_id",
        "hotel_reservation_id",
    ),
}

_RESULT_FIELDS_V1: dict[str, tuple[str, ...]] = {
    "flights.book": ("booked_flight_id", "flight_booking_id", "price_cents"),
    "hotels.book": ("booked_hotel_id", "hotel_reservation_id", "price_cents"),
    "travel.resolve_booking_request": ("resolved_request_id",),
}


class SchemaDriftEnvironment:
    """Expose one registered contract difference while retaining Travel state semantics."""

    def __init__(self, drift_mode: SchemaDriftMode = "none") -> None:
        if drift_mode not in {
            "none",
            "flight_action_schema_v2",
            "hotel_result_schema_v2",
        }:
            raise ValueError(f"Unknown schema drift mode: {drift_mode}")
        self.drift_mode = drift_mode
        self.last_fault_id: str | None = None
        self._base = TravelEnvironment(fault_mode="none")

    @property
    def task(self) -> Any:
        return self._base.task

    @property
    def state_version(self) -> int:
        return self._base.state_version

    @property
    def logical_time(self) -> int:
        return self._base.logical_time

    def close(self) -> None:
        self._base.close()

    def reset(self, task_id: str, seed: int) -> Observation:
        observation = self._base.reset(task_id, seed)
        self.last_fault_id = None
        return replace(observation, env_version=ENV_VERSION)

    def export_world(self) -> dict[str, Any]:
        return self._base.export_world()

    def state_hash(self) -> str:
        return self._base.state_hash()

    def snapshot(self) -> SnapshotRef:
        return self._base.snapshot()

    def restore(self, snapshot: SnapshotRef) -> None:
        self._base.restore(snapshot)
        self.last_fault_id = None

    def describe_tool(self, tool_name: str) -> dict[str, Any]:
        if tool_name not in _ACTION_FIELDS_V1:
            raise ValueError(f"Unknown tool descriptor: {tool_name}")
        action_version = SCHEMA_VERSION
        action_fields = _ACTION_FIELDS_V1[tool_name]
        result_version = SCHEMA_VERSION
        result_fields = _RESULT_FIELDS_V1[tool_name]
        if self.drift_mode == "flight_action_schema_v2" and tool_name == "flights.book":
            action_version = DRIFT_SCHEMA_VERSION
            action_fields = (
                "reservation_ref",
                "flight_ref",
                "traveler_ref",
                "payment_ref",
                "fare_acknowledged",
            )
        if self.drift_mode == "hotel_result_schema_v2" and tool_name == "hotels.book":
            result_version = DRIFT_SCHEMA_VERSION
            result_fields = ("result_schema_version", "reservation", "amount")
        descriptor = {
            "tool_name": tool_name,
            "action": {
                "schema_version": action_version,
                "required_fields": list(action_fields),
                "additional_fields": False,
            },
            "result": {
                "schema_version": result_version,
                "required_fields": list(result_fields),
                "additional_fields": False,
            },
        }
        return deepcopy(descriptor)

    @staticmethod
    def _valid_flight_v2(arguments: dict[str, Any]) -> bool:
        required = {
            "reservation_ref",
            "flight_ref",
            "traveler_ref",
            "payment_ref",
            "fare_acknowledged",
        }
        return bool(
            set(arguments) == required
            and all(
                isinstance(arguments.get(key), str) and bool(arguments[key])
                for key in required - {"fare_acknowledged"}
            )
            and isinstance(arguments.get("fare_acknowledged"), bool)
        )

    def _safe_rejection(self, action: ToolAction, error_code: str) -> StepResult:
        rejected = self._base.step(
            ToolAction(
                tool_name=action.tool_name,
                schema_version="adapter-rejected",
                arguments={},
                expected_state_version=action.expected_state_version,
            )
        )
        return replace(rejected, error_code=error_code)

    @staticmethod
    def _translate_flight_v2(action: ToolAction) -> ToolAction:
        arguments = action.arguments
        return ToolAction(
            tool_name=action.tool_name,
            schema_version=SCHEMA_VERSION,
            arguments={
                "booking_id": arguments["reservation_ref"],
                "flight_id": arguments["flight_ref"],
                "user_id": arguments["traveler_ref"],
                "payment_id": arguments["payment_ref"],
                "confirmed_nonrefundable": arguments["fare_acknowledged"],
            },
            idempotency_key=action.idempotency_key,
            expected_state_version=action.expected_state_version,
        )

    @staticmethod
    def _hotel_result_v2(result: StepResult) -> StepResult:
        assert result.value is not None
        return replace(
            result,
            value={
                "result_schema_version": DRIFT_SCHEMA_VERSION,
                "reservation": {
                    "ref": result.value["hotel_reservation_id"],
                    "hotel_ref": result.value["booked_hotel_id"],
                },
                "amount": {
                    "minor_units": result.value["price_cents"],
                    "currency": "SYN",
                },
            },
        )

    def step(self, action: ToolAction) -> StepResult:
        self.last_fault_id = None
        if self.drift_mode == "flight_action_schema_v2" and action.tool_name == "flights.book":
            self.last_fault_id = FLIGHT_ACTION_FAULT_ID
            if action.schema_version != DRIFT_SCHEMA_VERSION:
                return self._safe_rejection(action, "schema_version_unsupported")
            if not self._valid_flight_v2(action.arguments):
                return self._safe_rejection(action, "invalid_arguments")
            return self._base.step(self._translate_flight_v2(action))

        result = self._base.step(action)
        if (
            self.drift_mode == "hotel_result_schema_v2"
            and action.tool_name == "hotels.book"
            and result.ok
        ):
            self.last_fault_id = HOTEL_RESULT_FAULT_ID
            return self._hotel_result_v2(result)
        return result
