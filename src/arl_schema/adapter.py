"""Strict, descriptor-driven adapters for the synthetic schema-drift benchmark."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from arl.core.types import StepResult, ToolAction

BASE_SCHEMA_VERSION = "1.0"
DRIFT_SCHEMA_VERSION = "2.0"

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

_FLIGHT_ACTION_FIELDS_V2 = (
    "reservation_ref",
    "flight_ref",
    "traveler_ref",
    "payment_ref",
    "fare_acknowledged",
)

_HOTEL_RESULT_FIELDS_V2 = ("result_schema_version", "reservation", "amount")


class SchemaAdapterError(ValueError):
    """Raised when a public descriptor or payload cannot be adapted safely."""


def _require_exact_fields(
    value: Any,
    required: set[str],
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SchemaAdapterError(f"{label} must be an object")
    actual = set(value)
    if actual != required:
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        raise SchemaAdapterError(f"{label} fields mismatch: missing={missing}, extra={extra}")
    return value


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise SchemaAdapterError(f"{label} must be a non-empty string")
    return value


def _descriptor_section(
    descriptor: dict[str, Any],
    *,
    tool_name: str,
    section: str,
) -> dict[str, Any]:
    if descriptor.get("tool_name") != tool_name:
        raise SchemaAdapterError("descriptor tool_name does not match action tool")
    value = descriptor.get(section)
    if not isinstance(value, dict):
        raise SchemaAdapterError(f"descriptor {section} section must be an object")
    _require_string(value.get("schema_version"), label=f"descriptor {section} schema_version")
    return value


def _validate_descriptor_contract(
    section: dict[str, Any],
    *,
    required_fields: tuple[str, ...],
    label: str,
) -> None:
    _require_exact_fields(
        section,
        {"schema_version", "required_fields", "additional_fields"},
        label=label,
    )
    if section["required_fields"] != list(required_fields):
        raise SchemaAdapterError(f"{label} required_fields are not registered")
    if section["additional_fields"] is not False:
        raise SchemaAdapterError(f"{label} must reject additional fields")


class SchemaAdapter:
    """Map only explicitly registered public schema versions.

    The registry is static and contains no task, seed, evaluator, or fault information.
    Unknown versions and non-exact payloads fail closed.
    """

    @staticmethod
    def adapt_action(
        action: ToolAction,
        descriptor: dict[str, Any],
    ) -> tuple[ToolAction, bool]:
        section = _descriptor_section(
            descriptor,
            tool_name=action.tool_name,
            section="action",
        )
        advertised_version = section["schema_version"]
        if advertised_version == BASE_SCHEMA_VERSION:
            if action.tool_name not in _ACTION_FIELDS_V1:
                raise SchemaAdapterError(f"unsupported action tool: {action.tool_name}")
            _validate_descriptor_contract(
                section,
                required_fields=_ACTION_FIELDS_V1[action.tool_name],
                label=f"{action.tool_name}@1.0 action descriptor",
            )
            if action.schema_version != BASE_SCHEMA_VERSION:
                raise SchemaAdapterError("canonical action must use schema version 1.0")
            return action, False
        if action.tool_name != "flights.book" or advertised_version != DRIFT_SCHEMA_VERSION:
            raise SchemaAdapterError(
                f"unsupported action schema: {action.tool_name}@{advertised_version}"
            )
        if action.schema_version != BASE_SCHEMA_VERSION:
            raise SchemaAdapterError("canonical action must use schema version 1.0")
        _validate_descriptor_contract(
            section,
            required_fields=_FLIGHT_ACTION_FIELDS_V2,
            label="flights.book@2.0 action descriptor",
        )

        arguments = _require_exact_fields(
            action.arguments,
            {
                "booking_id",
                "flight_id",
                "user_id",
                "payment_id",
                "confirmed_nonrefundable",
            },
            label="flights.book@1.0 arguments",
        )
        for key in ("booking_id", "flight_id", "user_id", "payment_id"):
            _require_string(arguments[key], label=f"flights.book@1.0 {key}")
        if not isinstance(arguments["confirmed_nonrefundable"], bool):
            raise SchemaAdapterError("flights.book@1.0 confirmed_nonrefundable must be a boolean")

        return (
            ToolAction(
                tool_name=action.tool_name,
                schema_version=DRIFT_SCHEMA_VERSION,
                arguments={
                    "reservation_ref": arguments["booking_id"],
                    "flight_ref": arguments["flight_id"],
                    "traveler_ref": arguments["user_id"],
                    "payment_ref": arguments["payment_id"],
                    "fare_acknowledged": arguments["confirmed_nonrefundable"],
                },
                idempotency_key=action.idempotency_key,
                expected_state_version=action.expected_state_version,
            ),
            True,
        )

    @staticmethod
    def normalize_result(
        *,
        tool_name: str,
        result: StepResult,
        descriptor: dict[str, Any],
    ) -> tuple[StepResult, bool]:
        section = _descriptor_section(
            descriptor,
            tool_name=tool_name,
            section="result",
        )
        advertised_version = section["schema_version"]
        if advertised_version == BASE_SCHEMA_VERSION:
            if tool_name not in _RESULT_FIELDS_V1:
                raise SchemaAdapterError(f"unsupported result tool: {tool_name}")
            _validate_descriptor_contract(
                section,
                required_fields=_RESULT_FIELDS_V1[tool_name],
                label=f"{tool_name}@1.0 result descriptor",
            )
            return result, False
        if tool_name != "hotels.book" or advertised_version != DRIFT_SCHEMA_VERSION:
            raise SchemaAdapterError(f"unsupported result schema: {tool_name}@{advertised_version}")
        _validate_descriptor_contract(
            section,
            required_fields=_HOTEL_RESULT_FIELDS_V2,
            label="hotels.book@2.0 result descriptor",
        )
        if not result.ok:
            return result, False

        value = _require_exact_fields(
            result.value,
            {"result_schema_version", "reservation", "amount"},
            label="hotels.book@2.0 result",
        )
        if value["result_schema_version"] != DRIFT_SCHEMA_VERSION:
            raise SchemaAdapterError("hotels.book result version marker mismatch")
        reservation = _require_exact_fields(
            value["reservation"],
            {"ref", "hotel_ref"},
            label="hotels.book@2.0 reservation",
        )
        amount = _require_exact_fields(
            value["amount"],
            {"minor_units", "currency"},
            label="hotels.book@2.0 amount",
        )
        reservation_ref = _require_string(
            reservation["ref"], label="hotels.book@2.0 reservation.ref"
        )
        hotel_ref = _require_string(
            reservation["hotel_ref"], label="hotels.book@2.0 reservation.hotel_ref"
        )
        minor_units = amount["minor_units"]
        if isinstance(minor_units, bool) or not isinstance(minor_units, int) or minor_units < 0:
            raise SchemaAdapterError(
                "hotels.book@2.0 amount.minor_units must be a non-negative integer"
            )
        if amount["currency"] != "SYN":
            raise SchemaAdapterError("hotels.book@2.0 amount.currency must be SYN")

        return (
            replace(
                result,
                value={
                    "booked_hotel_id": hotel_ref,
                    "hotel_reservation_id": reservation_ref,
                    "price_cents": minor_units,
                },
            ),
            True,
        )
