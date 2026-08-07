"""R1/R2 runtime specialized for the synthetic Travel domain."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value
from arl.runtime.journal import EventJournal
from arl_travel.env import SCHEMA_VERSION, TravelEnvironment


@dataclass(frozen=True)
class TravelActionPlan:
    """A primary oracle path plus one bounded, pre-registered recovery branch."""

    primary_actions: tuple[ToolAction, ...]
    recovery_actions: tuple[ToolAction, ...] = ()
    recovery_trigger_tool: str | None = None
    recovery_trigger_error: str | None = None


@dataclass(frozen=True)
class TravelExecutionReport:
    runtime_name: str
    completed_plan: bool
    actions_planned: int
    recovery_actions_planned: int
    tool_attempts: int
    retry_count: int
    confirmation_count: int
    recovery_branch_count: int
    compensation_count: int
    failure_code: str | None
    result_contract_violations: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class TravelRuntime:
    """Run R1 guarded or R2 confirm-and-compensate semantics."""

    def __init__(self, name: str) -> None:
        if name not in {"r1_guarded", "r2_confirmed"}:
            raise ValueError(f"Unknown runtime: {name}")
        self.name = name
        self.max_retries = 1
        self.confirm_ambiguous_commits = name == "r2_confirmed"
        self.use_recovery_branch = name == "r2_confirmed"

    @staticmethod
    def _result_contract_valid(
        environment: TravelEnvironment,
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
                and value["price_cents"] >= 0
            )
        if action.tool_name == "flights.get_booking":
            return isinstance(value.get("booking"), dict)
        if action.tool_name == "hotels.book":
            return (
                value.get("booked_hotel_id") == action.arguments.get("hotel_id")
                and value.get("hotel_reservation_id") == action.arguments.get("reservation_id")
                and isinstance(value.get("price_cents"), int)
                and value["price_cents"] >= 0
            )
        if action.tool_name == "hotels.get_reservation":
            return isinstance(value.get("reservation"), dict)
        if action.tool_name == "hotels.cancel":
            return value.get("cancelled_reservation_id") == action.arguments.get("reservation_id")
        if action.tool_name == "travel.resolve_booking_request":
            return value.get("resolved_request_id") == action.arguments.get("request_id")
        return False

    @staticmethod
    def _append_action_started(
        environment: TravelEnvironment,
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
        environment: TravelEnvironment,
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

    @staticmethod
    def _confirmation_action(action: ToolAction, state_version: int) -> ToolAction | None:
        if action.tool_name == "flights.book":
            return ToolAction(
                tool_name="flights.get_booking",
                schema_version=SCHEMA_VERSION,
                arguments={"booking_id": action.arguments["booking_id"]},
                expected_state_version=state_version,
            )
        if action.tool_name == "hotels.book":
            return ToolAction(
                tool_name="hotels.get_reservation",
                schema_version=SCHEMA_VERSION,
                arguments={"reservation_id": action.arguments["reservation_id"]},
                expected_state_version=state_version,
            )
        return None

    @staticmethod
    def _confirmation_matches(original: ToolAction, result: StepResult) -> bool:
        if result.value is None:
            return False
        if original.tool_name == "flights.book":
            booking = result.value.get("booking")
            return bool(
                isinstance(booking, dict)
                and booking.get("booking_id") == original.arguments["booking_id"]
                and booking.get("flight_id") == original.arguments["flight_id"]
                and booking.get("user_id") == original.arguments["user_id"]
                and booking.get("payment_id") == original.arguments["payment_id"]
                and booking.get("status") == "booked"
                and isinstance(booking.get("price_cents"), int)
                and booking["price_cents"] >= 0
            )
        if original.tool_name == "hotels.book":
            reservation = result.value.get("reservation")
            return bool(
                isinstance(reservation, dict)
                and reservation.get("reservation_id") == original.arguments["reservation_id"]
                and reservation.get("hotel_id") == original.arguments["hotel_id"]
                and reservation.get("user_id") == original.arguments["user_id"]
                and reservation.get("payment_id") == original.arguments["payment_id"]
                and reservation.get("status") == "active"
                and isinstance(reservation.get("price_cents"), int)
                and reservation["price_cents"] >= 0
            )
        return False

    def _confirm(
        self,
        environment: TravelEnvironment,
        action: ToolAction,
        journal: EventJournal,
    ) -> tuple[bool, str | None]:
        confirmation = self._confirmation_action(action, environment.state_version)
        if confirmation is None:
            return False, "confirmation_not_supported"
        state_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="state_confirmation_started",
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            input_digest=digest_value(
                {
                    "tool_name": action.tool_name,
                    "request_digest": digest_value(action.as_dict()),
                }
            ),
            tool_name=confirmation.tool_name,
            schema_version=confirmation.schema_version,
        )
        self._append_action_started(environment, journal, confirmation)
        result = environment.step(confirmation)
        self._append_result(environment, journal, confirmation, result)
        if not result.ok or not self._result_contract_valid(environment, confirmation, result):
            return False, result.error_code or "confirmation_contract_violation"
        if not self._confirmation_matches(action, result):
            return False, "state_confirmation_mismatch"
        confirmed_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="state_confirmation_succeeded",
            state_hash_before=confirmed_hash,
            state_hash_after=confirmed_hash,
            input_digest=digest_value(action.as_dict()),
            output_digest=digest_value(result.as_dict()),
            tool_name=action.tool_name,
            schema_version=action.schema_version,
        )
        return True, None

    @staticmethod
    def _branch_matches(
        plan: TravelActionPlan,
        action: ToolAction,
        result: StepResult,
    ) -> bool:
        return bool(
            plan.recovery_actions
            and action.tool_name == plan.recovery_trigger_tool
            and result.error_code == plan.recovery_trigger_error
        )

    def _report(
        self,
        *,
        plan: TravelActionPlan,
        tool_attempts: int,
        retry_count: int,
        confirmation_count: int,
        recovery_branch_count: int,
        compensation_count: int,
        failure_code: str | None,
        contract_violations: int,
    ) -> TravelExecutionReport:
        return TravelExecutionReport(
            runtime_name=self.name,
            completed_plan=failure_code is None,
            actions_planned=len(plan.primary_actions),
            recovery_actions_planned=len(plan.recovery_actions),
            tool_attempts=tool_attempts,
            retry_count=retry_count,
            confirmation_count=confirmation_count,
            recovery_branch_count=recovery_branch_count,
            compensation_count=compensation_count,
            failure_code=failure_code,
            result_contract_violations=contract_violations,
        )

    def execute(
        self,
        environment: TravelEnvironment,
        plan: TravelActionPlan,
        journal: EventJournal,
    ) -> TravelExecutionReport:
        tool_attempts = 0
        retry_count = 0
        confirmation_count = 0
        recovery_branch_count = 0
        compensation_count = 0
        contract_violations = 0

        def run_action(action: ToolAction) -> tuple[bool, StepResult]:
            nonlocal tool_attempts, retry_count, confirmation_count, contract_violations
            attempt = 0
            while True:
                attempt += 1
                tool_attempts += 1
                self._append_action_started(environment, journal, action)
                result = environment.step(action)
                self._append_result(environment, journal, action, result)
                if result.ok:
                    if self._result_contract_valid(environment, action, result):
                        return True, result
                    contract_violations += 1
                    return False, result

                ambiguous_commit = (
                    self.confirm_ambiguous_commits
                    and result.status == "retryable_error"
                    and result.error_code == "tool_timeout_postcommit"
                    and action.idempotency_key is not None
                    and result.state_hash_before != result.state_hash_after
                )
                if ambiguous_commit:
                    confirmation_count += 1
                    tool_attempts += 1
                    confirmed, failure_code = self._confirm(environment, action, journal)
                    if confirmed:
                        return True, result
                    return False, StepResult(
                        status="fatal_error",
                        value=None,
                        error_code=failure_code,
                        state_version=environment.state_version,
                        retry_after_ms=None,
                        state_hash_before=environment.state_hash(),
                        state_hash_after=environment.state_hash(),
                        timestamp_logical=environment.logical_time,
                    )

                if result.status == "retryable_error" and attempt <= self.max_retries:
                    retry_count += 1
                    journal.append(
                        timestamp_logical=result.timestamp_logical,
                        actor="runtime",
                        event_type="retry_scheduled",
                        state_hash_before=result.state_hash_after,
                        state_hash_after=result.state_hash_after,
                        input_digest=digest_value(
                            {
                                "attempt": attempt,
                                "retry_after_ms": result.retry_after_ms,
                                "error_code": result.error_code,
                            }
                        ),
                        tool_name=action.tool_name,
                        schema_version=action.schema_version,
                        error_code=result.error_code,
                    )
                    continue
                return False, result

        failed_action: ToolAction | None = None
        failed_result: StepResult | None = None
        for action in plan.primary_actions:
            succeeded, result = run_action(action)
            if not succeeded:
                failed_action = action
                failed_result = result
                break
        if failed_action is None or failed_result is None:
            return self._report(
                plan=plan,
                tool_attempts=tool_attempts,
                retry_count=retry_count,
                confirmation_count=confirmation_count,
                recovery_branch_count=recovery_branch_count,
                compensation_count=compensation_count,
                failure_code=None,
                contract_violations=contract_violations,
            )

        contract_failure = failed_result.ok and not self._result_contract_valid(
            environment, failed_action, failed_result
        )
        failure_code = "result_contract_violation" if contract_failure else failed_result.error_code
        can_recover = self.use_recovery_branch and self._branch_matches(
            plan, failed_action, failed_result
        )
        if not can_recover:
            return self._report(
                plan=plan,
                tool_attempts=tool_attempts,
                retry_count=retry_count,
                confirmation_count=confirmation_count,
                recovery_branch_count=recovery_branch_count,
                compensation_count=compensation_count,
                failure_code=failure_code,
                contract_violations=contract_violations,
            )

        recovery_branch_count += 1
        branch_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="recovery_branch_started",
            state_hash_before=branch_hash,
            state_hash_after=branch_hash,
            input_digest=digest_value(
                {
                    "trigger_tool": failed_action.tool_name,
                    "trigger_error": failed_result.error_code,
                    "recovery_action_count": len(plan.recovery_actions),
                }
            ),
            tool_name=failed_action.tool_name,
            schema_version=failed_action.schema_version,
            error_code=failed_result.error_code,
            fault_id=environment.last_fault_id,
        )
        for recovery_action in plan.recovery_actions:
            succeeded, result = run_action(recovery_action)
            if not succeeded:
                branch_failure = (
                    "result_contract_violation"
                    if result.ok
                    else result.error_code or "recovery_action_failed"
                )
                return self._report(
                    plan=plan,
                    tool_attempts=tool_attempts,
                    retry_count=retry_count,
                    confirmation_count=confirmation_count,
                    recovery_branch_count=recovery_branch_count,
                    compensation_count=compensation_count,
                    failure_code=branch_failure,
                    contract_violations=contract_violations,
                )
            if recovery_action.tool_name == "hotels.cancel":
                compensation_count += 1
                compensation_hash = environment.state_hash()
                journal.append(
                    timestamp_logical=environment.logical_time,
                    actor="runtime",
                    event_type="compensation_succeeded",
                    state_hash_before=compensation_hash,
                    state_hash_after=compensation_hash,
                    input_digest=digest_value(recovery_action.as_dict()),
                    tool_name=recovery_action.tool_name,
                    schema_version=recovery_action.schema_version,
                )
        completed_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="recovery_branch_succeeded",
            state_hash_before=completed_hash,
            state_hash_after=completed_hash,
            output_digest=digest_value(
                {
                    "recovery_actions": len(plan.recovery_actions),
                    "compensations": compensation_count,
                }
            ),
        )
        return self._report(
            plan=plan,
            tool_attempts=tool_attempts,
            retry_count=retry_count,
            confirmation_count=confirmation_count,
            recovery_branch_count=recovery_branch_count,
            compensation_count=compensation_count,
            failure_code=None,
            contract_violations=contract_violations,
        )
