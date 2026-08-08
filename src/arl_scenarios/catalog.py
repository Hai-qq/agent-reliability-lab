"""Fixed reliability task templates for the v0.12 scenario pack."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from arl.core.types import digest_value
from arl_retail.env import PURCHASE_TASK_ID, REFUND_TASK_ID
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID

Domain = Literal["retail", "travel"]

RETAIL_PURCHASE_TEMPLATE_ID = "retail.purchase-resolution.v1"
RETAIL_REFUND_TEMPLATE_ID = "retail.refund-resolution.v1"
TRAVEL_BOOK_TEMPLATE_ID = "travel.itinerary-resolution.v1"
TRAVEL_RECOVERY_TEMPLATE_ID = "travel.fallback-workflow.v1"


@dataclass(frozen=True)
class ReliabilityTaskTemplate:
    template_id: str
    domain: Domain
    task_id: str
    task_slug: str
    conflict_tool: str
    compatible_fault_id: str
    incompatible_fault_id: str
    guard_count: int
    compensation_type: str | None = None

    def __post_init__(self) -> None:
        if not all(
            (
                self.template_id,
                self.task_id,
                self.task_slug,
                self.conflict_tool,
                self.compatible_fault_id,
                self.incompatible_fault_id,
            )
        ):
            raise ValueError("Task template identity and conflict metadata are required")
        if self.guard_count < 1:
            raise ValueError("Task templates require at least one public-read guard")

    def audit_descriptor(self) -> dict[str, object]:
        value = asdict(self)
        value["template_digest"] = digest_value(value)
        return value


TASK_TEMPLATES = (
    ReliabilityTaskTemplate(
        template_id=RETAIL_PURCHASE_TEMPLATE_ID,
        domain="retail",
        task_id=PURCHASE_TASK_ID,
        task_slug="retail-purchase",
        conflict_tool="retail.resolve_purchase_request",
        compatible_fault_id="fault.scenario.retail.purchase.metadata_change_once",
        incompatible_fault_id="fault.scenario.retail.purchase.order_change_once",
        guard_count=1,
    ),
    ReliabilityTaskTemplate(
        template_id=RETAIL_REFUND_TEMPLATE_ID,
        domain="retail",
        task_id=REFUND_TASK_ID,
        task_slug="retail-refund",
        conflict_tool="retail.resolve_refund_request",
        compatible_fault_id="fault.scenario.retail.refund.metadata_change_once",
        incompatible_fault_id="fault.scenario.retail.refund.status_change_once",
        guard_count=1,
    ),
    ReliabilityTaskTemplate(
        template_id=TRAVEL_BOOK_TEMPLATE_ID,
        domain="travel",
        task_id=BOOK_TASK_ID,
        task_slug="travel-book",
        conflict_tool="travel.resolve_booking_request",
        compatible_fault_id="fault.scenario.travel.book.metadata_change_once",
        incompatible_fault_id="fault.scenario.travel.book.reservation_change_once",
        guard_count=2,
    ),
    ReliabilityTaskTemplate(
        template_id=TRAVEL_RECOVERY_TEMPLATE_ID,
        domain="travel",
        task_id=RECOVERY_TASK_ID,
        task_slug="travel-recovery",
        conflict_tool="hotels.cancel",
        compatible_fault_id="fault.scenario.travel.recovery.metadata_change_once",
        incompatible_fault_id="fault.scenario.travel.recovery.reservation_change_once",
        guard_count=1,
        compensation_type="bounded_workflow",
    ),
)

TEMPLATES_BY_ID = {item.template_id: item for item in TASK_TEMPLATES}
TEMPLATES_BY_TASK_ID = {item.task_id: item for item in TASK_TEMPLATES}

if len(TEMPLATES_BY_ID) != len(TASK_TEMPLATES):  # pragma: no cover - import-time gate
    raise RuntimeError("Reliability task template IDs must be unique")
if len(TEMPLATES_BY_TASK_ID) != len(TASK_TEMPLATES):  # pragma: no cover - import-time gate
    raise RuntimeError("Reliability task IDs must be unique")
