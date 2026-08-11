"""Twenty-four unseen synthetic task templates with three frozen data seeds."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from functools import cache
from typing import Any

from arl.core.types import ToolAction, digest_value
from arl_mainpack.specs import MAIN_SPECS_BY_TEMPLATE_ID, MAIN_TASK_SPECS
from arl_mainstudy.contract import DOMAIN_TEMPLATE_COUNTS, FAULT_FAMILY_COUNTS
from arl_mainstudy.model import ToolDefinition
from arl_pilot.specs import CANONICAL_SCHEMA_VERSION, OperationSpec

ENVIRONMENT_SEEDS = (29_101, 29_211, 29_307)


@dataclass(frozen=True)
class HoldoutTemplate:
    """One task-level holdout declaration frozen before provider execution."""

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


HOLDOUT_TEMPLATES = (
    HoldoutTemplate(
        "workspace.schedule-meeting.main-v1",
        "workspace.coordinate-review-session.holdout-v1",
        "Create the review session at the approved time, invite the listed participants, "
        "and close the scheduling request.",
    ),
    HoldoutTemplate(
        "workspace.reschedule-meeting.main-v1",
        "workspace.move-planning-session.holdout-v1",
        "Move the planning session to the approved slot, notify its participants, and "
        "close the change request.",
    ),
    HoldoutTemplate(
        "retail.discounted-order.main-v1",
        "retail.place-campaign-order.holdout-v1",
        "Create the approved campaign purchase with the supplied coupon and close the "
        "purchase request.",
    ),
    HoldoutTemplate(
        "retail.eligible-exchange.main-v1",
        "retail.exchange-damaged-item.holdout-v1",
        "Create the authorized replacement exchange and close its request.",
    ),
    HoldoutTemplate(
        "travel.book-itinerary.main-v1",
        "travel.reserve-conference-trip.holdout-v1",
        "Reserve the approved conference flight and lodging, then close the travel request.",
    ),
    HoldoutTemplate(
        "workspace.clarify-attendees.main-v1",
        "workspace.resolve-review-participants.holdout-v1",
        "Resolve the participant handles, create the review session, invite the resolved "
        "people, and close the request.",
    ),
    HoldoutTemplate(
        "retail.shipping-revision.main-v1",
        "retail.correct-delivery-destination.holdout-v1",
        "Verify the order, apply the authorized destination correction, and close the request.",
    ),
    HoldoutTemplate(
        "travel.bundle-recovery.main-v1",
        "travel.recover-retreat-bundle.holdout-v1",
        "Reserve the preferred retreat bundle; if its preferred leg is unavailable, use only "
        "the authorized fallback bundle.",
    ),
    HoldoutTemplate(
        "workspace.cancel-meeting.main-v1",
        "workspace.withdraw-training-session.holdout-v1",
        "Cancel the scheduled training session, notify its participants, and close the request.",
    ),
    HoldoutTemplate(
        "workspace.share-document.main-v1",
        "workspace.grant-draft-access.holdout-v1",
        "Grant the approved reviewer access to the draft with the authorized role and close "
        "the request.",
    ),
    HoldoutTemplate(
        "workspace.resolve-schedule-conflict.main-v1",
        "workspace.move-conflicting-workshop.holdout-v1",
        "Move the conflicting workshop to the approved free slot and close the request.",
    ),
    HoldoutTemplate(
        "workspace.revised-authorization.main-v1",
        "workspace.apply-revised-room-approval.holdout-v1",
        "Apply the supplied authorization revision to the room booking and close the request.",
    ),
    HoldoutTemplate(
        "workspace.partial-change-compensation.main-v1",
        "workspace.publish-controlled-copy.holdout-v1",
        "Create the approved controlled copy; use the team-only fallback if external access "
        "cannot be granted.",
    ),
    HoldoutTemplate(
        "retail.partial-refund.main-v1",
        "retail.issue-service-credit.holdout-v1",
        "Issue the approved partial service credit and close the request.",
    ),
    HoldoutTemplate(
        "retail.cancel-order.main-v1",
        "retail.cancel-unpacked-order.holdout-v1",
        "Cancel the unfulfilled order for the supplied approved reason and close the request.",
    ),
    HoldoutTemplate(
        "retail.stock-substitution.main-v1",
        "retail.apply-approved-substitute.holdout-v1",
        "Use the approved in-stock substitute for the order and close the request.",
    ),
    HoldoutTemplate(
        "retail.duplicate-order.main-v1",
        "retail.remove-duplicate-subscription.holdout-v1",
        "Keep the primary purchase, cancel the confirmed duplicate, and close the request.",
    ),
    HoldoutTemplate(
        "retail.payment-order-split.main-v1",
        "retail.recover-paid-order-creation.holdout-v1",
        "Create the paid order; if creation is unavailable, refund it and use only the "
        "authorized invoice fallback.",
    ),
    HoldoutTemplate(
        "travel.rebook-flight.main-v1",
        "travel.replace-disrupted-leg.holdout-v1",
        "Cancel the disrupted reservation, reserve the approved replacement, and close the "
        "request.",
    ),
    HoldoutTemplate(
        "travel.cancel-itinerary.main-v1",
        "travel.cancel-training-trip.holdout-v1",
        "Cancel the refundable trip components, request the refund, and close the travel request.",
    ),
    HoldoutTemplate(
        "travel.clarify-budget.main-v1",
        "travel.resolve-lodging-cap.holdout-v1",
        "Resolve the stated lodging cap, reserve the approved option within it, and close the "
        "request.",
    ),
    HoldoutTemplate(
        "travel.revise-dates.main-v1",
        "travel.apply-workshop-date-change.holdout-v1",
        "Resolve and apply the supplied workshop date change, then close the itinerary request.",
    ),
    HoldoutTemplate(
        "travel.inventory-conflict.main-v1",
        "travel.reserve-last-approved-seat.holdout-v1",
        "Reserve the last approved seat only if inventory is unchanged, then close the request.",
    ),
    HoldoutTemplate(
        "travel.split-booking-compensation.main-v1",
        "travel.recover-mixed-mode-itinerary.holdout-v1",
        "Reserve the preferred itinerary; if its flight is unavailable, use only the authorized "
        "mixed-mode fallback.",
    ),
)

HOLDOUT_TEMPLATES_BY_ID = {item.template_id: item for item in HOLDOUT_TEMPLATES}
CANARY_TEMPLATE_IDS = tuple(
    next(item.template_id for item in HOLDOUT_TEMPLATES if item.fault_family == family)
    for family in FAULT_FAMILY_COUNTS
)


@dataclass(frozen=True)
class HoldoutTaskSpec:
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
    implementation_version: str = "v029"

    def __post_init__(self) -> None:
        if self.environment_seed not in ENVIRONMENT_SEEDS:
            raise ValueError("Holdout environment seed is not frozen")
        if self.domain not in DOMAIN_TEMPLATE_COUNTS:
            raise ValueError("Unknown holdout domain")
        if self.fault_family not in FAULT_FAMILY_COUNTS:
            raise ValueError("Unknown holdout fault family")
        if not self.template_id.endswith(".holdout-v1") or not self.task_id:
            raise ValueError("Holdout identifiers are invalid")
        operations = self.all_operations
        operation_ids = [operation.operation_id for operation in operations]
        if len(operation_ids) != len(set(operation_ids)):
            raise ValueError("Holdout operation IDs must be unique")
        if self.fault_operation_id not in {
            operation.operation_id for operation in self.semantic_operations
        }:
            raise ValueError("Holdout fault operation is not semantic")
        if len({operation.tool_name for operation in self.semantic_operations}) != len(
            self.semantic_operations
        ):
            raise ValueError("Holdout model tools must be unique within a task")
        initial_paths = {path for path, _ in self.initial_values}
        all_effect_paths = {path for operation in operations for path, _ in operation.effects} | {
            path for path, _ in self.conflict_effects
        }
        expected_paths = {path for path, _ in (*self.clean_expected, *self.fault_expected)}
        if not expected_paths.issubset(initial_paths | all_effect_paths):
            raise ValueError("Holdout expected state has no definition")
        if not all_effect_paths.issubset(self.allowed_change_paths):
            raise ValueError("Holdout effect is not evaluator-allowed")
        if not set(self.public_read_paths).issubset(initial_paths | all_effect_paths):
            raise ValueError("Holdout public read path has no state definition")
        if not {path for path, _ in self.conflict_guard}.issubset(self.public_read_paths):
            raise ValueError("Holdout conflict guard is not publicly readable")
        if self.fault_family == "bounded_compensation" and not self.compensation_operations:
            raise ValueError("Holdout compensation task has no fallback workflow")
        if self.fault_family != "bounded_compensation" and self.compensation_operations:
            raise ValueError("Unexpected holdout compensation workflow")
        if self.fault_family == "input_schema_drift" and not self.input_drift_argument_map:
            raise ValueError("Holdout input drift task has no field map")
        if self.fault_family != "input_schema_drift" and self.input_drift_argument_map:
            raise ValueError("Unexpected holdout input field map")
        if self.fault_family == "output_schema_drift" and not self.output_drift_result:
            raise ValueError("Holdout output drift task has no drifted result")
        if self.fault_family != "output_schema_drift" and self.output_drift_result:
            raise ValueError("Unexpected holdout output drift result")
        conflict_fields = bool(self.conflict_guard) and bool(self.conflict_effects)
        if (self.fault_family == "compatible_state_conflict") != conflict_fields:
            raise ValueError("Holdout conflict contract is incomplete or unexpected")
        if not self.user_request or not self.visible_context:
            raise ValueError("Holdout visible task contract is incomplete")

    @property
    def fault_id(self) -> str:
        return f"fault.holdout.v29.{self.template_id}.{self.fault_family}"

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
        raise ValueError(f"Unknown holdout condition: {condition}")

    def operation(self, operation_id: str) -> OperationSpec:
        try:
            return next(item for item in self.all_operations if item.operation_id == operation_id)
        except StopIteration as error:
            raise KeyError(f"Unknown holdout operation: {operation_id}") from error

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
    offset = 7 * (seed_index + 1) + template_index % 3
    suffix = f"h29-{template_index + 1:02d}-s{seed_index + 1}"
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
    return f"holdout.v29.t{template_index + 1:02d}.s{seed_index + 1}.{path}"


def _operation(
    source: OperationSpec,
    *,
    mapping: dict[tuple[type, Any], Any],
    template_index: int,
    seed_index: int,
) -> OperationSpec:
    return OperationSpec(
        operation_id=f"h29.t{template_index + 1:02d}.{source.operation_id}",
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
def holdout_spec(template_id: str, environment_seed: int) -> HoldoutTaskSpec:
    declaration = HOLDOUT_TEMPLATES_BY_ID[template_id]
    source = declaration.source
    template_index = HOLDOUT_TEMPLATES.index(declaration)
    try:
        seed_index = ENVIRONMENT_SEEDS.index(environment_seed)
    except ValueError as error:
        raise ValueError("Holdout environment seed is not frozen") from error
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

    return HoldoutTaskSpec(
        template_id=declaration.template_id,
        task_id=f"arl.holdout.v29.{declaration.template_id}",
        source_template_id=declaration.source_template_id,
        domain=declaration.domain,
        fault_family=declaration.fault_family,
        environment_seed=environment_seed,
        initial_values=tuple(
            (path(state_path), _replace_scalars(value, mapping))
            for state_path, value in source.initial_values
        ),
        semantic_operations=operations,
        fault_operation_id=f"h29.t{template_index + 1:02d}.{source.fault_operation_id}",
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


def specs_for_seed(environment_seed: int) -> tuple[HoldoutTaskSpec, ...]:
    return tuple(holdout_spec(item.template_id, environment_seed) for item in HOLDOUT_TEMPLATES)


def all_seeded_specs() -> tuple[HoldoutTaskSpec, ...]:
    return tuple(
        holdout_spec(item.template_id, seed)
        for item in HOLDOUT_TEMPLATES
        for seed in ENVIRONMENT_SEEDS
    )


def holdout_catalog_audit() -> dict[str, Any]:
    base_ids = {spec.template_id for spec in MAIN_TASK_SPECS}
    template_ids = [item.template_id for item in HOLDOUT_TEMPLATES]
    source_ids = [item.source_template_id for item in HOLDOUT_TEMPLATES]
    variants = all_seeded_specs()
    context_digests = {
        item.template_id: {
            digest_value(holdout_spec(item.template_id, seed).visible_task["context"])
            for seed in ENVIRONMENT_SEEDS
        }
        for item in HOLDOUT_TEMPLATES
    }
    variant_digests = {
        item.template_id: {
            digest_value(holdout_spec(item.template_id, seed).as_dict())
            for seed in ENVIRONMENT_SEEDS
        }
        for item in HOLDOUT_TEMPLATES
    }
    checks = {
        "exact_24_holdout_templates": len(HOLDOUT_TEMPLATES) == 24,
        "unique_holdout_template_ids": len(set(template_ids)) == 24,
        "disjoint_from_v028_template_ids": not (set(template_ids) & base_ids),
        "one_to_one_frozen_source_archetypes": len(set(source_ids)) == 24
        and set(source_ids) == base_ids,
        "three_balanced_domains": Counter(item.domain for item in HOLDOUT_TEMPLATES)
        == DOMAIN_TEMPLATE_COUNTS,
        "six_balanced_fault_families": Counter(item.fault_family for item in HOLDOUT_TEMPLATES)
        == FAULT_FAMILY_COUNTS,
        "requests_are_new_and_unique": len({item.user_request for item in HOLDOUT_TEMPLATES}) == 24
        and not (
            {item.user_request for item in HOLDOUT_TEMPLATES}
            & {spec.visible_task["user_request"] for spec in MAIN_TASK_SPECS}
        ),
        "exact_three_frozen_environment_seeds": len(set(ENVIRONMENT_SEEDS)) == 3,
        "exact_72_seeded_variants": len(variants) == 72,
        "context_varies_across_all_three_seeds": all(
            len(values) == 3 for values in context_digests.values()
        ),
        "full_spec_varies_across_all_three_seeds": all(
            len(values) == 3 for values in variant_digests.values()
        ),
        "six_canary_tasks_cover_six_fault_families": {
            HOLDOUT_TEMPLATES_BY_ID[item].fault_family for item in CANARY_TEMPLATE_IDS
        }
        == set(FAULT_FAMILY_COUNTS),
    }
    payload = {
        "catalog_version": "arl-holdout-task-catalog-v0.29.0",
        "selection_disclosure": (
            "New task IDs, requests, record identities, values, and state namespaces; the six "
            "runtime mechanism archetypes and public tool schemas are intentionally reused."
        ),
        "environment_seeds": list(ENVIRONMENT_SEEDS),
        "templates": [asdict(item) for item in HOLDOUT_TEMPLATES],
        "seeded_variant_sha256": {
            item.template_id: {
                str(seed): digest_value(holdout_spec(item.template_id, seed).as_dict())
                for seed in ENVIRONMENT_SEEDS
            }
            for item in HOLDOUT_TEMPLATES
        },
    }
    return {
        **payload,
        "catalog_sha256": digest_value(payload),
        "checks": checks,
        "passed": all(checks.values()),
    }
