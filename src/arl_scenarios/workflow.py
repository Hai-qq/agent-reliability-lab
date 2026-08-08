"""Bounded multi-step compensation workflow and Travel plan adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arl.core.types import Observation, ToolAction, digest_value
from arl.runtime.journal import EventJournal
from arl_resilience.contracts import CompensationContract, GuardedAction, StateGuard
from arl_resilience.runtime import (
    TravelResiliencePlan,
    TravelResilienceRuntime,
)
from arl_scenarios.env import ScenarioTravelEnvironment
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID, SCHEMA_VERSION
from arl_travel.experiment import task_plan


@dataclass(frozen=True)
class CompensationWorkflowStep:
    step_id: str
    action: ToolAction
    preconditions: tuple[StateGuard, ...] = ()
    postconditions: tuple[StateGuard, ...] = ()

    def __post_init__(self) -> None:
        if not self.step_id:
            raise ValueError("Compensation workflow step ID is required")
        if not isinstance(self.action.idempotency_key, str) or not self.action.idempotency_key:
            raise ValueError("Every compensation workflow write must be idempotent")

    def audit_descriptor(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action_tool": self.action.tool_name,
            "action_digest": digest_value(self.action.as_dict()),
            "preconditions": [item.audit_descriptor() for item in self.preconditions],
            "postconditions": [item.audit_descriptor() for item in self.postconditions],
        }


@dataclass(frozen=True)
class CompensationWorkflowContract:
    contract_id: str
    trigger_tool: str
    trigger_error: str
    steps: tuple[CompensationWorkflowStep, ...]
    terminal_postconditions: tuple[StateGuard, ...]
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not self.contract_id or not self.trigger_tool or not self.trigger_error:
            raise ValueError("Compensation workflow identity and trigger are required")
        if self.max_attempts != 1:
            raise ValueError("Compensation workflows currently allow exactly one attempt")
        if not 2 <= len(self.steps) <= 8:
            raise ValueError("Compensation workflows require two to eight bounded steps")
        if len({item.step_id for item in self.steps}) != len(self.steps):
            raise ValueError("Compensation workflow step IDs must be unique")
        first = self.steps[0]
        if not first.preconditions or not first.postconditions:
            raise ValueError("First workflow step requires preconditions and postconditions")
        if not self.terminal_postconditions:
            raise ValueError("Compensation workflow requires terminal postconditions")

    def audit_descriptor(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "trigger_tool": self.trigger_tool,
            "trigger_error": self.trigger_error,
            "steps": [item.audit_descriptor() for item in self.steps],
            "terminal_postconditions": [
                item.audit_descriptor() for item in self.terminal_postconditions
            ],
            "max_attempts": self.max_attempts,
        }

    def translated_actions(self) -> tuple[CompensationContract | GuardedAction, ...]:
        first, *remaining = self.steps
        single_action = CompensationContract(
            contract_id=f"{self.contract_id}.step.{first.step_id}",
            trigger_tool=self.trigger_tool,
            trigger_error=self.trigger_error,
            action=first.action,
            preconditions=first.preconditions,
            postconditions=first.postconditions,
        )
        return (
            single_action,
            *(GuardedAction(action=item.action, guards=item.preconditions) for item in remaining),
        )


@dataclass(frozen=True)
class ScenarioTravelPlan:
    primary_actions: tuple[GuardedAction, ...]
    workflow: CompensationWorkflowContract | None = None


def _guard(
    tool_name: str,
    arguments: dict[str, Any],
    value_path: tuple[str, ...],
    expected_value: Any,
) -> StateGuard:
    return StateGuard(
        tool_name=tool_name,
        schema_version=SCHEMA_VERSION,
        arguments=arguments,
        value_path=value_path,
        expected_value=expected_value,
    )


def _workflow_for_recovery(observation: Observation) -> CompensationWorkflowContract:
    base = task_plan(observation, "r2_confirmed")
    task = observation.visible_task
    preferred_reservation = task["preferred"]["hotel_reservation_id"]
    backup_booking = task["backup"]["flight_booking_id"]
    backup_reservation = task["backup"]["hotel_reservation_id"]
    request_id = task["request_id"]
    preferred_active = _guard(
        "hotels.get_reservation",
        {"reservation_id": preferred_reservation},
        ("reservation", "status"),
        "active",
    )
    preferred_cancelled = _guard(
        "hotels.get_reservation",
        {"reservation_id": preferred_reservation},
        ("reservation", "status"),
        "cancelled",
    )
    backup_flight_booked = _guard(
        "flights.get_booking",
        {"booking_id": backup_booking},
        ("booking", "status"),
        "booked",
    )
    backup_hotel_active = _guard(
        "hotels.get_reservation",
        {"reservation_id": backup_reservation},
        ("reservation", "status"),
        "active",
    )
    request_resolved = _guard(
        ScenarioTravelEnvironment.REQUEST_READ_TOOL,
        {"request_id": request_id},
        ("request", "status"),
        "resolved",
    )
    selected_flight = _guard(
        ScenarioTravelEnvironment.REQUEST_READ_TOOL,
        {"request_id": request_id},
        ("request", "selected_flight_booking_id"),
        backup_booking,
    )
    selected_hotel = _guard(
        ScenarioTravelEnvironment.REQUEST_READ_TOOL,
        {"request_id": request_id},
        ("request", "selected_hotel_reservation_id"),
        backup_reservation,
    )
    recovery = base.recovery_actions
    return CompensationWorkflowContract(
        contract_id="travel.fallback-booking.workflow.v1",
        trigger_tool=base.recovery_trigger_tool or "",
        trigger_error=base.recovery_trigger_error or "",
        steps=(
            CompensationWorkflowStep(
                "cancel-preferred-hotel",
                recovery[0],
                preconditions=(preferred_active,),
                postconditions=(preferred_cancelled,),
            ),
            CompensationWorkflowStep(
                "book-backup-flight",
                recovery[1],
                preconditions=(preferred_cancelled,),
                postconditions=(backup_flight_booked,),
            ),
            CompensationWorkflowStep(
                "book-backup-hotel",
                recovery[2],
                preconditions=(backup_flight_booked,),
                postconditions=(backup_hotel_active,),
            ),
            CompensationWorkflowStep(
                "resolve-backup-request",
                recovery[3],
                preconditions=(backup_flight_booked, backup_hotel_active),
                postconditions=(request_resolved,),
            ),
        ),
        terminal_postconditions=(
            preferred_cancelled,
            backup_flight_booked,
            backup_hotel_active,
            request_resolved,
            selected_flight,
            selected_hotel,
        ),
    )


def build_travel_scenario_plan(observation: Observation) -> ScenarioTravelPlan:
    base = task_plan(observation, "r2_confirmed")
    if observation.task_id == BOOK_TASK_ID:
        task = observation.visible_task
        flight_guard = _guard(
            "flights.get_booking",
            {"booking_id": task["flight_booking_id"]},
            ("booking", "status"),
            "booked",
        )
        hotel_guard = _guard(
            "hotels.get_reservation",
            {"reservation_id": task["hotel_reservation_id"]},
            ("reservation", "status"),
            "active",
        )
        return ScenarioTravelPlan(
            primary_actions=tuple(
                GuardedAction(
                    action=action,
                    guards=(flight_guard, hotel_guard)
                    if action.tool_name == "travel.resolve_booking_request"
                    else (),
                )
                for action in base.primary_actions
            )
        )
    if observation.task_id != RECOVERY_TASK_ID:
        raise ValueError(f"Unsupported Travel task: {observation.task_id}")
    return ScenarioTravelPlan(
        primary_actions=tuple(GuardedAction(action=action) for action in base.primary_actions),
        workflow=_workflow_for_recovery(observation),
    )


class ScenarioTravelRuntime:
    """Execute guarded Travel plans and verify a bounded workflow contract."""

    name = "r2_template_guarded"

    @staticmethod
    def _append_workflow_event(
        environment: ScenarioTravelEnvironment,
        journal: EventJournal,
        workflow: CompensationWorkflowContract,
        event_type: str,
        *,
        error_code: str | None = None,
    ) -> None:
        state_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type=event_type,
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            input_digest=digest_value(workflow.audit_descriptor()),
            error_code=error_code,
        )

    @staticmethod
    def _probe_terminal_guards(
        environment: ScenarioTravelEnvironment,
        journal: EventJournal,
        workflow: CompensationWorkflowContract,
    ) -> tuple[bool, str | None, int]:
        attempts = 0
        for guard in workflow.terminal_postconditions:
            attempts += 1
            before_hash = environment.state_hash()
            result = environment.step(guard.read_action(environment.state_version))
            found, value = guard.observed_value(result)
            matched = bool(result.ok and found and value == guard.expected_value)
            journal.append(
                timestamp_logical=result.timestamp_logical,
                actor="runtime",
                event_type=(
                    "compensation_workflow_guard_satisfied"
                    if matched
                    else "compensation_workflow_guard_failed"
                ),
                state_hash_before=before_hash,
                state_hash_after=environment.state_hash(),
                input_digest=digest_value(guard.audit_descriptor()),
                output_digest=digest_value(
                    {"found": found, "observed_digest": digest_value(value)}
                ),
                tool_name=guard.tool_name,
                schema_version=guard.schema_version,
                error_code=(
                    None if matched else result.error_code or "workflow_postcondition_changed"
                ),
            )
            if not matched:
                return False, result.error_code or "workflow_postcondition_changed", attempts
        return True, None, attempts

    def execute(
        self,
        environment: ScenarioTravelEnvironment,
        plan: ScenarioTravelPlan,
        journal: EventJournal,
    ) -> dict[str, Any]:
        workflow = plan.workflow
        if workflow is None:
            translated = TravelResiliencePlan(
                primary_actions=plan.primary_actions,
                recovery_actions=(),
                recovery_trigger_tool="",
                recovery_trigger_error="",
            )
        else:
            self._append_workflow_event(
                environment,
                journal,
                workflow,
                "compensation_workflow_registered",
            )
            translated = TravelResiliencePlan(
                primary_actions=plan.primary_actions,
                recovery_actions=workflow.translated_actions(),
                recovery_trigger_tool=workflow.trigger_tool,
                recovery_trigger_error=workflow.trigger_error,
            )
        report = TravelResilienceRuntime().execute(environment, translated, journal)
        value = report.as_dict()
        value["runtime_name"] = self.name
        value.update(
            {
                "workflow_contract_attempt_count": 0,
                "workflow_contract_success_count": 0,
                "workflow_contract_failure_count": 0,
                "workflow_terminal_probe_count": 0,
            }
        )
        if workflow is None or report.recovery_branch_count == 0:
            return value
        value["workflow_contract_attempt_count"] = 1
        if not report.completed_plan:
            value["workflow_contract_failure_count"] = 1
            self._append_workflow_event(
                environment,
                journal,
                workflow,
                "compensation_workflow_failed",
                error_code=report.failure_code,
            )
            return value
        matched, failure_code, probe_count = self._probe_terminal_guards(
            environment,
            journal,
            workflow,
        )
        value["tool_attempts"] += probe_count
        value["compensation_probe_count"] += probe_count
        value["workflow_terminal_probe_count"] = probe_count
        if not matched:
            value["completed_plan"] = False
            value["failure_code"] = failure_code
            value["workflow_contract_failure_count"] = 1
            self._append_workflow_event(
                environment,
                journal,
                workflow,
                "compensation_workflow_failed",
                error_code=failure_code,
            )
            return value
        value["workflow_contract_success_count"] = 1
        self._append_workflow_event(
            environment,
            journal,
            workflow,
            "compensation_workflow_succeeded",
        )
        return value
