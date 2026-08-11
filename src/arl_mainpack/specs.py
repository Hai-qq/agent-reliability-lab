"""Sixteen additional fixtures that complete ARL's frozen 24-task blueprint."""

from __future__ import annotations

from collections import Counter
from typing import Any

from arl.core.types import digest_value
from arl_mainstudy.catalog import TASK_BLUEPRINTS
from arl_pilot.specs import (
    DRIFT_SCHEMA_VERSION,
    PILOT_TASK_SPECS,
    OperationSpec,
    PilotTaskSpec,
    operation_spec,
)


def _read(
    operation_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
) -> OperationSpec:
    return operation_spec(
        operation_id,
        tool_name,
        arguments,
        result=result,
        required=tuple(result),
    )


def _write(
    operation_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    effects: dict[str, Any],
    result: dict[str, Any],
) -> OperationSpec:
    return operation_spec(
        operation_id,
        tool_name,
        arguments,
        effects=effects,
        result=result,
        required=tuple(result),
    )


def _task(
    *,
    template_id: str,
    initial: dict[str, Any],
    operations: tuple[OperationSpec, ...],
    fault_operation_id: str,
    clean_expected: dict[str, Any],
    fault_expected: dict[str, Any] | None,
    public_read_paths: tuple[str, ...],
    user_request: str,
    context: dict[str, Any],
    compensation: tuple[OperationSpec, ...] = (),
    conflict_guard: dict[str, Any] | None = None,
    conflict_effects: dict[str, Any] | None = None,
    input_drift_argument_map: dict[str, str] | None = None,
    output_drift_result: dict[str, Any] | None = None,
) -> PilotTaskSpec:
    all_operations = (*operations, *compensation)
    allowed_change_paths = sorted(
        {path for operation in all_operations for path, _ in operation.effects}
        | set(conflict_effects or {})
    )
    return PilotTaskSpec(
        template_id=template_id,
        initial_values=tuple(initial.items()),
        semantic_operations=operations,
        fault_operation_id=fault_operation_id,
        clean_expected=tuple(clean_expected.items()),
        fault_expected=tuple((fault_expected or clean_expected).items()),
        allowed_change_paths=tuple(allowed_change_paths),
        public_read_paths=public_read_paths,
        compensation_operations=compensation,
        conflict_guard=tuple((conflict_guard or {}).items()),
        input_drift_argument_map=tuple((input_drift_argument_map or {}).items()),
        output_drift_result=tuple((output_drift_result or {}).items()),
        conflict_effects=tuple((conflict_effects or {}).items()),
        user_request=user_request,
        visible_context=tuple(context.items()),
        implementation_version="v020",
    )


