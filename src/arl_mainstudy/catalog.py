"""Auditable 24-template blueprint without pretending planned tasks are runnable."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Literal

from arl.core.types import digest_value
from arl_mainstudy.contract import DOMAIN_TEMPLATE_COUNTS, FAULT_FAMILY_COUNTS

Domain = Literal["workspace", "retail", "travel"]
ImplementationStatus = Literal["existing_core", "planned"]


@dataclass(frozen=True)
class TaskBlueprint:
    template_id: str
    task_id: str
    domain: Domain
    operation_pattern: str
    main_fault_family: str
    implementation_status: ImplementationStatus
    smoke_ready: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _blueprint(
    domain: Domain,
    slug: str,
    task_id: str,
    operation_pattern: str,
    fault: str,
    status: ImplementationStatus,
    *,
    smoke_ready: bool = False,
) -> TaskBlueprint:
    return TaskBlueprint(
        template_id=f"{domain}.{slug}.main-v1",
        task_id=task_id,
        domain=domain,
        operation_pattern=operation_pattern,
        main_fault_family=fault,
        implementation_status=status,
        smoke_ready=smoke_ready,
    )


TASK_BLUEPRINTS = (
    _blueprint(
        "workspace",
        "schedule-meeting",
        "workspace.schedule_meeting_and_notify",
        "create-and-notify",
        "postcommit_response_loss",
        "existing_core",
        smoke_ready=True,
    ),
    _blueprint(
        "workspace",
        "reschedule-meeting",
        "workspace.reschedule_meeting_and_notify",
        "update-and-notify",
        "postcommit_response_loss",
        "existing_core",
    ),
    _blueprint(
        "workspace",
        "cancel-meeting",
        "workspace.cancel_meeting_and_notify",
        "cancel-and-notify",
        "retryable_invocation_error",
        "planned",
    ),
    _blueprint(
        "workspace",
        "share-document",
        "workspace.share_document_with_policy",
        "policy-constrained-share",
        "input_schema_drift",
        "planned",
    ),
    _blueprint(
        "workspace",
        "resolve-schedule-conflict",
        "workspace.resolve_schedule_conflict",
        "conflict-resolution",
        "compatible_state_conflict",
        "planned",
    ),
    _blueprint(
        "workspace",
        "clarify-attendees",
        "workspace.clarify_attendee_scope",
        "clarify-before-write",
        "output_schema_drift",
        "planned",
    ),
    _blueprint(
        "workspace",
        "revised-authorization",
        "workspace.apply_revised_meeting_authorization",
        "revision-aware-write",
        "compatible_state_conflict",
        "planned",
    ),
    _blueprint(
        "workspace",
        "partial-change-compensation",
        "workspace.compensate_partial_workspace_change",
        "bounded-compensation",
        "bounded_compensation",
        "planned",
    ),
    _blueprint(
        "retail",
        "discounted-order",
        "retail.place_discounted_order",
        "policy-constrained-create",
        "postcommit_response_loss",
        "existing_core",
        smoke_ready=True,
    ),
    _blueprint(
        "retail",
        "partial-refund",
        "retail.issue_policy_compliant_partial_refund",
        "policy-constrained-refund",
        "postcommit_response_loss",
        "existing_core",
    ),
    _blueprint(
        "retail",
        "eligible-exchange",
        "retail.exchange_eligible_item",
        "exchange-transaction",
        "retryable_invocation_error",
        "planned",
    ),
    _blueprint(
        "retail",
        "cancel-order",
        "retail.cancel_unfulfilled_order",
        "state-dependent-cancel",
        "input_schema_drift",
        "planned",
    ),
    _blueprint(
        "retail",
        "stock-substitution",
        "retail.clarify_out_of_stock_substitution",
        "clarify-and-substitute",
        "output_schema_drift",
        "planned",
    ),
    _blueprint(
        "retail",
        "shipping-revision",
        "retail.revise_shipping_address",
        "revision-aware-update",
        "compatible_state_conflict",
        "planned",
    ),
    _blueprint(
        "retail",
        "duplicate-order",
        "retail.resolve_duplicate_order",
        "deduplicate-and-resolve",
        "retryable_invocation_error",
        "planned",
    ),
    _blueprint(
        "retail",
        "payment-order-split",
        "retail.compensate_payment_order_split",
        "bounded-compensation",
        "bounded_compensation",
        "planned",
    ),
    _blueprint(
        "travel",
        "book-itinerary",
        "travel.book_policy_compliant_itinerary",
        "multi-entity-booking",
        "input_schema_drift",
        "existing_core",
    ),
    _blueprint(
        "travel",
        "bundle-recovery",
        "travel.recover_bundle_after_flight_failure",
        "fallback-workflow",
        "bounded_compensation",
        "existing_core",
    ),
    _blueprint(
        "travel",
        "rebook-flight",
        "travel.rebook_disrupted_flight",
        "state-dependent-rebook",
        "retryable_invocation_error",
        "planned",
    ),
    _blueprint(
        "travel",
        "cancel-itinerary",
        "travel.cancel_refundable_itinerary",
        "policy-constrained-cancel",
        "input_schema_drift",
        "planned",
    ),
    _blueprint(
        "travel",
        "clarify-budget",
        "travel.clarify_hotel_budget",
        "clarify-before-booking",
        "output_schema_drift",
        "planned",
    ),
    _blueprint(
        "travel",
        "revise-dates",
        "travel.revise_trip_dates",
        "revision-aware-rebook",
        "output_schema_drift",
        "planned",
    ),
    _blueprint(
        "travel",
        "inventory-conflict",
        "travel.resolve_inventory_conflict",
        "conflict-resolution",
        "compatible_state_conflict",
        "planned",
    ),
    _blueprint(
        "travel",
        "split-booking-compensation",
        "travel.compensate_split_booking",
        "bounded-compensation",
        "bounded_compensation",
        "planned",
    ),
)

BLUEPRINTS_BY_TEMPLATE_ID = {item.template_id: item for item in TASK_BLUEPRINTS}
BLUEPRINTS_BY_TASK_ID = {item.task_id: item for item in TASK_BLUEPRINTS}


def catalog_audit() -> dict[str, Any]:
    domain_counts = Counter(item.domain for item in TASK_BLUEPRINTS)
    fault_counts = Counter(item.main_fault_family for item in TASK_BLUEPRINTS)
    status_counts = Counter(item.implementation_status for item in TASK_BLUEPRINTS)
    checks = {
        "twenty_four_unique_templates": (
            len(TASK_BLUEPRINTS) == 24
            and len(BLUEPRINTS_BY_TEMPLATE_ID) == 24
            and len(BLUEPRINTS_BY_TASK_ID) == 24
        ),
        "eight_templates_per_domain": dict(domain_counts) == DOMAIN_TEMPLATE_COUNTS,
        "four_templates_per_fault_family": dict(fault_counts) == FAULT_FAMILY_COUNTS,
        "six_existing_eighteen_planned": dict(status_counts) == {"existing_core": 6, "planned": 18},
        "two_scripted_smoke_adapters": sum(item.smoke_ready for item in TASK_BLUEPRINTS) == 2,
    }
    descriptor = [item.as_dict() for item in TASK_BLUEPRINTS]
    return {
        "checks": checks,
        "passed": all(checks.values()),
        "template_count": len(TASK_BLUEPRINTS),
        "domain_counts": dict(sorted(domain_counts.items())),
        "fault_family_counts": dict(sorted(fault_counts.items())),
        "implementation_status_counts": dict(sorted(status_counts.items())),
        "catalog_sha256": digest_value(descriptor),
    }
