"""Data contracts shared by the ARL pilot and expanded main-study task pack."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

from arl.core.types import ToolAction, digest_value
from arl_mainstudy.catalog import BLUEPRINTS_BY_TEMPLATE_ID, TaskBlueprint
from arl_mainstudy.model import ToolDefinition

ENV_VERSION = "arl-pilot-preflight-v0.17.0"
CANONICAL_SCHEMA_VERSION = "1.0"
DRIFT_SCHEMA_VERSION = "2.0"
CONDITIONS = ("clean", "recoverable_fault")


@dataclass(frozen=True)
class OperationSpec:
    """One public semantic operation and its deterministic business-state effect."""

    operation_id: str
    tool_name: str
    arguments: dict[str, Any]
    is_write: bool
    effects: tuple[tuple[str, Any], ...] = ()
    result_value: dict[str, Any] = field(default_factory=dict)
    required_result_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.operation_id or not self.tool_name:
            raise ValueError("Operation ID and tool name are required")
        if len({path for path, _ in self.effects}) != len(self.effects):
            raise ValueError(f"Duplicate effect path in {self.operation_id}")
        if bool(self.effects) != self.is_write:
            raise ValueError("Write operations require effects and reads cannot mutate state")
        if not set(self.required_result_fields).issubset(self.result_value):
            raise ValueError(f"Missing canonical result field in {self.operation_id}")

    def semantic_action(self) -> ToolAction:
        return ToolAction(
            tool_name=self.tool_name,
            schema_version=CANONICAL_SCHEMA_VERSION,
            arguments=dict(self.arguments),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "effects": [[path, value] for path, value in self.effects],
        }


@dataclass(frozen=True)
class PilotTaskSpec:
    """A complete local task, fault, oracle, and evaluator contract."""

    template_id: str
    initial_values: tuple[tuple[str, Any], ...]
    semantic_operations: tuple[OperationSpec, ...]
    fault_operation_id: str
    clean_expected: tuple[tuple[str, Any], ...]
    fault_expected: tuple[tuple[str, Any], ...]
    allowed_change_paths: tuple[str, ...]
    public_read_paths: tuple[str, ...]
    compensation_operations: tuple[OperationSpec, ...] = ()
    conflict_guard: tuple[tuple[str, Any], ...] = ()
    input_drift_argument_map: tuple[tuple[str, str], ...] = ()
    output_drift_result: tuple[tuple[str, Any], ...] = ()
    conflict_effects: tuple[tuple[str, Any], ...] = ()
    user_request: str | None = None
    visible_context: tuple[tuple[str, Any], ...] = ()
    implementation_version: str = "v017"

    def __post_init__(self) -> None:
        blueprint = self.blueprint
        operation_ids = [operation.operation_id for operation in self.all_operations]
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError(f"Duplicate operation ID in {self.template_id}")
        if self.fault_operation_id not in {
            operation.operation_id for operation in self.semantic_operations
        }:
            raise ValueError(f"Fault operation is not semantic in {self.template_id}")
        initial_paths = {path for path, _ in self.initial_values}
        if len(initial_paths) != len(self.initial_values):
            raise ValueError(f"Duplicate initial path in {self.template_id}")
        all_effect_paths = {
            path for operation in self.all_operations for path, _ in operation.effects
        } | {path for path, _ in self.conflict_effects}
        expected_paths = {path for path, _ in (*self.clean_expected, *self.fault_expected)}
        if not expected_paths.issubset(initial_paths | all_effect_paths):
            raise ValueError(f"Expected path has no state definition in {self.template_id}")
        if not all_effect_paths.issubset(self.allowed_change_paths):
            raise ValueError(f"Operation effect is not evaluator-allowed in {self.template_id}")
        if not {path for path, _ in self.conflict_guard}.issubset(self.public_read_paths):
            raise ValueError(f"Conflict guard is not public in {self.template_id}")
        if not set(self.public_read_paths).issubset(initial_paths | all_effect_paths):
            raise ValueError(f"Public read path has no state definition in {self.template_id}")
        if (
            blueprint.main_fault_family == "bounded_compensation"
            and not self.compensation_operations
        ):
            raise ValueError("Bounded-compensation tasks require a recovery workflow")
        if blueprint.main_fault_family != "bounded_compensation" and self.compensation_operations:
            raise ValueError("Only bounded-compensation tasks may register a recovery workflow")
        fault_operation = self.operation(self.fault_operation_id)
        input_map = dict(self.input_drift_argument_map)
        if len(input_map) != len(self.input_drift_argument_map):
            raise ValueError(f"Duplicate input drift field in {self.template_id}")
        if blueprint.main_fault_family == "input_schema_drift":
            if not input_map or not set(input_map).issubset(fault_operation.arguments):
                raise ValueError("Input-schema tasks require an exact argument rename map")
            drift_fields = [input_map.get(name, name) for name in fault_operation.arguments]
            if len(set(drift_fields)) != len(drift_fields):
                raise ValueError("Input-schema rename map produces duplicate fields")
        elif input_map:
            raise ValueError("Only input-schema tasks may register an argument rename map")
        if blueprint.main_fault_family == "output_schema_drift":
            if not self.output_drift_result:
                raise ValueError("Output-schema tasks require an exact drifted result")
        elif self.output_drift_result:
            raise ValueError("Only output-schema tasks may register a drifted result")
        if blueprint.main_fault_family == "compatible_state_conflict":
            if not self.conflict_guard or not self.conflict_effects:
                raise ValueError("Conflict tasks require a public guard and external effects")
        elif self.conflict_guard or self.conflict_effects:
            raise ValueError("Only conflict tasks may register conflict contracts")
        if not self.implementation_version:
            raise ValueError("Implementation version is required")
        if self.user_request is None and self.template_id not in _VISIBLE_TASK_CONTRACTS:
            raise ValueError(f"Visible task contract is missing for {self.template_id}")
        if self.user_request is not None and (not self.user_request or not self.visible_context):
            raise ValueError(f"Inline visible task contract is incomplete for {self.template_id}")

    @property
    def blueprint(self) -> TaskBlueprint:
        return BLUEPRINTS_BY_TEMPLATE_ID[self.template_id]

    @property
    def task_id(self) -> str:
        return self.blueprint.task_id

    @property
    def domain(self) -> str:
        return self.blueprint.domain

    @property
    def fault_family(self) -> str:
        return self.blueprint.main_fault_family

    @property
    def fault_id(self) -> str:
        return f"fault.pilot.{self.template_id}.{self.fault_family}"

    @property
    def all_operations(self) -> tuple[OperationSpec, ...]:
        return (*self.semantic_operations, *self.compensation_operations)

    @property
    def initial_values_dict(self) -> dict[str, Any]:
        return dict(self.initial_values)

    def expected_values(self, condition: str) -> dict[str, Any]:
        if condition == "clean":
            return dict(self.clean_expected)
        if condition == "recoverable_fault":
            return dict(self.fault_expected)
        raise ValueError(f"Unknown condition: {condition}")

    def operation(self, operation_id: str) -> OperationSpec:
        try:
            return next(item for item in self.all_operations if item.operation_id == operation_id)
        except StopIteration as error:
            raise KeyError(f"Unknown operation {operation_id!r} for {self.template_id}") from error

    @property
    def semantic_actions(self) -> tuple[ToolAction, ...]:
        return tuple(operation.semantic_action() for operation in self.semantic_operations)

    def drifted_arguments(self, operation: OperationSpec) -> dict[str, Any]:
        """Return the exact advertised v2 arguments for the registered fault operation."""

        if operation.operation_id != self.fault_operation_id:
            raise ValueError("Input drift is only defined for the fault operation")
        rename = dict(self.input_drift_argument_map)
        return {rename.get(name, name): value for name, value in operation.arguments.items()}

    @property
    def visible_task(self) -> dict[str, Any]:
        contract = (
            _VISIBLE_TASK_CONTRACTS[self.template_id]
            if self.user_request is None
            else {"user_request": self.user_request, "context": dict(self.visible_context)}
        )
        return {
            "template_id": self.template_id,
            "domain": self.domain,
            "user_request": contract["user_request"],
            "context": dict(contract["context"]),
            "allowed_tools": sorted(
                {operation.tool_name for operation in self.semantic_operations}
            ),
        }

    @property
    def model_tools(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            ToolDefinition(
                tool_name=operation.tool_name,
                schema_version=CANONICAL_SCHEMA_VERSION,
                required_arguments=tuple(operation.arguments),
            )
            for operation in self.semantic_operations
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "task_id": self.task_id,
            "domain": self.domain,
            "fault_family": self.fault_family,
            "fault_id": self.fault_id,
            "source_blueprint_status": self.blueprint.implementation_status,
            "implementation_status": f"implemented_{self.implementation_version}",
            "semantic_operation_ids": [item.operation_id for item in self.semantic_operations],
            "fault_operation_id": self.fault_operation_id,
            "compensation_operation_ids": [
                item.operation_id for item in self.compensation_operations
            ],
            "clean_expected": dict(self.clean_expected),
            "fault_expected": dict(self.fault_expected),
            "allowed_change_paths": list(self.allowed_change_paths),
            "public_read_paths": list(self.public_read_paths),
            "conflict_guard": dict(self.conflict_guard),
            "input_drift_argument_map": dict(self.input_drift_argument_map),
            "output_drift_result": dict(self.output_drift_result),
            "conflict_effects": dict(self.conflict_effects),
            "visible_task": self.visible_task,
            "model_tools": [tool.as_dict() for tool in self.model_tools],
        }


def operation_spec(
    operation_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    effects: dict[str, Any] | None = None,
    result: dict[str, Any],
    required: tuple[str, ...],
) -> OperationSpec:
    effect_items = tuple((effects or {}).items())
    return OperationSpec(
        operation_id=operation_id,
        tool_name=tool_name,
        arguments=arguments,
        is_write=bool(effect_items),
        effects=effect_items,
        result_value=result,
        required_result_fields=required,
    )


_op = operation_spec


_VISIBLE_TASK_CONTRACTS: dict[str, dict[str, Any]] = {
    "workspace.schedule-meeting.main-v1": {
        "user_request": (
            "Schedule the requested meeting, invite both attendees, and resolve the request."
        ),
        "context": {
            "event_id": "event-main",
            "time": "2026-09-10T10:00",
            "recipient_count": 2,
            "request_id": "schedule-main",
        },
    },
    "workspace.reschedule-meeting.main-v1": {
        "user_request": (
            "Move the meeting to the approved time, notify both attendees, and resolve "
            "the change request."
        ),
        "context": {
            "event_id": "event-main",
            "approved_time": "2026-09-10T14:00",
            "recipient_count": 2,
            "request_id": "reschedule-main",
        },
    },
    "retail.discounted-order.main-v1": {
        "user_request": (
            "Place one unit using the approved coupon and resolve the purchase request."
        ),
        "context": {
            "product_id": "product-main",
            "quantity": 1,
            "coupon_code": "ARL20",
            "order_id": "order-main",
            "request_id": "purchase-main",
        },
    },
    "retail.eligible-exchange.main-v1": {
        "user_request": (
            "Create the eligible exchange for the requested replacement and resolve the request."
        ),
        "context": {
            "order_id": "order-exchange",
            "exchange_id": "exchange-main",
            "replacement_sku": "sku-blue",
            "request_id": "exchange-main",
        },
    },
    "travel.book-itinerary.main-v1": {
        "user_request": "Book the approved flight and hotel, then resolve the booking request.",
        "context": {
            "flight_id": "flight-main",
            "hotel_id": "hotel-main",
            "request_id": "booking-main",
        },
    },
    "workspace.clarify-attendees.main-v1": {
        "user_request": (
            "Resolve the two attendee handles, schedule the meeting, invite the resolved "
            "people, and close the request."
        ),
        "context": {
            "handles": ["alex", "sam"],
            "event_id": "event-clarified",
            "time": "2026-09-11T09:00",
            "recipient_count": 2,
            "request_id": "clarification-main",
        },
    },
    "retail.shipping-revision.main-v1": {
        "user_request": (
            "Verify the order, apply the authorized shipping-address revision, and resolve "
            "the request."
        ),
        "context": {
            "order_id": "order-shipping",
            "current_shipping_address": "1 Original Road",
            "authorized_shipping_address": "2 Revised Avenue",
            "request_id": "shipping-main",
        },
    },
    "travel.bundle-recovery.main-v1": {
        "user_request": (
            "Book the preferred refundable hotel and flight; the runtime may use the "
            "authorized fallback bundle if the flight is unavailable."
        ),
        "context": {
            "preferred_hotel_id": "hotel-preferred",
            "preferred_flight_id": "flight-preferred",
            "fallback_hotel_id": "hotel-fallback",
            "fallback_flight_id": "flight-fallback",
        },
    },
}


PILOT_TASK_SPECS = (
    PilotTaskSpec(
        template_id="workspace.schedule-meeting.main-v1",
        initial_values=(
            ("workspace.event.main.status", "absent"),
            ("workspace.event.main.time", None),
            ("workspace.notifications.invites", 0),
            ("workspace.request.schedule.status", "pending"),
        ),
        semantic_operations=(
            _op(
                "schedule.create_event",
                "calendar.create_event",
                {"event_id": "event-main", "time": "2026-09-10T10:00"},
                effects={
                    "workspace.event.main.status": "scheduled",
                    "workspace.event.main.time": "2026-09-10T10:00",
                },
                result={"event_id": "event-main", "status": "scheduled"},
                required=("event_id", "status"),
            ),
            _op(
                "schedule.send_invites",
                "messages.send_invitations",
                {"event_id": "event-main", "recipient_count": 2},
                effects={"workspace.notifications.invites": 2},
                result={"sent_count": 2},
                required=("sent_count",),
            ),
            _op(
                "schedule.resolve_request",
                "workspace.resolve_schedule_request",
                {"request_id": "schedule-main"},
                effects={"workspace.request.schedule.status": "resolved"},
                result={"request_id": "schedule-main", "status": "resolved"},
                required=("request_id", "status"),
            ),
        ),
        fault_operation_id="schedule.create_event",
        clean_expected=(
            ("workspace.event.main.status", "scheduled"),
            ("workspace.event.main.time", "2026-09-10T10:00"),
            ("workspace.notifications.invites", 2),
            ("workspace.request.schedule.status", "resolved"),
        ),
        fault_expected=(
            ("workspace.event.main.status", "scheduled"),
            ("workspace.event.main.time", "2026-09-10T10:00"),
            ("workspace.notifications.invites", 2),
            ("workspace.request.schedule.status", "resolved"),
        ),
        allowed_change_paths=(
            "workspace.event.main.status",
            "workspace.event.main.time",
            "workspace.notifications.invites",
            "workspace.request.schedule.status",
        ),
        public_read_paths=("workspace.event.main.status", "workspace.event.main.time"),
    ),
    PilotTaskSpec(
        template_id="workspace.reschedule-meeting.main-v1",
        initial_values=(
            ("workspace.event.main.time", "2026-09-10T10:00"),
            ("workspace.notifications.reschedule", 0),
            ("workspace.request.reschedule.status", "pending"),
        ),
        semantic_operations=(
            _op(
                "reschedule.update_event",
                "calendar.update_event_time",
                {"event_id": "event-main", "time": "2026-09-10T14:00"},
                effects={"workspace.event.main.time": "2026-09-10T14:00"},
                result={"event_id": "event-main", "time": "2026-09-10T14:00"},
                required=("event_id", "time"),
            ),
            _op(
                "reschedule.notify",
                "messages.send_reschedule_notifications",
                {"event_id": "event-main", "recipient_count": 2},
                effects={"workspace.notifications.reschedule": 2},
                result={"sent_count": 2},
                required=("sent_count",),
            ),
            _op(
                "reschedule.resolve_request",
                "workspace.resolve_change_request",
                {"request_id": "reschedule-main"},
                effects={"workspace.request.reschedule.status": "resolved"},
                result={"request_id": "reschedule-main", "status": "resolved"},
                required=("request_id", "status"),
            ),
        ),
        fault_operation_id="reschedule.notify",
        clean_expected=(
            ("workspace.event.main.time", "2026-09-10T14:00"),
            ("workspace.notifications.reschedule", 2),
            ("workspace.request.reschedule.status", "resolved"),
        ),
        fault_expected=(
            ("workspace.event.main.time", "2026-09-10T14:00"),
            ("workspace.notifications.reschedule", 2),
            ("workspace.request.reschedule.status", "resolved"),
        ),
        allowed_change_paths=(
            "workspace.event.main.time",
            "workspace.notifications.reschedule",
            "workspace.request.reschedule.status",
        ),
        public_read_paths=("workspace.notifications.reschedule",),
    ),
    PilotTaskSpec(
        template_id="retail.discounted-order.main-v1",
        initial_values=(
            ("retail.cart.item_count", 0),
            ("retail.cart.coupon", None),
            ("retail.order.main.status", "absent"),
            ("retail.request.purchase.status", "pending"),
        ),
        semantic_operations=(
            _op(
                "purchase.add_item",
                "cart.add_item",
                {"product_id": "product-main", "quantity": 1},
                effects={"retail.cart.item_count": 1},
                result={"item_count": 1},
                required=("item_count",),
            ),
            _op(
                "purchase.apply_coupon",
                "cart.apply_coupon",
                {"coupon_code": "ARL20"},
                effects={"retail.cart.coupon": "ARL20"},
                result={"coupon_code": "ARL20", "accepted": True},
                required=("coupon_code", "accepted"),
            ),
            _op(
                "purchase.place_order",
                "orders.place_order",
                {"order_id": "order-main"},
                effects={"retail.order.main.status": "placed"},
                result={"order_id": "order-main", "status": "placed"},
                required=("order_id", "status"),
            ),
            _op(
                "purchase.resolve_request",
                "retail.resolve_purchase_request",
                {"request_id": "purchase-main", "order_id": "order-main"},
                effects={"retail.request.purchase.status": "resolved"},
                result={"request_id": "purchase-main", "status": "resolved"},
                required=("request_id", "status"),
            ),
        ),
        fault_operation_id="purchase.place_order",
        clean_expected=(
            ("retail.cart.item_count", 1),
            ("retail.cart.coupon", "ARL20"),
            ("retail.order.main.status", "placed"),
            ("retail.request.purchase.status", "resolved"),
        ),
        fault_expected=(
            ("retail.cart.item_count", 1),
            ("retail.cart.coupon", "ARL20"),
            ("retail.order.main.status", "placed"),
            ("retail.request.purchase.status", "resolved"),
        ),
        allowed_change_paths=(
            "retail.cart.item_count",
            "retail.cart.coupon",
            "retail.order.main.status",
            "retail.request.purchase.status",
        ),
        public_read_paths=("retail.order.main.status",),
    ),
    PilotTaskSpec(
        template_id="retail.eligible-exchange.main-v1",
        initial_values=(
            ("retail.order.item.status", "delivered"),
            ("retail.exchange.main.status", "absent"),
            ("retail.request.exchange.status", "pending"),
        ),
        semantic_operations=(
            _op(
                "exchange.read_order",
                "orders.get_order",
                {"order_id": "order-exchange"},
                result={"order_id": "order-exchange", "item_status": "delivered"},
                required=("order_id", "item_status"),
            ),
            _op(
                "exchange.create",
                "exchanges.create",
                {"exchange_id": "exchange-main", "replacement_sku": "sku-blue"},
                effects={
                    "retail.order.item.status": "exchange_pending",
                    "retail.exchange.main.status": "created",
                },
                result={"exchange_id": "exchange-main", "status": "created"},
                required=("exchange_id", "status"),
            ),
            _op(
                "exchange.resolve_request",
                "retail.resolve_exchange_request",
                {"request_id": "exchange-main"},
                effects={"retail.request.exchange.status": "resolved"},
                result={"request_id": "exchange-main", "status": "resolved"},
                required=("request_id", "status"),
            ),
        ),
        fault_operation_id="exchange.create",
        clean_expected=(
            ("retail.order.item.status", "exchange_pending"),
            ("retail.exchange.main.status", "created"),
            ("retail.request.exchange.status", "resolved"),
        ),
        fault_expected=(
            ("retail.order.item.status", "exchange_pending"),
            ("retail.exchange.main.status", "created"),
            ("retail.request.exchange.status", "resolved"),
        ),
        allowed_change_paths=(
            "retail.order.item.status",
            "retail.exchange.main.status",
            "retail.request.exchange.status",
        ),
        public_read_paths=("retail.exchange.main.status",),
    ),
    PilotTaskSpec(
        template_id="travel.book-itinerary.main-v1",
        initial_values=(
            ("travel.flight.main.status", "absent"),
            ("travel.hotel.main.status", "absent"),
            ("travel.request.booking.status", "pending"),
        ),
        semantic_operations=(
            _op(
                "itinerary.book_flight",
                "flights.book",
                {"flight_id": "flight-main"},
                effects={"travel.flight.main.status": "booked"},
                result={"reservation_id": "flight-res-main", "status": "booked"},
                required=("reservation_id", "status"),
            ),
            _op(
                "itinerary.book_hotel",
                "hotels.book",
                {"hotel_id": "hotel-main"},
                effects={"travel.hotel.main.status": "booked"},
                result={"reservation_id": "hotel-res-main", "status": "booked"},
                required=("reservation_id", "status"),
            ),
            _op(
                "itinerary.resolve_request",
                "travel.resolve_booking_request",
                {"request_id": "booking-main"},
                effects={"travel.request.booking.status": "resolved"},
                result={"request_id": "booking-main", "status": "resolved"},
                required=("request_id", "status"),
            ),
        ),
        fault_operation_id="itinerary.book_flight",
        clean_expected=(
            ("travel.flight.main.status", "booked"),
            ("travel.hotel.main.status", "booked"),
            ("travel.request.booking.status", "resolved"),
        ),
        fault_expected=(
            ("travel.flight.main.status", "booked"),
            ("travel.hotel.main.status", "booked"),
            ("travel.request.booking.status", "resolved"),
        ),
        allowed_change_paths=(
            "travel.flight.main.status",
            "travel.hotel.main.status",
            "travel.request.booking.status",
        ),
        public_read_paths=("travel.flight.main.status",),
        input_drift_argument_map=(("flight_id", "segment_id"),),
    ),
    PilotTaskSpec(
        template_id="workspace.clarify-attendees.main-v1",
        initial_values=(
            ("workspace.attendees.resolved_count", 0),
            ("workspace.event.clarified.status", "absent"),
            ("workspace.notifications.clarified", 0),
            ("workspace.request.clarification.status", "pending"),
        ),
        semantic_operations=(
            _op(
                "clarify.resolve_attendees",
                "directory.resolve_attendees",
                {"handles": ["alex", "sam"]},
                result={"attendee_ids": ["person-alex", "person-sam"]},
                required=("attendee_ids",),
            ),
            _op(
                "clarify.create_event",
                "calendar.create_event",
                {
                    "event_id": "event-clarified",
                    "time": "2026-09-11T09:00",
                    "attendee_ids": ["person-alex", "person-sam"],
                },
                effects={
                    "workspace.attendees.resolved_count": 2,
                    "workspace.event.clarified.status": "scheduled",
                },
                result={"event_id": "event-clarified", "status": "scheduled"},
                required=("event_id", "status"),
            ),
            _op(
                "clarify.send_invites",
                "messages.send_invitations",
                {"event_id": "event-clarified", "recipient_count": 2},
                effects={"workspace.notifications.clarified": 2},
                result={"sent_count": 2},
                required=("sent_count",),
            ),
            _op(
                "clarify.resolve_request",
                "workspace.resolve_clarification_request",
                {"request_id": "clarification-main"},
                effects={"workspace.request.clarification.status": "resolved"},
                result={"request_id": "clarification-main", "status": "resolved"},
                required=("request_id", "status"),
            ),
        ),
        fault_operation_id="clarify.resolve_attendees",
        clean_expected=(
            ("workspace.attendees.resolved_count", 2),
            ("workspace.event.clarified.status", "scheduled"),
            ("workspace.notifications.clarified", 2),
            ("workspace.request.clarification.status", "resolved"),
        ),
        fault_expected=(
            ("workspace.attendees.resolved_count", 2),
            ("workspace.event.clarified.status", "scheduled"),
            ("workspace.notifications.clarified", 2),
            ("workspace.request.clarification.status", "resolved"),
        ),
        allowed_change_paths=(
            "workspace.attendees.resolved_count",
            "workspace.event.clarified.status",
            "workspace.notifications.clarified",
            "workspace.request.clarification.status",
        ),
        public_read_paths=("workspace.event.clarified.status",),
        output_drift_result=(
            ("result_schema_version", DRIFT_SCHEMA_VERSION),
            ("resolution", {"ids": ["person-alex", "person-sam"]}),
        ),
    ),
    PilotTaskSpec(
        template_id="retail.shipping-revision.main-v1",
        initial_values=(
            ("retail.order.shipping.address", "1 Original Road"),
            ("retail.order.audit_revision", 0),
            ("retail.request.shipping.status", "pending"),
        ),
        semantic_operations=(
            _op(
                "shipping.read_order",
                "orders.get_order",
                {"order_id": "order-shipping"},
                result={
                    "order_id": "order-shipping",
                    "shipping_address": "1 Original Road",
                },
                required=("order_id", "shipping_address"),
            ),
            _op(
                "shipping.update_address",
                "orders.update_shipping",
                {"order_id": "order-shipping", "shipping_address": "2 Revised Avenue"},
                effects={"retail.order.shipping.address": "2 Revised Avenue"},
                result={"order_id": "order-shipping", "status": "updated"},
                required=("order_id", "status"),
            ),
            _op(
                "shipping.resolve_request",
                "retail.resolve_shipping_request",
                {"request_id": "shipping-main"},
                effects={"retail.request.shipping.status": "resolved"},
                result={"request_id": "shipping-main", "status": "resolved"},
                required=("request_id", "status"),
            ),
        ),
        fault_operation_id="shipping.update_address",
        clean_expected=(
            ("retail.order.shipping.address", "2 Revised Avenue"),
            ("retail.request.shipping.status", "resolved"),
        ),
        fault_expected=(
            ("retail.order.shipping.address", "2 Revised Avenue"),
            ("retail.request.shipping.status", "resolved"),
        ),
        allowed_change_paths=(
            "retail.order.shipping.address",
            "retail.order.audit_revision",
            "retail.request.shipping.status",
        ),
        public_read_paths=("retail.order.shipping.address",),
        conflict_guard=(("retail.order.shipping.address", "1 Original Road"),),
        conflict_effects=(("retail.order.audit_revision", 1),),
    ),
    PilotTaskSpec(
        template_id="travel.bundle-recovery.main-v1",
        initial_values=(
            ("travel.hotel.preferred.status", "absent"),
            ("travel.flight.preferred.status", "absent"),
            ("travel.hotel.fallback.status", "absent"),
            ("travel.flight.fallback.status", "absent"),
        ),
        semantic_operations=(
            _op(
                "bundle.book_preferred_hotel",
                "hotels.book",
                {"hotel_id": "hotel-preferred"},
                effects={"travel.hotel.preferred.status": "booked"},
                result={"reservation_id": "hotel-preferred", "status": "booked"},
                required=("reservation_id", "status"),
            ),
            _op(
                "bundle.book_preferred_flight",
                "flights.book",
                {"flight_id": "flight-preferred"},
                effects={"travel.flight.preferred.status": "booked"},
                result={"reservation_id": "flight-preferred", "status": "booked"},
                required=("reservation_id", "status"),
            ),
        ),
        fault_operation_id="bundle.book_preferred_flight",
        clean_expected=(
            ("travel.hotel.preferred.status", "booked"),
            ("travel.flight.preferred.status", "booked"),
            ("travel.hotel.fallback.status", "absent"),
            ("travel.flight.fallback.status", "absent"),
        ),
        fault_expected=(
            ("travel.hotel.preferred.status", "cancelled"),
            ("travel.flight.preferred.status", "absent"),
            ("travel.hotel.fallback.status", "booked"),
            ("travel.flight.fallback.status", "booked"),
        ),
        allowed_change_paths=(
            "travel.hotel.preferred.status",
            "travel.flight.preferred.status",
            "travel.hotel.fallback.status",
            "travel.flight.fallback.status",
        ),
        public_read_paths=(
            "travel.hotel.preferred.status",
            "travel.flight.preferred.status",
        ),
        compensation_operations=(
            _op(
                "bundle.cancel_preferred_hotel",
                "hotels.cancel",
                {"hotel_id": "hotel-preferred"},
                effects={"travel.hotel.preferred.status": "cancelled"},
                result={"reservation_id": "hotel-preferred", "status": "cancelled"},
                required=("reservation_id", "status"),
            ),
            _op(
                "bundle.book_fallback_flight",
                "flights.book",
                {"flight_id": "flight-fallback"},
                effects={"travel.flight.fallback.status": "booked"},
                result={"reservation_id": "flight-fallback", "status": "booked"},
                required=("reservation_id", "status"),
            ),
            _op(
                "bundle.book_fallback_hotel",
                "hotels.book",
                {"hotel_id": "hotel-fallback"},
                effects={"travel.hotel.fallback.status": "booked"},
                result={"reservation_id": "hotel-fallback", "status": "booked"},
                required=("reservation_id", "status"),
            ),
        ),
    ),
)

SPECS_BY_TEMPLATE_ID = {spec.template_id: spec for spec in PILOT_TASK_SPECS}


def pilot_catalog_audit() -> dict[str, Any]:
    template_ids = [spec.template_id for spec in PILOT_TASK_SPECS]
    domain_counts = Counter(spec.domain for spec in PILOT_TASK_SPECS)
    fault_counts = Counter(spec.fault_family for spec in PILOT_TASK_SPECS)
    source_status_counts = Counter(
        spec.blueprint.implementation_status for spec in PILOT_TASK_SPECS
    )
    checks = {
        "eight_unique_runnable_tasks": (
            len(PILOT_TASK_SPECS) == 8
            and len(SPECS_BY_TEMPLATE_ID) == 8
            and len(set(template_ids)) == 8
        ),
        "all_three_domains_present": set(domain_counts) == {"workspace", "retail", "travel"},
        "all_six_fault_families_present": set(fault_counts)
        == {
            "postcommit_response_loss",
            "retryable_invocation_error",
            "input_schema_drift",
            "output_schema_drift",
            "compatible_state_conflict",
            "bounded_compensation",
        },
        "five_existing_three_newly_implemented": dict(source_status_counts)
        == {"existing_core": 5, "planned": 3},
        "every_task_has_oracle_and_fault": all(
            spec.clean_expected and spec.fault_expected and spec.fault_operation_id
            for spec in PILOT_TASK_SPECS
        ),
    }
    descriptor = [spec.as_dict() for spec in PILOT_TASK_SPECS]
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "task_count": len(PILOT_TASK_SPECS),
        "domain_counts": dict(sorted(domain_counts.items())),
        "fault_family_counts": dict(sorted(fault_counts.items())),
        "source_blueprint_status_counts": dict(sorted(source_status_counts.items())),
        "catalog_sha256": digest_value(descriptor),
    }
