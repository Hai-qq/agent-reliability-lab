"""R1/R2 runtime comparison for public schema drift."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value
from arl.runtime.journal import EventJournal
from arl_schema.adapter import SchemaAdapter, SchemaAdapterError
from arl_schema.env import SchemaDriftEnvironment
from arl_travel.runtime import TravelActionPlan


@dataclass(frozen=True)
class SchemaExecutionReport:
    runtime_name: str
    completed_plan: bool
    actions_planned: int
    tool_attempts: int
    schema_adaptation_count: int
    output_normalization_count: int
    failure_code: str | None
    result_contract_violations: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SchemaRuntime:
    """Execute a fixed plan with or without descriptor-driven adaptation."""

    def __init__(self, name: str) -> None:
        if name not in {"r1_guarded", "r2_schema_adapted"}:
            raise ValueError(f"Unknown runtime: {name}")
        self.name = name
        self.use_adapter = name == "r2_schema_adapted"
        self.adapter = SchemaAdapter()

    @staticmethod
    def _result_contract_valid(
        environment: SchemaDriftEnvironment,
        action: ToolAction,
        result: StepResult,
    ) -> bool:
        if result.state_hash_after != environment.state_hash():
            return False
        if result.state_version != environment.state_version:
            return False
        value = result.value or {}
        if action.tool_name == "flights.book":
            return (
                value.get("booked_flight_id") == action.arguments.get("flight_id")
                and value.get("flight_booking_id") == action.arguments.get("booking_id")
                and isinstance(value.get("price_cents"), int)
                and not isinstance(value.get("price_cents"), bool)
                and value["price_cents"] >= 0
            )
        if action.tool_name == "hotels.book":
            return (
                value.get("booked_hotel_id") == action.arguments.get("hotel_id")
                and value.get("hotel_reservation_id") == action.arguments.get("reservation_id")
                and isinstance(value.get("price_cents"), int)
                and not isinstance(value.get("price_cents"), bool)
                and value["price_cents"] >= 0
            )
        if action.tool_name == "travel.resolve_booking_request":
            return value.get("resolved_request_id") == action.arguments.get("request_id")
        return False

    @staticmethod
    def _append_action_started(
        environment: SchemaDriftEnvironment,
        journal: EventJournal,
        action: ToolAction,
    ) -> None:
        state_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="action_started",
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            input_digest=digest_value(action.as_dict()),
            tool_name=action.tool_name,
            schema_version=action.schema_version,
        )

    @staticmethod
    def _append_result(
        environment: SchemaDriftEnvironment,
        journal: EventJournal,
        action: ToolAction,
        result: StepResult,
    ) -> None:
        journal.append(
            timestamp_logical=result.timestamp_logical,
            actor="environment",
            event_type="tool_succeeded" if result.ok else "tool_error",
            state_hash_before=result.state_hash_before,
            state_hash_after=result.state_hash_after,
            input_digest=digest_value(action.as_dict()),
            output_digest=digest_value(result.as_dict()),
            tool_name=action.tool_name,
            schema_version=action.schema_version,
            error_code=result.error_code,
            fault_id=environment.last_fault_id,
        )

    def execute(
        self,
        environment: SchemaDriftEnvironment,
        plan: TravelActionPlan,
        journal: EventJournal,
    ) -> SchemaExecutionReport:
        tool_attempts = 0
        adaptation_count = 0
        normalization_count = 0
        contract_violations = 0
        failure_code: str | None = None

        for canonical_action in plan.primary_actions:
            descriptor: dict[str, Any] | None = None
            dispatched_action = canonical_action
            if self.use_adapter:
                descriptor = environment.describe_tool(canonical_action.tool_name)
                try:
                    dispatched_action, adapted = self.adapter.adapt_action(
                        canonical_action,
                        descriptor,
                    )
                except SchemaAdapterError:
                    failure_code = "schema_adapter_error"
                    break
                if adapted:
                    adaptation_count += 1
                    state_hash = environment.state_hash()
                    journal.append(
                        timestamp_logical=environment.logical_time,
                        actor="runtime",
                        event_type="schema_adapter_applied",
                        state_hash_before=state_hash,
                        state_hash_after=state_hash,
                        input_digest=digest_value(descriptor),
                        output_digest=digest_value(dispatched_action.as_dict()),
                        tool_name=canonical_action.tool_name,
                        schema_version=dispatched_action.schema_version,
                    )

            tool_attempts += 1
            self._append_action_started(environment, journal, dispatched_action)
            raw_result = environment.step(dispatched_action)
            self._append_result(environment, journal, dispatched_action, raw_result)
            if not raw_result.ok:
                failure_code = raw_result.error_code or "tool_error"
                break

            canonical_result = raw_result
            if self.use_adapter:
                assert descriptor is not None
                try:
                    canonical_result, normalized = self.adapter.normalize_result(
                        tool_name=canonical_action.tool_name,
                        result=raw_result,
                        descriptor=descriptor,
                    )
                except SchemaAdapterError:
                    failure_code = "schema_adapter_error"
                    break
                if normalized:
                    normalization_count += 1
                    state_hash = environment.state_hash()
                    journal.append(
                        timestamp_logical=environment.logical_time,
                        actor="runtime",
                        event_type="output_adapter_applied",
                        state_hash_before=state_hash,
                        state_hash_after=state_hash,
                        input_digest=digest_value(raw_result.as_dict()),
                        output_digest=digest_value(canonical_result.as_dict()),
                        tool_name=canonical_action.tool_name,
                        schema_version=descriptor["result"]["schema_version"],
                        fault_id=environment.last_fault_id,
                    )

            if not self._result_contract_valid(
                environment,
                canonical_action,
                canonical_result,
            ):
                contract_violations += 1
                failure_code = "result_contract_violation"
                break

        return SchemaExecutionReport(
            runtime_name=self.name,
            completed_plan=failure_code is None,
            actions_planned=len(plan.primary_actions),
            tool_attempts=tool_attempts,
            schema_adaptation_count=adaptation_count,
            output_normalization_count=normalization_count,
            failure_code=failure_code,
            result_contract_violations=contract_violations,
        )
