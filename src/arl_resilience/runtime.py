"""Cross-domain guarded execution and auditable compensation runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from arl.core.types import StepResult, digest_value
from arl.runtime.journal import EventJournal
from arl_resilience.contracts import CompensationContract, GuardedAction, StateGuard
from arl_retail.env import RetailEnvironment
from arl_retail.runtime import RetailRuntime
from arl_travel.env import TravelEnvironment
from arl_travel.runtime import TravelRuntime

Environment = RetailEnvironment | TravelEnvironment
BaseRuntime = RetailRuntime | TravelRuntime
ProbeCounter = Literal["conflict", "compensation"]


@dataclass
class _Counters:
    tool_attempts: int = 0
    retry_count: int = 0
    confirmation_count: int = 0
    conflict_count: int = 0
    conflict_probe_count: int = 0
    conflict_rebase_count: int = 0
    conflict_abort_count: int = 0
    compensation_probe_count: int = 0
    result_contract_violations: int = 0


@dataclass(frozen=True)
class _ActionOutcome:
    succeeded: bool
    result: StepResult
    failure_code: str | None


@dataclass(frozen=True)
class ResilienceExecutionReport:
    runtime_name: str
    completed_plan: bool
    actions_planned: int
    recovery_actions_planned: int
    tool_attempts: int
    retry_count: int
    confirmation_count: int
    conflict_count: int
    conflict_probe_count: int
    conflict_rebase_count: int
    conflict_abort_count: int
    recovery_branch_count: int
    compensation_count: int
    compensation_contract_attempt_count: int
    compensation_contract_success_count: int
    compensation_contract_failure_count: int
    compensation_probe_count: int
    failure_code: str | None
    result_contract_violations: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TravelResiliencePlan:
    primary_actions: tuple[GuardedAction, ...]
    recovery_actions: tuple[GuardedAction | CompensationContract, ...]
    recovery_trigger_tool: str
    recovery_trigger_error: str


class _GuardedExecutor:
    def __init__(
        self,
        environment: Environment,
        journal: EventJournal,
        base_runtime: BaseRuntime,
    ) -> None:
        self.environment = environment
        self.journal = journal
        self.base_runtime = base_runtime
        self.known_state_version = environment.state_version
        self.max_conflict_rebases = 1
        self.counters = _Counters()

    def _append_conflict_event(
        self,
        *,
        event_type: str,
        step: GuardedAction,
        actual_values: list[Any] | None = None,
        error_code: str | None = None,
    ) -> None:
        state_hash = self.environment.state_hash()
        self.journal.append(
            timestamp_logical=self.environment.logical_time,
            actor="runtime",
            event_type=event_type,
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            input_digest=digest_value(
                {
                    "action_tool": step.action.tool_name,
                    "guards": [guard.audit_descriptor() for guard in step.guards],
                }
            ),
            output_digest=(
                digest_value([digest_value(value) for value in actual_values])
                if actual_values is not None
                else None
            ),
            tool_name=step.action.tool_name,
            schema_version=step.action.schema_version,
            error_code=error_code,
        )

    def probe_guards(
        self,
        guards: tuple[StateGuard, ...],
        *,
        counter: ProbeCounter,
        mismatch_code: str,
    ) -> tuple[bool, str | None, list[Any]]:
        actual_values: list[Any] = []
        for guard in guards:
            action = guard.read_action(self.environment.state_version)
            self.counters.tool_attempts += 1
            if counter == "conflict":
                self.counters.conflict_probe_count += 1
            else:
                self.counters.compensation_probe_count += 1
            self.base_runtime._append_action_started(self.environment, self.journal, action)
            result = self.environment.step(action)
            self.base_runtime._append_result(self.environment, self.journal, action, result)
            if not result.ok:
                return False, result.error_code or f"{counter}_probe_failed", actual_values
            if not self.base_runtime._result_contract_valid(
                self.environment,
                action,
                result,
            ):
                self.counters.result_contract_violations += 1
                return False, f"{counter}_probe_contract_violation", actual_values
            found, actual_value = guard.observed_value(result)
            if not found:
                return False, f"{counter}_probe_value_missing", actual_values
            actual_values.append(actual_value)
            if actual_value != guard.expected_value:
                return False, mismatch_code, actual_values
            self.known_state_version = result.state_version
        return True, None, actual_values

    def run(self, step: GuardedAction) -> _ActionOutcome:
        retry_attempt = 0
        step_rebases = 0
        while True:
            action = replace(
                step.action,
                expected_state_version=self.known_state_version,
            )
            self.counters.tool_attempts += 1
            self.base_runtime._append_action_started(self.environment, self.journal, action)
            result = self.environment.step(action)
            self.base_runtime._append_result(self.environment, self.journal, action, result)
            if result.ok:
                if not self.base_runtime._result_contract_valid(
                    self.environment,
                    action,
                    result,
                ):
                    self.counters.result_contract_violations += 1
                    return _ActionOutcome(False, result, "result_contract_violation")
                self.known_state_version = result.state_version
                return _ActionOutcome(True, result, None)

            ambiguous_commit = bool(
                result.status == "retryable_error"
                and result.error_code == "tool_timeout_postcommit"
                and action.idempotency_key is not None
                and result.state_hash_before != result.state_hash_after
            )
            if ambiguous_commit:
                self.counters.confirmation_count += 1
                self.counters.tool_attempts += 1
                confirmed, failure_code = self.base_runtime._confirm(
                    self.environment,
                    action,
                    self.journal,
                )
                if not confirmed:
                    return _ActionOutcome(False, result, failure_code)
                self.known_state_version = self.environment.state_version
                return _ActionOutcome(True, result, None)

            state_conflict = bool(
                result.status == "conflict" and result.error_code == "state_version_conflict"
            )
            if state_conflict:
                self.counters.conflict_count += 1
                self._append_conflict_event(
                    event_type="state_conflict_detected",
                    step=step,
                    error_code=result.error_code,
                )
                if not step.guards:
                    self.counters.conflict_abort_count += 1
                    return _ActionOutcome(False, result, "conflict_guard_missing")
                if step_rebases >= self.max_conflict_rebases:
                    self.counters.conflict_abort_count += 1
                    return _ActionOutcome(False, result, "conflict_rebase_limit_exceeded")
                matched, failure_code, actual_values = self.probe_guards(
                    step.guards,
                    counter="conflict",
                    mismatch_code="conflict_precondition_changed",
                )
                if not matched:
                    self.counters.conflict_abort_count += 1
                    self._append_conflict_event(
                        event_type="state_conflict_rejected",
                        step=step,
                        actual_values=actual_values,
                        error_code=failure_code,
                    )
                    return _ActionOutcome(False, result, failure_code)
                step_rebases += 1
                self.counters.conflict_rebase_count += 1
                self.known_state_version = self.environment.state_version
                self._append_conflict_event(
                    event_type="state_conflict_rebased",
                    step=step,
                    actual_values=actual_values,
                )
                continue

            if result.status == "retryable_error" and retry_attempt < self.base_runtime.max_retries:
                retry_attempt += 1
                self.counters.retry_count += 1
                self.journal.append(
                    timestamp_logical=result.timestamp_logical,
                    actor="runtime",
                    event_type="retry_scheduled",
                    state_hash_before=result.state_hash_after,
                    state_hash_after=result.state_hash_after,
                    input_digest=digest_value(
                        {
                            "attempt": retry_attempt,
                            "retry_after_ms": result.retry_after_ms,
                            "error_code": result.error_code,
                        }
                    ),
                    tool_name=action.tool_name,
                    schema_version=action.schema_version,
                    error_code=result.error_code,
                )
                continue
            return _ActionOutcome(False, result, result.error_code)


def _report(
    *,
    executor: _GuardedExecutor,
    actions_planned: int,
    recovery_actions_planned: int,
    recovery_branch_count: int,
    contract_attempts: int,
    contract_successes: int,
    contract_failures: int,
    failure_code: str | None,
) -> ResilienceExecutionReport:
    counters = executor.counters
    return ResilienceExecutionReport(
        runtime_name="r2_contract_guarded",
        completed_plan=failure_code is None,
        actions_planned=actions_planned,
        recovery_actions_planned=recovery_actions_planned,
        tool_attempts=counters.tool_attempts,
        retry_count=counters.retry_count,
        confirmation_count=counters.confirmation_count,
        conflict_count=counters.conflict_count,
        conflict_probe_count=counters.conflict_probe_count,
        conflict_rebase_count=counters.conflict_rebase_count,
        conflict_abort_count=counters.conflict_abort_count,
        recovery_branch_count=recovery_branch_count,
        compensation_count=contract_successes,
        compensation_contract_attempt_count=contract_attempts,
        compensation_contract_success_count=contract_successes,
        compensation_contract_failure_count=contract_failures,
        compensation_probe_count=counters.compensation_probe_count,
        failure_code=failure_code,
        result_contract_violations=counters.result_contract_violations,
    )


class RetailResilienceRuntime:
    """Run R2 confirmation plus exact guarded rebasing in Retail."""

    name = "r2_contract_guarded"

    def execute(
        self,
        environment: RetailEnvironment,
        plan: list[GuardedAction],
        journal: EventJournal,
    ) -> ResilienceExecutionReport:
        executor = _GuardedExecutor(environment, journal, RetailRuntime("r2_confirmed"))
        for step in plan:
            outcome = executor.run(step)
            if not outcome.succeeded:
                return _report(
                    executor=executor,
                    actions_planned=len(plan),
                    recovery_actions_planned=0,
                    recovery_branch_count=0,
                    contract_attempts=0,
                    contract_successes=0,
                    contract_failures=0,
                    failure_code=outcome.failure_code,
                )
        return _report(
            executor=executor,
            actions_planned=len(plan),
            recovery_actions_planned=0,
            recovery_branch_count=0,
            contract_attempts=0,
            contract_successes=0,
            contract_failures=0,
            failure_code=None,
        )


class TravelResilienceRuntime:
    """Run guarded R2 plus one registered compensation contract."""

    name = "r2_contract_guarded"

    @staticmethod
    def _append_contract_event(
        environment: TravelEnvironment,
        journal: EventJournal,
        contract: CompensationContract,
        *,
        event_type: str,
        error_code: str | None = None,
    ) -> None:
        state_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type=event_type,
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            input_digest=digest_value(contract.audit_descriptor()),
            tool_name=contract.action.tool_name,
            schema_version=contract.action.schema_version,
            error_code=error_code,
        )

    def execute(
        self,
        environment: TravelEnvironment,
        plan: TravelResiliencePlan,
        journal: EventJournal,
    ) -> ResilienceExecutionReport:
        executor = _GuardedExecutor(environment, journal, TravelRuntime("r2_confirmed"))
        recovery_branch_count = 0
        contract_attempts = 0
        contract_successes = 0
        contract_failures = 0

        failed_step: GuardedAction | None = None
        failed_outcome: _ActionOutcome | None = None
        for step in plan.primary_actions:
            outcome = executor.run(step)
            if not outcome.succeeded:
                failed_step = step
                failed_outcome = outcome
                break
        if failed_step is None or failed_outcome is None:
            return _report(
                executor=executor,
                actions_planned=len(plan.primary_actions),
                recovery_actions_planned=len(plan.recovery_actions),
                recovery_branch_count=0,
                contract_attempts=0,
                contract_successes=0,
                contract_failures=0,
                failure_code=None,
            )

        can_recover = bool(
            failed_step.action.tool_name == plan.recovery_trigger_tool
            and failed_outcome.failure_code == plan.recovery_trigger_error
        )
        if not can_recover:
            return _report(
                executor=executor,
                actions_planned=len(plan.primary_actions),
                recovery_actions_planned=len(plan.recovery_actions),
                recovery_branch_count=0,
                contract_attempts=0,
                contract_successes=0,
                contract_failures=0,
                failure_code=failed_outcome.failure_code,
            )

        recovery_branch_count = 1
        branch_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="recovery_branch_started",
            state_hash_before=branch_hash,
            state_hash_after=branch_hash,
            input_digest=digest_value(
                {
                    "trigger_tool": failed_step.action.tool_name,
                    "trigger_error": failed_outcome.failure_code,
                    "recovery_action_count": len(plan.recovery_actions),
                }
            ),
            tool_name=failed_step.action.tool_name,
            schema_version=failed_step.action.schema_version,
            error_code=failed_outcome.failure_code,
            fault_id=environment.last_fault_id,
        )

        for recovery_step in plan.recovery_actions:
            if isinstance(recovery_step, CompensationContract):
                contract_attempts += 1
                self._append_contract_event(
                    environment,
                    journal,
                    recovery_step,
                    event_type="compensation_contract_started",
                )
                if not recovery_step.matches_trigger(
                    failed_step.action.tool_name,
                    failed_outcome.failure_code,
                ):
                    contract_failures += 1
                    failure_code = "compensation_trigger_mismatch"
                    self._append_contract_event(
                        environment,
                        journal,
                        recovery_step,
                        event_type="compensation_contract_failed",
                        error_code=failure_code,
                    )
                    return _report(
                        executor=executor,
                        actions_planned=len(plan.primary_actions),
                        recovery_actions_planned=len(plan.recovery_actions),
                        recovery_branch_count=recovery_branch_count,
                        contract_attempts=contract_attempts,
                        contract_successes=contract_successes,
                        contract_failures=contract_failures,
                        failure_code=failure_code,
                    )
                matched, failure_code, _ = executor.probe_guards(
                    recovery_step.preconditions,
                    counter="compensation",
                    mismatch_code="compensation_precondition_changed",
                )
                if not matched:
                    contract_failures += 1
                    self._append_contract_event(
                        environment,
                        journal,
                        recovery_step,
                        event_type="compensation_contract_failed",
                        error_code=failure_code,
                    )
                    return _report(
                        executor=executor,
                        actions_planned=len(plan.primary_actions),
                        recovery_actions_planned=len(plan.recovery_actions),
                        recovery_branch_count=recovery_branch_count,
                        contract_attempts=contract_attempts,
                        contract_successes=contract_successes,
                        contract_failures=contract_failures,
                        failure_code=failure_code,
                    )
                outcome = executor.run(recovery_step.guarded_action())
                if not outcome.succeeded:
                    contract_failures += 1
                    self._append_contract_event(
                        environment,
                        journal,
                        recovery_step,
                        event_type="compensation_contract_failed",
                        error_code=outcome.failure_code,
                    )
                    return _report(
                        executor=executor,
                        actions_planned=len(plan.primary_actions),
                        recovery_actions_planned=len(plan.recovery_actions),
                        recovery_branch_count=recovery_branch_count,
                        contract_attempts=contract_attempts,
                        contract_successes=contract_successes,
                        contract_failures=contract_failures,
                        failure_code=outcome.failure_code,
                    )
                matched, failure_code, _ = executor.probe_guards(
                    recovery_step.postconditions,
                    counter="compensation",
                    mismatch_code="compensation_postcondition_changed",
                )
                if not matched:
                    contract_failures += 1
                    self._append_contract_event(
                        environment,
                        journal,
                        recovery_step,
                        event_type="compensation_contract_failed",
                        error_code=failure_code,
                    )
                    return _report(
                        executor=executor,
                        actions_planned=len(plan.primary_actions),
                        recovery_actions_planned=len(plan.recovery_actions),
                        recovery_branch_count=recovery_branch_count,
                        contract_attempts=contract_attempts,
                        contract_successes=contract_successes,
                        contract_failures=contract_failures,
                        failure_code=failure_code,
                    )
                contract_successes += 1
                self._append_contract_event(
                    environment,
                    journal,
                    recovery_step,
                    event_type="compensation_contract_succeeded",
                )
                continue

            outcome = executor.run(recovery_step)
            if not outcome.succeeded:
                return _report(
                    executor=executor,
                    actions_planned=len(plan.primary_actions),
                    recovery_actions_planned=len(plan.recovery_actions),
                    recovery_branch_count=recovery_branch_count,
                    contract_attempts=contract_attempts,
                    contract_successes=contract_successes,
                    contract_failures=contract_failures,
                    failure_code=outcome.failure_code,
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
                    "compensation_contracts": contract_successes,
                }
            ),
        )
        return _report(
            executor=executor,
            actions_planned=len(plan.primary_actions),
            recovery_actions_planned=len(plan.recovery_actions),
            recovery_branch_count=recovery_branch_count,
            contract_attempts=contract_attempts,
            contract_successes=contract_successes,
            contract_failures=contract_failures,
            failure_code=None,
        )
