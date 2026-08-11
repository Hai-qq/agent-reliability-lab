"""Twenty-four unseen synthetic task templates with three frozen data seeds."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from functools import cache
from typing import Any

from arl.core.types import ToolAction, digest_value
from arl_holdout_v29.specs import (
    ENVIRONMENT_SEEDS as V029_ENVIRONMENT_SEEDS,
)
from arl_holdout_v29.specs import (
    HOLDOUT_TEMPLATES as V029_TEMPLATES,
)
from arl_holdout_v29.specs import (
    holdout_spec as v029_spec,
)
from arl_mainpack.specs import MAIN_SPECS_BY_TEMPLATE_ID, MAIN_TASK_SPECS
from arl_mainstudy.contract import DOMAIN_TEMPLATE_COUNTS, FAULT_FAMILY_COUNTS
from arl_mainstudy.model import ToolDefinition
from arl_pilot.specs import CANONICAL_SCHEMA_VERSION, OperationSpec

ENVIRONMENT_SEEDS = (30_113, 30_229, 30_347)


@dataclass(frozen=True)
class ReplicationTemplate:
    """One task-level replication declaration frozen before provider execution."""

    source_template_id: str
    template_id: str
    user_request: str

    @property
    def source(self) -> Any:
        return MAIN_SPECS_BY_TEMPLATE_ID[self.source_template_id]

    @property
    def domain(self) -> str:
        return self.source.domain

    @property
    def fault_family(self) -> str:
        return self.source.fault_family


REPLICATION_TEMPLATES = (
    ReplicationTemplate(
        "workspace.schedule-meeting.main-v1",
        "workspace.convene-release-readiness-review.replication-v1",
        "Schedule the authorized release-readiness review for the provided slot, add every "
        "approved attendee, and mark the coordination item complete.",
    ),
    ReplicationTemplate(
        "workspace.reschedule-meeting.main-v1",
        "workspace.shift-quarterly-planning-forum.replication-v1",
        "Shift the quarterly planning forum to the newly approved time, inform all existing "
        "participants, and complete the change item.",
    ),
    ReplicationTemplate(
        "retail.discounted-order.main-v1",
        "retail.submit-partner-promotion-order.replication-v1",
        "Submit the authorized partner-promotion purchase with the provided discount code, "
        "then complete the purchase item.",
    ),
    ReplicationTemplate(
        "retail.eligible-exchange.main-v1",
        "retail.replace-defective-bundle.replication-v1",
        "Open the approved replacement exchange for the defective bundle and finish the "
        "service item.",
    ),
    ReplicationTemplate(
        "travel.book-itinerary.main-v1",
        "travel.book-standards-summit-journey.replication-v1",
        "Book the approved flight and hotel for the standards summit, then complete the "
        "travel item.",
    ),
    ReplicationTemplate(
        "workspace.clarify-attendees.main-v1",
        "workspace.disambiguate-audit-reviewers.replication-v1",
        "Resolve the ambiguous audit-reviewer handles, schedule the approved review, invite "
        "the resolved people, and complete the request.",
    ),
    ReplicationTemplate(
        "retail.shipping-revision.main-v1",
        "retail.amend-office-delivery-address.replication-v1",
        "Confirm the referenced purchase, apply its authorized office-delivery correction, "
        "and finish the update item.",
    ),
    ReplicationTemplate(
        "travel.bundle-recovery.main-v1",
        "travel.recover-field-offsite-package.replication-v1",
        "Book the preferred field-offsite package; if its preferred segment is unavailable, "
        "use only the explicitly approved alternate package.",
    ),
    ReplicationTemplate(
        "workspace.cancel-meeting.main-v1",
        "workspace.cancel-safety-briefing.replication-v1",
        "Cancel the scheduled safety briefing, alert its participants, and complete the "
        "cancellation item.",
    ),
    ReplicationTemplate(
        "workspace.share-document.main-v1",
        "workspace.share-proposal-with-editor.replication-v1",
        "Give the approved editor the authorized role on the proposal and finish the access "
        "request.",
    ),
    ReplicationTemplate(
        "workspace.resolve-schedule-conflict.main-v1",
        "workspace.relocate-overlapping-clinic.replication-v1",
        "Move the overlapping clinic to the authorized available slot and complete the "
        "scheduling item.",
    ),
    ReplicationTemplate(
        "workspace.revised-authorization.main-v1",
        "workspace.apply-updated-studio-permit.replication-v1",
        "Apply the supplied permit revision to the studio reservation and complete the "
        "authorization item.",
    ),
    ReplicationTemplate(
        "workspace.partial-change-compensation.main-v1",
        "workspace.release-internal-review-copy.replication-v1",
        "Create the approved review copy; if external sharing cannot be completed, use only "
        "the authorized internal-access fallback.",
    ),
    ReplicationTemplate(
        "retail.partial-refund.main-v1",
        "retail.grant-shipping-delay-credit.replication-v1",
        "Apply the authorized partial credit for the shipping delay and complete the service item.",
    ),
    ReplicationTemplate(
        "retail.cancel-order.main-v1",
        "retail.void-unpicked-supply-order.replication-v1",
        "Void the not-yet-picked supply order using the approved reason and complete the "
        "cancellation item.",
    ),
    ReplicationTemplate(
        "retail.stock-substitution.main-v1",
        "retail.swap-to-approved-backup-sku.replication-v1",
        "Replace the unavailable line with its approved in-stock backup SKU and complete the "
        "order update.",
    ),
    ReplicationTemplate(
        "retail.duplicate-order.main-v1",
        "retail.cancel-duplicate-renewal.replication-v1",
        "Preserve the primary renewal, cancel the verified duplicate, and complete the "
        "cleanup item.",
    ),
    ReplicationTemplate(
        "retail.payment-order-split.main-v1",
        "retail.recover-settled-checkout.replication-v1",
        "Create the order for the settled payment; if order creation is unavailable, refund "
        "it and use only the authorized invoicing fallback.",
    ),
    ReplicationTemplate(
        "travel.rebook-flight.main-v1",
        "travel.rebook-cancelled-connection.replication-v1",
        "Cancel the disrupted connection, reserve the approved substitute, and complete the "
        "rebooking item.",
    ),
    ReplicationTemplate(
        "travel.cancel-itinerary.main-v1",
        "travel.cancel-client-visit-package.replication-v1",
        "Cancel every refundable component of the client visit, request the refund, and "
        "complete the travel item.",
    ),
    ReplicationTemplate(
        "travel.clarify-budget.main-v1",
        "travel.resolve-hotel-nightly-limit.replication-v1",
        "Resolve the stated nightly hotel limit, book the approved option within that limit, "
        "and complete the request.",
    ),
    ReplicationTemplate(
        "travel.revise-dates.main-v1",
        "travel.move-certification-travel-dates.replication-v1",
        "Resolve the supplied certification date revision, apply it to the itinerary, and "
        "complete the change item.",
    ),
    ReplicationTemplate(
        "travel.inventory-conflict.main-v1",
        "travel.claim-final-authorized-ticket.replication-v1",
        "Book the final authorized ticket only when the inventory guard still matches, then "
        "complete the reservation item.",
    ),
    ReplicationTemplate(
        "travel.split-booking-compensation.main-v1",
        "travel.recover-rail-air-fallback.replication-v1",
        "Book the preferred route; if its flight segment is unavailable, use only the "
        "authorized rail-and-air recovery route.",
    ),
)

REPLICATION_TEMPLATES_BY_ID = {item.template_id: item for item in REPLICATION_TEMPLATES}
CANARY_TEMPLATE_IDS = tuple(
    next(item.template_id for item in REPLICATION_TEMPLATES if item.fault_family == family)
    for family in FAULT_FAMILY_COUNTS
)


@dataclass(frozen=True)
class ReplicationTaskSpec:
    """A duck-compatible task spec that does not mutate the frozen v0.20 catalog."""

    template_id: str
    task_id: str
    source_template_id: str
    domain: str
    fault_family: str
    environment_seed: int
    initial_values: tuple[tuple[str, Any], ...]
    semantic_operations: tuple[OperationSpec, ...]
    fault_operation_id: str
    clean_expected: tuple[tuple[str, Any], ...]
    fault_expected: tuple[tuple[str, Any], ...]
    allowed_change_paths: tuple[str, ...]
    public_read_paths: tuple[str, ...]
    compensation_operations: tuple[OperationSpec, ...]
    conflict_guard: tuple[tuple[str, Any], ...]
    input_drift_argument_map: tuple[tuple[str, str], ...]
    output_drift_result: tuple[tuple[str, Any], ...]
    conflict_effects: tuple[tuple[str, Any], ...]
    user_request: str
    visible_context: tuple[tuple[str, Any], ...]
    implementation_version: str = "v030"

    def __post_init__(self) -> None:
        if self.environment_seed not in ENVIRONMENT_SEEDS:
            raise ValueError("Replication environment seed is not frozen")
        if self.domain not in DOMAIN_TEMPLATE_COUNTS:
            raise ValueError("Unknown replication domain")
        if self.fault_family not in FAULT_FAMILY_COUNTS:
            raise ValueError("Unknown replication fault family")
        if not self.template_id.endswith(".replication-v1") or not self.task_id:
            raise ValueError("Replication identifiers are invalid")
        operations = self.all_operations
        operation_ids = [operation.operation_id for operation in operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Replication operation IDs must be unique")
        if self.fault_operation_id not in {
            operation.operation_id for operation in self.semantic_operations
        }:
            raise ValueError("Replication fault operation is not semantic")
        if len({operation.tool_name for operation in self.semantic_operations}) != len(
            self.semantic_operations
        ):
            raise ValueError("Replication model tools must be unique within a task")
        initial_paths = {path for path, _ in self.initial_values}
        all_effect_paths = {path for operation in operations for path, _ in operation.effects} | {
            path for path, _ in self.conflict_effects
        }
        expected_paths = {path for path, _ in (*self.clean_expected, *self.fault_expected)}
        if not expected_paths.issubset(initial_paths | all_effect_paths):
            raise ValueError("Replication expected state has no definition")
        if not all_effect_paths.issubset(self.allowed_change_paths):
            raise ValueError("Replication effect is not evaluator-allowed")
        if not set(self.public_read_paths).issubset(initial_paths | all_effect_paths):
            raise ValueError("Replication public read path has no state definition")
        if not {path for path, _ in self.conflict_guard}.issubset(self.public_read_paths):
            raise ValueError("Replication conflict guard is not publicly readable")
        if self.fault_family == "bounded_compensation" and not self.compensation_operations:
            raise ValueError("Replication compensation task has no fallback workflow")
        if self.fault_family != "bounded_compensation" and self.compensation_operations:
            raise ValueError("Unexpected replication compensation workflow")
        if self.fault_family == "input_schema_drift" and not self.input_drift_argument_map:
            raise ValueError("Replication input drift task has no field map")
        if self.fault_family != "input_schema_drift" and self.input_drift_argument_map:
            raise ValueError("Unexpected replication input field map")
        if self.fault_family == "output_schema_drift" and not self.output_drift_result:
            raise ValueError("Replication output drift task has no drifted result")
        if self.fault_family != "output_schema_drift" and self.output_drift_result:
            raise ValueError("Unexpected replication output drift result")
        conflict_fields = bool(self.conflict_guard) and bool(self.conflict_effects)
        if (self.fault_family == "compatible_state_conflict") != conflict_fields:
            raise ValueError("Replication conflict contract is incomplete or unexpected")
        if not self.user_request or not self.visible_context:
            raise ValueError("Replication visible task contract is incomplete")

    @property
    def fault_id(self) -> str:
        return f"fault.replication.v30.{self.template_id}.{self.fault_family}"

    @property
    def all_operations(self) -> tuple[OperationSpec, ...]:
        return (*self.semantic_operations, *self.compensation_operations)

    @property
    def initial_values_dict(self) -> dict[str, Any]:
        return dict(self.initial_values)

    @property
    def semantic_actions(self) -> tuple[ToolAction, ...]:
        return tuple(operation.semantic_action() for operation in self.semantic_operations)

    @property
    def visible_task(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "domain": self.domain,
            "user_request": self.user_request,
            "context": dict(self.visible_context),
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

    def expected_values(self, condition: str) -> dict[str, Any]:
        if condition == "clean":
            return dict(self.clean_expected)
        if condition == "recoverable_fault":
            return dict(self.fault_expected)
        raise ValueError(f"Unknown replication condition: {condition}")

    def operation(self, operation_id: str) -> OperationSpec:
        try:
            return next(item for item in self.all_operations if item.operation_id == operation_id)
        except StopIteration as error:
            raise KeyError(f"Unknown replication operation: {operation_id}") from error

    def drifted_arguments(self, operation: OperationSpec) -> dict[str, Any]:
        if operation.operation_id != self.fault_operation_id:
            raise ValueError("Input drift is defined only for the fault operation")
        rename = dict(self.input_drift_argument_map)
        return {rename.get(name, name): value for name, value in operation.arguments.items()}

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "task_id": self.task_id,
            "source_template_id": self.source_template_id,
            "domain": self.domain,
            "fault_family": self.fault_family,
            "environment_seed": self.environment_seed,
            "initial_values": [list(item) for item in self.initial_values],
            "semantic_operations": [item.as_dict() for item in self.semantic_operations],
            "fault_operation_id": self.fault_operation_id,
            "clean_expected": [list(item) for item in self.clean_expected],
            "fault_expected": [list(item) for item in self.fault_expected],
            "allowed_change_paths": list(self.allowed_change_paths),
            "public_read_paths": list(self.public_read_paths),
            "compensation_operations": [item.as_dict() for item in self.compensation_operations],
            "conflict_guard": [list(item) for item in self.conflict_guard],
            "input_drift_argument_map": [list(item) for item in self.input_drift_argument_map],
            "output_drift_result": [list(item) for item in self.output_drift_result],
            "conflict_effects": [list(item) for item in self.conflict_effects],
            "visible_task": self.visible_task,
            "implementation_version": self.implementation_version,
        }


def _context_leaves(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _context_leaves(item)]
    if isinstance(value, (list, tuple)):
        return [leaf for item in value for leaf in _context_leaves(item)]
    return [value]


def _shift_string(value: str, *, offset: int, suffix: str) -> str:
    try:
        if "T" in value:
            return (datetime.fromisoformat(value) + timedelta(days=offset)).isoformat(
                timespec="minutes"
            )
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return (datetime.fromisoformat(value).date() + timedelta(days=offset)).isoformat()
    except ValueError:
        pass
    budget = re.fullmatch(r"up to (\d+) per night", value)
    if budget:
        return f"up to {int(budget.group(1)) + offset} per night"
    if " " in value:
        return f"{value} [{suffix}]"
    return f"{value}-{suffix}"


def _scalar_mapping(context: dict[str, Any], *, template_index: int, seed_index: int) -> dict:
    offset = 11 * (seed_index + 1) + template_index % 5
    suffix = f"r30-{template_index + 1:02d}-s{seed_index + 1}"
    mapping: dict[tuple[type, Any], Any] = {}
    for value in _context_leaves(context):
        if type(value) is str:
            mapping[(str, value)] = _shift_string(value, offset=offset, suffix=suffix)
        elif type(value) is int:
            mapping[(int, value)] = value + offset
        elif type(value) is float:
            mapping[(float, value)] = value + float(offset)
    return mapping


def _replace_scalars(value: Any, mapping: dict[tuple[type, Any], Any]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_scalars(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_scalars(item, mapping) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_scalars(item, mapping) for item in value)
    return mapping.get((type(value), value), value)


def _state_path(template_index: int, seed_index: int, path: str) -> str:
    return f"replication.v30.t{template_index + 1:02d}.s{seed_index + 1}.{path}"


def _operation(
    source: OperationSpec,
    *,
    mapping: dict[tuple[type, Any], Any],
    template_index: int,
    seed_index: int,
) -> OperationSpec:
    return OperationSpec(
        operation_id=f"r30.t{template_index + 1:02d}.{source.operation_id}",
        tool_name=source.tool_name,
        arguments=_replace_scalars(source.arguments, mapping),
        is_write=source.is_write,
        effects=tuple(
            (
                _state_path(template_index, seed_index, path),
                _replace_scalars(value, mapping),
            )
            for path, value in source.effects
        ),
        result_value=_replace_scalars(source.result_value, mapping),
        required_result_fields=source.required_result_fields,
    )


@cache
def replication_spec(template_id: str, environment_seed: int) -> ReplicationTaskSpec:
    declaration = REPLICATION_TEMPLATES_BY_ID[template_id]
    source = declaration.source
    template_index = REPLICATION_TEMPLATES.index(declaration)
    try:
        seed_index = ENVIRONMENT_SEEDS.index(environment_seed)
    except ValueError as error:
        raise ValueError("Replication environment seed is not frozen") from error
    mapping = _scalar_mapping(
        source.visible_task["context"],
        template_index=template_index,
        seed_index=seed_index,
    )
    operations = tuple(
        _operation(
            item,
            mapping=mapping,
            template_index=template_index,
            seed_index=seed_index,
        )
        for item in source.semantic_operations
    )
    compensation = tuple(
        _operation(
            item,
            mapping=mapping,
            template_index=template_index,
            seed_index=seed_index,
        )
        for item in source.compensation_operations
    )

    def path(value: str) -> str:
        return _state_path(template_index, seed_index, value)

    return ReplicationTaskSpec(
        template_id=declaration.template_id,
        task_id=f"arl.replication.v30.{declaration.template_id}",
        source_template_id=declaration.source_template_id,
        domain=declaration.domain,
        fault_family=declaration.fault_family,
        environment_seed=environment_seed,
        initial_values=tuple(
            (path(state_path), _replace_scalars(value, mapping))
            for state_path, value in source.initial_values
        ),
        semantic_operations=operations,
        fault_operation_id=f"r30.t{template_index + 1:02d}.{source.fault_operation_id}",
        clean_expected=tuple(
            (path(state_path), _replace_scalars(value, mapping))
            for state_path, value in source.clean_expected
        ),
        fault_expected=tuple(
            (path(state_path), _replace_scalars(value, mapping))
            for state_path, value in source.fault_expected
        ),
        allowed_change_paths=tuple(path(item) for item in source.allowed_change_paths),
        public_read_paths=tuple(path(item) for item in source.public_read_paths),
        compensation_operations=compensation,
        conflict_guard=tuple(
            (path(state_path), _replace_scalars(value, mapping))
            for state_path, value in source.conflict_guard
        ),
        input_drift_argument_map=source.input_drift_argument_map,
        output_drift_result=tuple(
            (name, _replace_scalars(value, mapping)) for name, value in source.output_drift_result
        ),
        conflict_effects=tuple(
            (path(state_path), _replace_scalars(value, mapping))
            for state_path, value in source.conflict_effects
        ),
        user_request=declaration.user_request,
        visible_context=tuple(_replace_scalars(source.visible_task["context"], mapping).items()),
    )


def specs_for_seed(environment_seed: int) -> tuple[ReplicationTaskSpec, ...]:
    return tuple(
        replication_spec(item.template_id, environment_seed) for item in REPLICATION_TEMPLATES
    )


def all_seeded_specs() -> tuple[ReplicationTaskSpec, ...]:
    return tuple(
        replication_spec(item.template_id, seed)
        for item in REPLICATION_TEMPLATES
        for seed in ENVIRONMENT_SEEDS
    )


def replication_catalog_audit() -> dict[str, Any]:
    base_ids = {spec.template_id for spec in MAIN_TASK_SPECS}
    v029_ids = {item.template_id for item in V029_TEMPLATES}
    prior_requests = {
        *(spec.visible_task["user_request"] for spec in MAIN_TASK_SPECS),
        *(item.user_request for item in V029_TEMPLATES),
    }
    template_ids = [item.template_id for item in REPLICATION_TEMPLATES]
    source_ids = [item.source_template_id for item in REPLICATION_TEMPLATES]
    variants = all_seeded_specs()
    context_digests = {
        item.template_id: {
            digest_value(replication_spec(item.template_id, seed).visible_task["context"])
            for seed in ENVIRONMENT_SEEDS
        }
        for item in REPLICATION_TEMPLATES
    }
    v029_context_digests = {
        digest_value(v029_spec(item.template_id, seed).visible_task["context"])
        for item in V029_TEMPLATES
        for seed in V029_ENVIRONMENT_SEEDS
    }
    variant_digests = {
        item.template_id: {
            digest_value(replication_spec(item.template_id, seed).as_dict())
            for seed in ENVIRONMENT_SEEDS
        }
        for item in REPLICATION_TEMPLATES
    }
    checks = {
        "exact_24_replication_templates": len(REPLICATION_TEMPLATES) == 24,
        "unique_replication_template_ids": len(set(template_ids)) == 24,
        "disjoint_from_v028_and_v029_template_ids": not (set(template_ids) & (base_ids | v029_ids)),
        "one_to_one_frozen_source_archetypes": len(set(source_ids)) == 24
        and set(source_ids) == base_ids,
        "three_balanced_domains": Counter(item.domain for item in REPLICATION_TEMPLATES)
        == DOMAIN_TEMPLATE_COUNTS,
        "six_balanced_fault_families": Counter(item.fault_family for item in REPLICATION_TEMPLATES)
        == FAULT_FAMILY_COUNTS,
        "requests_are_new_unique_and_disjoint_from_v028_v029": (
            len({item.user_request for item in REPLICATION_TEMPLATES}) == 24
            and not ({item.user_request for item in REPLICATION_TEMPLATES} & prior_requests)
        ),
        "exact_three_frozen_environment_seeds": len(set(ENVIRONMENT_SEEDS)) == 3,
        "environment_seeds_disjoint_from_v029": not (
            set(ENVIRONMENT_SEEDS) & set(V029_ENVIRONMENT_SEEDS)
        ),
        "exact_72_seeded_variants": len(variants) == 72,
        "context_varies_across_all_three_seeds": all(
            len(values) == 3 for values in context_digests.values()
        ),
        "contexts_disjoint_from_v029": not (
            {value for values in context_digests.values() for value in values}
            & v029_context_digests
        ),
        "full_spec_varies_across_all_three_seeds": all(
            len(values) == 3 for values in variant_digests.values()
        ),
        "six_canary_tasks_cover_six_fault_families": {
            REPLICATION_TEMPLATES_BY_ID[item].fault_family for item in CANARY_TEMPLATE_IDS
        }
        == set(FAULT_FAMILY_COUNTS),
    }
    payload = {
        "catalog_version": "arl-replication-task-catalog-v0.30.0",
        "selection_disclosure": (
            "New task IDs, requests, environment seeds, record identities, values, and state "
            "namespaces relative to both v0.28 and v0.29; the six runtime mechanism archetypes "
            "and public tool schemas are intentionally reused."
        ),
        "prior_catalogs_excluded": ["v0.28 main pack", "v0.29 prospective holdout"],
        "environment_seeds": list(ENVIRONMENT_SEEDS),
        "templates": [asdict(item) for item in REPLICATION_TEMPLATES],
        "seeded_variant_sha256": {
            item.template_id: {
                str(seed): digest_value(replication_spec(item.template_id, seed).as_dict())
                for seed in ENVIRONMENT_SEEDS
            }
            for item in REPLICATION_TEMPLATES
        },
    }
    return {
        **payload,
        "catalog_sha256": digest_value(payload),
        "checks": checks,
        "passed": all(checks.values()),
    }