ADDITIONAL_TASK_SPECS = (
    _task(
        template_id="workspace.cancel-meeting.main-v1",
        initial={
            "workspace.event.cancel.status": "scheduled",
            "workspace.notifications.cancellations": 0,
            "workspace.request.cancel.status": "pending",
        },
        operations=(
            _read(
                "cancel.read_event",
                "calendar.get_event",
                {"event_id": "event-cancel"},
                {"event_id": "event-cancel", "status": "scheduled"},
            ),
            _write(
                "cancel.cancel_event",
                "calendar.cancel_event",
                {"event_id": "event-cancel"},
                {"workspace.event.cancel.status": "cancelled"},
                {"event_id": "event-cancel", "status": "cancelled"},
            ),
            _write(
                "cancel.notify_attendees",
                "messages.send_cancellations",
                {"event_id": "event-cancel", "recipient_count": 2},
                {"workspace.notifications.cancellations": 2},
                {"sent_count": 2},
            ),
            _write(
                "cancel.resolve_request",
                "workspace.resolve_cancel_request",
                {"request_id": "cancel-main"},
                {"workspace.request.cancel.status": "resolved"},
                {"request_id": "cancel-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="cancel.cancel_event",
        clean_expected={
            "workspace.event.cancel.status": "cancelled",
            "workspace.notifications.cancellations": 2,
            "workspace.request.cancel.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("workspace.event.cancel.status",),
        user_request=(
            "Cancel the scheduled meeting, notify both attendees, and resolve the request."
        ),
        context={
            "event_id": "event-cancel",
            "recipient_count": 2,
            "request_id": "cancel-main",
        },
    ),
    _task(
        template_id="workspace.share-document.main-v1",
        initial={
            "workspace.document.share.status": "private",
            "workspace.document.share.editor_count": 0,
            "workspace.request.share.status": "pending",
        },
        operations=(
            _write(
                "share.grant_access",
                "documents.share",
                {
                    "document_id": "document-share",
                    "recipient_id": "person-reviewer",
                    "role": "editor",
                },
                {
                    "workspace.document.share.status": "shared",
                    "workspace.document.share.editor_count": 1,
                },
                {"document_id": "document-share", "status": "shared"},
            ),
            _write(
                "share.resolve_request",
                "workspace.resolve_share_request",
                {"request_id": "share-main"},
                {"workspace.request.share.status": "resolved"},
                {"request_id": "share-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="share.grant_access",
        clean_expected={
            "workspace.document.share.status": "shared",
            "workspace.document.share.editor_count": 1,
            "workspace.request.share.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("workspace.document.share.status",),
        input_drift_argument_map={"recipient_id": "principal_id"},
        user_request=(
            "Share the document with the approved reviewer as editor and resolve the request."
        ),
        context={
            "document_id": "document-share",
            "recipient_id": "person-reviewer",
            "role": "editor",
            "request_id": "share-main",
        },
    ),
    _task(
        template_id="workspace.resolve-schedule-conflict.main-v1",
        initial={
            "workspace.event.conflict": True,
            "workspace.event.selected_time": "2026-09-12T09:00",
            "workspace.schedule.audit_revision": 0,
            "workspace.request.conflict.status": "pending",
        },
        operations=(
            _read(
                "conflict.read_event",
                "calendar.get_event",
                {"event_id": "event-conflict"},
                {
                    "event_id": "event-conflict",
                    "selected_time": "2026-09-12T09:00",
                    "has_conflict": True,
                },
            ),
            _write(
                "conflict.select_time",
                "calendar.update_event",
                {"event_id": "event-conflict", "time": "2026-09-12T11:00"},
                {
                    "workspace.event.conflict": False,
                    "workspace.event.selected_time": "2026-09-12T11:00",
                },
                {"event_id": "event-conflict", "status": "updated"},
            ),
            _write(
                "conflict.resolve_request",
                "workspace.resolve_conflict_request",
                {"request_id": "conflict-main"},
                {"workspace.request.conflict.status": "resolved"},
                {"request_id": "conflict-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="conflict.select_time",
        clean_expected={
            "workspace.event.conflict": False,
            "workspace.event.selected_time": "2026-09-12T11:00",
            "workspace.request.conflict.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=(
            "workspace.event.conflict",
            "workspace.event.selected_time",
        ),
        conflict_guard={
            "workspace.event.conflict": True,
            "workspace.event.selected_time": "2026-09-12T09:00",
        },
        conflict_effects={"workspace.schedule.audit_revision": 1},
        user_request=(
            "Move the conflicted meeting to the approved free slot and resolve the request."
        ),
        context={
            "event_id": "event-conflict",
            "approved_time": "2026-09-12T11:00",
            "request_id": "conflict-main",
        },
    ),
    _task(
        template_id="workspace.revised-authorization.main-v1",
        initial={
            "workspace.authorization.revision": 2,
            "workspace.authorization.approved_time": "2026-09-13T15:00",
            "workspace.authorization.audit_revision": 0,
            "workspace.event.authorized.time": "2026-09-13T13:00",
            "workspace.event.authorized.applied_revision": 1,
            "workspace.request.authorization.status": "pending",
        },
        operations=(
            _read(
                "authorization.read_revision",
                "workspace.get_authorization",
                {"request_id": "authorization-main"},
                {"revision": 2, "approved_time": "2026-09-13T15:00"},
            ),
            _write(
                "authorization.apply_revision",
                "calendar.update_event",
                {
                    "event_id": "event-authorized",
                    "time": "2026-09-13T15:00",
                    "authorization_revision": 2,
                },
                {
                    "workspace.event.authorized.time": "2026-09-13T15:00",
                    "workspace.event.authorized.applied_revision": 2,
                },
                {"event_id": "event-authorized", "status": "updated"},
            ),
            _write(
                "authorization.resolve_request",
                "workspace.resolve_authorization_request",
                {"request_id": "authorization-main", "revision": 2},
                {"workspace.request.authorization.status": "resolved"},
                {"request_id": "authorization-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="authorization.apply_revision",
        clean_expected={
            "workspace.event.authorized.time": "2026-09-13T15:00",
            "workspace.event.authorized.applied_revision": 2,
            "workspace.request.authorization.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=(
            "workspace.authorization.revision",
            "workspace.authorization.approved_time",
        ),
        conflict_guard={
            "workspace.authorization.revision": 2,
            "workspace.authorization.approved_time": "2026-09-13T15:00",
        },
        conflict_effects={"workspace.authorization.audit_revision": 1},
        user_request="Apply authorization revision 2 to the meeting and resolve the request.",
        context={
            "event_id": "event-authorized",
            "authorization_revision": 2,
            "approved_time": "2026-09-13T15:00",
            "request_id": "authorization-main",
        },
    ),
    _task(
        template_id="workspace.partial-change-compensation.main-v1",
        initial={
            "workspace.copy.external.status": "absent",
            "workspace.copy.external.access": "none",
            "workspace.copy.internal.status": "absent",
            "workspace.copy.internal.access": "none",
            "workspace.request.copy.status": "pending",
        },
        operations=(
            _write(
                "copy.create_external",
                "documents.create_copy",
                {"source_id": "document-source", "copy_id": "copy-external"},
                {"workspace.copy.external.status": "created"},
                {"copy_id": "copy-external", "status": "created"},
            ),
            _write(
                "copy.grant_external",
                "documents.grant_access",
                {"copy_id": "copy-external", "audience": "external"},
                {"workspace.copy.external.access": "external"},
                {"copy_id": "copy-external", "status": "shared"},
            ),
            _write(
                "copy.resolve_request",
                "workspace.resolve_copy_request",
                {"request_id": "copy-main"},
                {"workspace.request.copy.status": "resolved"},
                {"request_id": "copy-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="copy.grant_external",
        clean_expected={
            "workspace.copy.external.status": "created",
            "workspace.copy.external.access": "external",
            "workspace.copy.internal.status": "absent",
            "workspace.copy.internal.access": "none",
            "workspace.request.copy.status": "resolved",
        },
        fault_expected={
            "workspace.copy.external.status": "deleted",
            "workspace.copy.external.access": "none",
            "workspace.copy.internal.status": "created",
            "workspace.copy.internal.access": "team",
            "workspace.request.copy.status": "resolved",
        },
        public_read_paths=("workspace.copy.external.status",),
        compensation=(
            _write(
                "copy.delete_external",
                "documents.delete_copy",
                {"copy_id": "copy-external"},
                {"workspace.copy.external.status": "deleted"},
                {"copy_id": "copy-external", "status": "deleted"},
            ),
            _write(
                "copy.create_internal",
                "documents.create_copy",
                {"source_id": "document-source", "copy_id": "copy-internal"},
                {"workspace.copy.internal.status": "created"},
                {"copy_id": "copy-internal", "status": "created"},
            ),
            _write(
                "copy.grant_team",
                "documents.grant_access",
                {"copy_id": "copy-internal", "audience": "team"},
                {"workspace.copy.internal.access": "team"},
                {"copy_id": "copy-internal", "status": "shared"},
            ),
        ),
        user_request=(
            "Create the approved shared copy; use the team-only fallback if external "
            "access is unavailable."
        ),
        context={
            "source_id": "document-source",
            "preferred_copy_id": "copy-external",
            "fallback_copy_id": "copy-internal",
            "request_id": "copy-main",
        },
    ),
    _task(
        template_id="retail.partial-refund.main-v1",
        initial={
            "retail.order.refund.balance": 100,
            "retail.refund.partial.status": "absent",
            "retail.refund.partial.amount": 0,
            "retail.request.refund.status": "pending",
        },
        operations=(
            _read(
                "refund.read_order",
                "orders.get_order",
                {"order_id": "order-refund"},
                {"order_id": "order-refund", "refundable_amount": 30},
            ),
            _write(
                "refund.issue_partial",
                "refunds.issue",
                {"order_id": "order-refund", "refund_id": "refund-partial", "amount": 30},
                {
                    "retail.order.refund.balance": 70,
                    "retail.refund.partial.status": "issued",
                    "retail.refund.partial.amount": 30,
                },
                {"refund_id": "refund-partial", "status": "issued", "amount": 30},
            ),
            _write(
                "refund.resolve_request",
                "retail.resolve_refund_request",
                {"request_id": "refund-main", "refund_id": "refund-partial"},
                {"retail.request.refund.status": "resolved"},
                {"request_id": "refund-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="refund.issue_partial",
        clean_expected={
            "retail.order.refund.balance": 70,
            "retail.refund.partial.status": "issued",
            "retail.refund.partial.amount": 30,
            "retail.request.refund.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=(
            "retail.order.refund.balance",
            "retail.refund.partial.status",
            "retail.refund.partial.amount",
        ),
        user_request="Issue the policy-approved partial refund of 30 and resolve the request.",
        context={
            "order_id": "order-refund",
            "refund_id": "refund-partial",
            "amount": 30,
            "request_id": "refund-main",
        },
    ),
    _task(
        template_id="retail.cancel-order.main-v1",
        initial={
            "retail.order.cancel.status": "unfulfilled",
            "retail.order.cancel.reason": None,
            "retail.request.cancel.status": "pending",
        },
        operations=(
            _read(
                "order_cancel.read_order",
                "orders.get_order",
                {"order_id": "order-cancel"},
                {"order_id": "order-cancel", "status": "unfulfilled"},
            ),
            _write(
                "order_cancel.cancel",
                "orders.cancel",
                {"order_id": "order-cancel", "reason": "customer_requested"},
                {
                    "retail.order.cancel.status": "cancelled",
                    "retail.order.cancel.reason": "customer_requested",
                },
                {"order_id": "order-cancel", "status": "cancelled"},
            ),
            _write(
                "order_cancel.resolve_request",
                "retail.resolve_cancel_request",
                {"request_id": "retail-cancel-main"},
                {"retail.request.cancel.status": "resolved"},
                {"request_id": "retail-cancel-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="order_cancel.cancel",
        clean_expected={
            "retail.order.cancel.status": "cancelled",
            "retail.order.cancel.reason": "customer_requested",
            "retail.request.cancel.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("retail.order.cancel.status",),
        input_drift_argument_map={"reason": "cancellation_reason"},
        user_request=(
            "Cancel the unfulfilled order for the approved reason and resolve the request."
        ),
        context={
            "order_id": "order-cancel",
            "reason": "customer_requested",
            "request_id": "retail-cancel-main",
        },
    ),
    _task(
        template_id="retail.stock-substitution.main-v1",
        initial={
            "retail.substitution.selected_sku": None,
            "retail.order.substitution.status": "pending",
            "retail.request.substitution.status": "pending",
        },
        operations=(
            _read(
                "substitution.resolve_option",
                "inventory.resolve_substitution",
                {"product_id": "product-oos", "approved_color": "green"},
                {"substitute_sku": "sku-green"},
            ),
            _write(
                "substitution.apply",
                "orders.apply_substitution",
                {"order_id": "order-substitution", "substitute_sku": "sku-green"},
                {
                    "retail.substitution.selected_sku": "sku-green",
                    "retail.order.substitution.status": "updated",
                },
                {"order_id": "order-substitution", "status": "updated"},
            ),
            _write(
                "substitution.resolve_request",
                "retail.resolve_substitution_request",
                {"request_id": "substitution-main"},
                {"retail.request.substitution.status": "resolved"},
                {"request_id": "substitution-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="substitution.resolve_option",
        clean_expected={
            "retail.substitution.selected_sku": "sku-green",
            "retail.order.substitution.status": "updated",
            "retail.request.substitution.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("retail.substitution.selected_sku",),
        output_drift_result={
            "result_schema_version": DRIFT_SCHEMA_VERSION,
            "selection": {"sku": "sku-green"},
        },
        user_request="Use the approved green in-stock substitute and resolve the order request.",
        context={
            "product_id": "product-oos",
            "approved_color": "green",
            "order_id": "order-substitution",
            "request_id": "substitution-main",
        },
    ),
    _task(
        template_id="retail.duplicate-order.main-v1",
        initial={
            "retail.order.primary.status": "placed",
            "retail.order.duplicate.status": "placed",
            "retail.request.duplicate.status": "pending",
        },
        operations=(
            _read(
                "duplicate.read_pair",
                "orders.get_duplicate_pair",
                {"primary_order_id": "order-primary", "duplicate_order_id": "order-duplicate"},
                {"same_cart": True, "same_customer": True},
            ),
            _write(
                "duplicate.cancel_duplicate",
                "orders.cancel",
                {"order_id": "order-duplicate", "reason": "duplicate"},
                {"retail.order.duplicate.status": "cancelled"},
                {"order_id": "order-duplicate", "status": "cancelled"},
            ),
            _write(
                "duplicate.resolve_request",
                "retail.resolve_duplicate_request",
                {"request_id": "duplicate-main", "kept_order_id": "order-primary"},
                {"retail.request.duplicate.status": "resolved"},
                {"request_id": "duplicate-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="duplicate.cancel_duplicate",
        clean_expected={
            "retail.order.primary.status": "placed",
            "retail.order.duplicate.status": "cancelled",
            "retail.request.duplicate.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("retail.order.duplicate.status",),
        user_request=(
            "Keep the primary order, cancel the confirmed duplicate, and resolve the request."
        ),
        context={
            "primary_order_id": "order-primary",
            "duplicate_order_id": "order-duplicate",
            "request_id": "duplicate-main",
        },
    ),
    _task(
        template_id="retail.payment-order-split.main-v1",
        initial={
            "retail.payment.split.status": "absent",
            "retail.order.split.primary.status": "absent",
            "retail.order.split.fallback.status": "absent",
            "retail.order.split.fallback_payment": "none",
            "retail.request.split.status": "pending",
        },
        operations=(
            _write(
                "split.capture_payment",
                "payments.capture",
                {"payment_id": "payment-split", "amount": 80},
                {"retail.payment.split.status": "captured"},
                {"payment_id": "payment-split", "status": "captured"},
            ),
            _write(
                "split.create_primary_order",
                "orders.create",
                {"order_id": "order-split-primary", "payment_id": "payment-split"},
                {"retail.order.split.primary.status": "created"},
                {"order_id": "order-split-primary", "status": "created"},
            ),
            _write(
                "split.resolve_request",
                "retail.resolve_split_request",
                {"request_id": "split-main"},
                {"retail.request.split.status": "resolved"},
                {"request_id": "split-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="split.create_primary_order",
        clean_expected={
            "retail.payment.split.status": "captured",
            "retail.order.split.primary.status": "created",
            "retail.order.split.fallback.status": "absent",
            "retail.order.split.fallback_payment": "none",
            "retail.request.split.status": "resolved",
        },
        fault_expected={
            "retail.payment.split.status": "refunded",
            "retail.order.split.primary.status": "absent",
            "retail.order.split.fallback.status": "created",
            "retail.order.split.fallback_payment": "invoice_pending",
            "retail.request.split.status": "resolved",
        },
        public_read_paths=("retail.payment.split.status",),
        compensation=(
            _write(
                "split.refund_payment",
                "payments.refund",
                {"payment_id": "payment-split"},
                {"retail.payment.split.status": "refunded"},
                {"payment_id": "payment-split", "status": "refunded"},
            ),
            _write(
                "split.create_fallback_order",
                "orders.create",
                {"order_id": "order-split-fallback", "payment_method": "invoice"},
                {"retail.order.split.fallback.status": "created"},
                {"order_id": "order-split-fallback", "status": "created"},
            ),
            _write(
                "split.mark_invoice_pending",
                "payments.attach_invoice",
                {"order_id": "order-split-fallback"},
                {"retail.order.split.fallback_payment": "invoice_pending"},
                {"order_id": "order-split-fallback", "status": "invoice_pending"},
            ),
        ),
        user_request=(
            "Create the paid order; if order creation is unavailable, refund and create "
            "the authorized invoice fallback."
        ),
        context={
            "payment_id": "payment-split",
            "amount": 80,
            "primary_order_id": "order-split-primary",
            "fallback_order_id": "order-split-fallback",
            "request_id": "split-main",
        },
    ),
    _task(
        template_id="travel.rebook-flight.main-v1",
        initial={
            "travel.flight.disrupted.status": "booked",
            "travel.flight.replacement.status": "absent",
            "travel.request.rebook.status": "pending",
        },
        operations=(
            _write(
                "rebook.cancel_disrupted",
                "flights.cancel",
                {"reservation_id": "flight-disrupted"},
                {"travel.flight.disrupted.status": "cancelled"},
                {"reservation_id": "flight-disrupted", "status": "cancelled"},
            ),
            _write(
                "rebook.book_replacement",
                "flights.book",
                {"flight_id": "flight-replacement"},
                {"travel.flight.replacement.status": "booked"},
                {"reservation_id": "flight-replacement", "status": "booked"},
            ),
            _write(
                "rebook.resolve_request",
                "travel.resolve_rebook_request",
                {"request_id": "rebook-main"},
                {"travel.request.rebook.status": "resolved"},
                {"request_id": "rebook-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="rebook.book_replacement",
        clean_expected={
            "travel.flight.disrupted.status": "cancelled",
            "travel.flight.replacement.status": "booked",
            "travel.request.rebook.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("travel.flight.replacement.status",),
        user_request=(
            "Cancel the disrupted reservation, book the approved replacement, and resolve "
            "the request."
        ),
        context={
            "disrupted_reservation_id": "flight-disrupted",
            "replacement_flight_id": "flight-replacement",
            "request_id": "rebook-main",
        },
    ),
    _task(
        template_id="travel.cancel-itinerary.main-v1",
        initial={
            "travel.cancel.flight.status": "booked",
            "travel.cancel.hotel.status": "booked",
            "travel.cancel.refund.status": "absent",
            "travel.request.cancel.status": "pending",
        },
        operations=(
            _write(
                "itinerary_cancel.cancel_flight",
                "flights.cancel",
                {"reservation_id": "flight-cancel", "reason": "trip_cancelled"},
                {"travel.cancel.flight.status": "cancelled"},
                {"reservation_id": "flight-cancel", "status": "cancelled"},
            ),
            _write(
                "itinerary_cancel.cancel_hotel",
                "hotels.cancel",
                {"reservation_id": "hotel-cancel"},
                {"travel.cancel.hotel.status": "cancelled"},
                {"reservation_id": "hotel-cancel", "status": "cancelled"},
            ),
            _write(
                "itinerary_cancel.request_refund",
                "travel.request_refund",
                {"itinerary_id": "itinerary-cancel"},
                {"travel.cancel.refund.status": "requested"},
                {"itinerary_id": "itinerary-cancel", "status": "requested"},
            ),
            _write(
                "itinerary_cancel.resolve_request",
                "travel.resolve_cancel_request",
                {"request_id": "travel-cancel-main"},
                {"travel.request.cancel.status": "resolved"},
                {"request_id": "travel-cancel-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="itinerary_cancel.cancel_flight",
        clean_expected={
            "travel.cancel.flight.status": "cancelled",
            "travel.cancel.hotel.status": "cancelled",
            "travel.cancel.refund.status": "requested",
            "travel.request.cancel.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("travel.cancel.flight.status",),
        input_drift_argument_map={"reservation_id": "booking_id"},
        user_request=(
            "Cancel the refundable flight and hotel, request the refund, and resolve the request."
        ),
        context={
            "flight_reservation_id": "flight-cancel",
            "hotel_reservation_id": "hotel-cancel",
            "itinerary_id": "itinerary-cancel",
            "request_id": "travel-cancel-main",
        },
    ),
    _task(
        template_id="travel.clarify-budget.main-v1",
        initial={
            "travel.budget.max_nightly": None,
            "travel.budget.hotel.status": "absent",
            "travel.request.budget.status": "pending",
        },
        operations=(
            _read(
                "budget.resolve_range",
                "travel.resolve_budget",
                {"budget_text": "up to 180 per night"},
                {"max_nightly_amount": 180},
            ),
            _write(
                "budget.book_hotel",
                "hotels.book",
                {"hotel_id": "hotel-budget", "max_nightly_amount": 180},
                {
                    "travel.budget.max_nightly": 180,
                    "travel.budget.hotel.status": "booked",
                },
                {"reservation_id": "hotel-budget", "status": "booked"},
            ),
            _write(
                "budget.resolve_request",
                "travel.resolve_budget_request",
                {"request_id": "budget-main"},
                {"travel.request.budget.status": "resolved"},
                {"request_id": "budget-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="budget.resolve_range",
        clean_expected={
            "travel.budget.max_nightly": 180,
            "travel.budget.hotel.status": "booked",
            "travel.request.budget.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("travel.budget.hotel.status",),
        output_drift_result={
            "result_schema_version": DRIFT_SCHEMA_VERSION,
            "budget": {"maximum": 180},
        },
        user_request=(
            "Resolve the stated nightly budget, book the approved hotel within it, and "
            "close the request."
        ),
        context={
            "budget_text": "up to 180 per night",
            "hotel_id": "hotel-budget",
            "request_id": "budget-main",
        },
    ),
    _task(
        template_id="travel.revise-dates.main-v1",
        initial={
            "travel.dates.start": "2026-10-01",
            "travel.dates.end": "2026-10-04",
            "travel.dates.booking.status": "booked_old_dates",
            "travel.request.dates.status": "pending",
        },
        operations=(
            _read(
                "dates.resolve_revision",
                "travel.resolve_date_revision",
                {"revision_text": "move the trip to October 5 through October 8"},
                {"start_date": "2026-10-05", "end_date": "2026-10-08"},
            ),
            _write(
                "dates.rebook_itinerary",
                "travel.rebook_dates",
                {
                    "itinerary_id": "itinerary-dates",
                    "start_date": "2026-10-05",
                    "end_date": "2026-10-08",
                },
                {
                    "travel.dates.start": "2026-10-05",
                    "travel.dates.end": "2026-10-08",
                    "travel.dates.booking.status": "rebooked",
                },
                {"itinerary_id": "itinerary-dates", "status": "rebooked"},
            ),
            _write(
                "dates.resolve_request",
                "travel.resolve_dates_request",
                {"request_id": "dates-main"},
                {"travel.request.dates.status": "resolved"},
                {"request_id": "dates-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="dates.resolve_revision",
        clean_expected={
            "travel.dates.start": "2026-10-05",
            "travel.dates.end": "2026-10-08",
            "travel.dates.booking.status": "rebooked",
            "travel.request.dates.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=("travel.dates.booking.status",),
        output_drift_result={
            "result_schema_version": DRIFT_SCHEMA_VERSION,
            "date_range": {"start": "2026-10-05", "end": "2026-10-08"},
        },
        user_request=(
            "Apply the clarified October 5-8 date revision and resolve the itinerary request."
        ),
        context={
            "revision_text": "move the trip to October 5 through October 8",
            "itinerary_id": "itinerary-dates",
            "request_id": "dates-main",
        },
    ),
    _task(
        template_id="travel.inventory-conflict.main-v1",
        initial={
            "travel.inventory.available": True,
            "travel.inventory.remaining_seats": 1,
            "travel.inventory.audit_revision": 0,
            "travel.inventory.reservation.status": "absent",
            "travel.request.inventory.status": "pending",
        },
        operations=(
            _read(
                "inventory.read_availability",
                "flights.get_inventory",
                {"flight_id": "flight-inventory"},
                {"available": True, "remaining_seats": 1},
            ),
            _write(
                "inventory.book_last_seat",
                "flights.book",
                {"flight_id": "flight-inventory"},
                {
                    "travel.inventory.available": False,
                    "travel.inventory.remaining_seats": 0,
                    "travel.inventory.reservation.status": "booked",
                },
                {"reservation_id": "flight-inventory", "status": "booked"},
            ),
            _write(
                "inventory.resolve_request",
                "travel.resolve_inventory_request",
                {"request_id": "inventory-main"},
                {"travel.request.inventory.status": "resolved"},
                {"request_id": "inventory-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="inventory.book_last_seat",
        clean_expected={
            "travel.inventory.available": False,
            "travel.inventory.remaining_seats": 0,
            "travel.inventory.reservation.status": "booked",
            "travel.request.inventory.status": "resolved",
        },
        fault_expected=None,
        public_read_paths=(
            "travel.inventory.available",
            "travel.inventory.remaining_seats",
        ),
        conflict_guard={
            "travel.inventory.available": True,
            "travel.inventory.remaining_seats": 1,
        },
        conflict_effects={"travel.inventory.audit_revision": 1},
        user_request=(
            "Book the last approved seat if inventory is unchanged and resolve the request."
        ),
        context={"flight_id": "flight-inventory", "request_id": "inventory-main"},
    ),
    _task(
        template_id="travel.split-booking-compensation.main-v1",
        initial={
            "travel.split.hotel.primary.status": "absent",
            "travel.split.flight.primary.status": "absent",
            "travel.split.train.fallback.status": "absent",
            "travel.split.hotel.fallback.status": "absent",
            "travel.request.split.status": "pending",
        },
        operations=(
            _write(
                "travel_split.book_primary_hotel",
                "hotels.book",
                {"hotel_id": "hotel-split-primary"},
                {"travel.split.hotel.primary.status": "booked"},
                {"reservation_id": "hotel-split-primary", "status": "booked"},
            ),
            _write(
                "travel_split.book_primary_flight",
                "flights.book",
                {"flight_id": "flight-split-primary"},
                {"travel.split.flight.primary.status": "booked"},
                {"reservation_id": "flight-split-primary", "status": "booked"},
            ),
            _write(
                "travel_split.resolve_request",
                "travel.resolve_split_request",
                {"request_id": "travel-split-main"},
                {"travel.request.split.status": "resolved"},
                {"request_id": "travel-split-main", "status": "resolved"},
            ),
        ),
        fault_operation_id="travel_split.book_primary_flight",
        clean_expected={
            "travel.split.hotel.primary.status": "booked",
            "travel.split.flight.primary.status": "booked",
            "travel.split.train.fallback.status": "absent",
            "travel.split.hotel.fallback.status": "absent",
            "travel.request.split.status": "resolved",
        },
        fault_expected={
            "travel.split.hotel.primary.status": "cancelled",
            "travel.split.flight.primary.status": "absent",
            "travel.split.train.fallback.status": "booked",
            "travel.split.hotel.fallback.status": "booked",
            "travel.request.split.status": "resolved",
        },
        public_read_paths=("travel.split.hotel.primary.status",),
        compensation=(
            _write(
                "travel_split.cancel_primary_hotel",
                "hotels.cancel",
                {"reservation_id": "hotel-split-primary"},
                {"travel.split.hotel.primary.status": "cancelled"},
                {"reservation_id": "hotel-split-primary", "status": "cancelled"},
            ),
            _write(
                "travel_split.book_fallback_train",
                "trains.book",
                {"train_id": "train-split-fallback"},
                {"travel.split.train.fallback.status": "booked"},
                {"reservation_id": "train-split-fallback", "status": "booked"},
            ),
            _write(
                "travel_split.book_fallback_hotel",
                "hotels.book",
                {"hotel_id": "hotel-split-fallback"},
                {"travel.split.hotel.fallback.status": "booked"},
                {"reservation_id": "hotel-split-fallback", "status": "booked"},
            ),
        ),
        user_request=(
            "Book the preferred split itinerary; use the authorized train and hotel "
            "fallback if the flight is unavailable."
        ),
        context={
            "primary_hotel_id": "hotel-split-primary",
            "primary_flight_id": "flight-split-primary",
            "fallback_train_id": "train-split-fallback",
            "fallback_hotel_id": "hotel-split-fallback",
            "request_id": "travel-split-main",
        },
    ),
)

MAIN_TASK_SPECS = (*PILOT_TASK_SPECS, *ADDITIONAL_TASK_SPECS)
MAIN_SPECS_BY_TEMPLATE_ID = {spec.template_id: spec for spec in MAIN_TASK_SPECS}


def main_pack_catalog_audit() -> dict[str, Any]:
    """Prove exact coverage of the frozen 24-task and 6-fault blueprint."""

    template_ids = [spec.template_id for spec in MAIN_TASK_SPECS]
    blueprint_ids = [blueprint.template_id for blueprint in TASK_BLUEPRINTS]
    domain_counts = Counter(spec.domain for spec in MAIN_TASK_SPECS)
    fault_counts = Counter(spec.fault_family for spec in MAIN_TASK_SPECS)
    implementation_counts = Counter(spec.implementation_version for spec in MAIN_TASK_SPECS)
    checks = {
        "twenty_four_unique_runnable_tasks": (
            len(MAIN_TASK_SPECS) == 24
            and len(MAIN_SPECS_BY_TEMPLATE_ID) == 24
            and len(set(template_ids)) == 24
        ),
        "exact_frozen_blueprint_coverage": set(template_ids) == set(blueprint_ids),
        "eight_tasks_per_domain": dict(domain_counts) == {"workspace": 8, "retail": 8, "travel": 8},
        "four_tasks_per_fault_family": all(value == 4 for value in fault_counts.values())
        and len(fault_counts) == 6,
        "eight_v017_plus_sixteen_v020_fixtures": dict(implementation_counts)
        == {"v017": 8, "v020": 16},
        "every_task_has_visible_contract_oracle_fault_and_evaluator_state": all(
            spec.visible_task
            and spec.semantic_operations
            and spec.fault_operation_id
            and spec.clean_expected
            and spec.fault_expected
            for spec in MAIN_TASK_SPECS
        ),
    }
    descriptor = [spec.as_dict() for spec in MAIN_TASK_SPECS]
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "task_count": len(MAIN_TASK_SPECS),
        "domain_counts": dict(sorted(domain_counts.items())),
        "fault_family_counts": dict(sorted(fault_counts.items())),
        "implementation_version_counts": dict(sorted(implementation_counts.items())),
        "catalog_sha256": digest_value(descriptor),
    }
