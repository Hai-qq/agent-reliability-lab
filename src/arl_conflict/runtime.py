"""Conflict-aware R2 runtime with guarded, bounded state-version rebasing."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value
from arl.envs.workspace import SCHEMA_VERSION
from arl.runtime.journal import EventJournal
from arl_conflict.env import ConflictWorkspaceEnvironment
from arl_multitask.runtime import MultiTaskRuntime


@dataclass(frozen=True)
class ConflictGuard:
    """A public read and expected value used to validate a safe rebase."""

    tool_name: str
    arguments: dict[str, Any]
    value_path: tuple[str, ...]
    expected_value: Any

    def read_action(self, state_version: int) -> ToolAction:
        return ToolAction(
            tool_name=self.tool_name,
            schema_version=SCHEMA_VERSION,
            arguments=self.arguments,
            expected_state_version=state_version,
        )

    def observed_value(self, result: StepResult) -> tuple[bool, Any]:
        value: Any = result.value
        for key in self.value_path:
            if not isinstance(value, dict) or key not in value:
                return False, None
            value = value[key]
        return True, value

    def matches(self, result: StepResult) -> bool:
        found, value = self.observed_value(result)
        return found and value == self.expected_value


@dataclass(frozen=True)
class ConflictPlanStep:
    action: ToolAction
    guard: ConflictGuard | None


@dataclass(frozen=True)
class ConflictExecutionReport:
    runtime_name: str
    completed_plan: bool
    actions_planned: int
    tool_attempts: int
    retry_count: int
    confirmation_count: int
    conflict_count: int
    conflict_probe_count: int
    conflict_rebase_count: int
    conflict_abort_count: int
    failure_code: str | None
    result_contract_violations: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ConflictAwareRuntime(MultiTaskRuntime):
    """Preserve R2 confirmation while adding one guarded rebase per action."""

    def __init__(self) -> None:
        super().__init__("r2_confirmed")
        self.name = "r2_conflict_aware"
        self.max_conflict_rebases = 1

    @staticmethod
    def _append_conflict_event(
        environment: ConflictWorkspaceEnvironment,
        journal: EventJournal,
        *,
        event_type: str,
        step: ConflictPlanStep,
        actual_value: Any | None = None,
        error_code: str | None = None,
    ) -> None:
        state_hash = environment.state_hash()
        guard = step.guard
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type=event_type,
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            input_digest=digest_value(
                {
                    "tool_name": step.action.tool_name,
                    "guard_tool": guard.tool_name if guard else None,
                    "guard_path": list(guard.value_path) if guard else None,
                    "expected_digest": digest_value(guard.expected_value) if guard else None,
                }
            ),
            output_digest=(
                digest_value({"actual_digest": digest_value(actual_value)})
                if actual_value is not None
                else None
            ),
            tool_name=step.action.tool_name,
            schema_version=step.action.schema_version,
            error_code=error_code,
        )

    def _report(
        self,
        *,
        plan: list[ConflictPlanStep],
        tool_attempts: int,
        retry_count: int,
        confirmation_count: int,
        conflict_count: int,
        conflict_probe_count: int,
        conflict_rebase_count: int,
        conflict_abort_count: int,
        failure_code: str | None,
        contract_violations: int,
    ) -> ConflictExecutionReport:
        return ConflictExecutionReport(
            runtime_name=self.name,
            completed_plan=failure_code is None,
            actions_planned=len(plan),
            tool_attempts=tool_attempts,
            retry_count=retry_count,
            confirmation_count=confirmation_count,
            conflict_count=conflict_count,
            conflict_probe_count=conflict_probe_count,
            conflict_rebase_count=conflict_rebase_count,
            conflict_abort_count=conflict_abort_count,
            failure_code=failure_code,
            result_contract_violations=contract_violations,
        )

    def execute(
        self,
        environment: ConflictWorkspaceEnvironment,
        plan: list[ConflictPlanStep],
        journal: EventJournal,
    ) -> ConflictExecutionReport:
        known_state_version = environment.state_version
        tool_attempts = 0
        retry_count = 0
        confirmation_count = 0
        conflict_count = 0
        conflict_probe_count = 0
        conflict_rebase_count = 0
        conflict_abort_count = 0
        contract_violations = 0

        def report(failure_code: str | None) -> ConflictExecutionReport:
            return self._report(
                plan=plan,
                tool_attempts=tool_attempts,
                retry_count=retry_count,
                confirmation_count=confirmation_count,
                conflict_count=conflict_count,
                conflict_probe_count=conflict_probe_count,
                conflict_rebase_count=conflict_rebase_count,
                conflict_abort_count=conflict_abort_count,
                failure_code=failure_code,
                contract_violations=contract_violations,
            )

        for step in plan:
            retry_attempt = 0
            step_rebases = 0
            while True:
                action = replace(step.action, expected_state_version=known_state_version)
                tool_attempts += 1
                self._append_action_started(environment, journal, action)
                result = environment.step(action)
                self._append_result(environment, journal, action, result)

                if result.ok:
                    if not self._result_contract_valid(environment, action, result):
                        contract_violations += 1
                        return report("result_contract_violation")
                    known_state_version = result.state_version
                    break

                ambiguous_commit = (
                    result.status == "retryable_error"
                    and result.error_code == "tool_timeout_postcommit"
                    and action.idempotency_key is not None
                    and result.state_hash_before != result.state_hash_after
                )
                if ambiguous_commit:
                    confirmation_count += 1
                    tool_attempts += 1
                    confirmed, failure_code = self._confirm(environment, action, journal)
                    if not confirmed:
                        return report(failure_code)
                    known_state_version = environment.state_version
                    break

                state_conflict = (
                    result.status == "conflict" and result.error_code == "state_version_conflict"
                )
                if state_conflict:
                    conflict_count += 1
                    self._append_conflict_event(
                        environment,
                        journal,
                        event_type="state_conflict_detected",
                        step=step,
                        error_code=result.error_code,
                    )
                    if step.guard is None:
                        conflict_abort_count += 1
                        return report("conflict_guard_missing")
                    if step_rebases >= self.max_conflict_rebases:
                        conflict_abort_count += 1
                        return report("conflict_rebase_limit_exceeded")

                    probe = step.guard.read_action(result.state_version)
                    conflict_probe_count += 1
                    tool_attempts += 1
                    self._append_action_started(environment, journal, probe)
                    probe_result = environment.step(probe)
                    self._append_result(environment, journal, probe, probe_result)
                    if not probe_result.ok:
                        conflict_abort_count += 1
                        return report(probe_result.error_code or "conflict_probe_failed")
                    if not self._result_contract_valid(environment, probe, probe_result):
                        contract_violations += 1
                        conflict_abort_count += 1
                        return report("conflict_probe_contract_violation")
                    found, actual_value = step.guard.observed_value(probe_result)
                    if not found:
                        conflict_abort_count += 1
                        return report("conflict_probe_value_missing")
                    if actual_value != step.guard.expected_value:
                        conflict_abort_count += 1
                        self._append_conflict_event(
                            environment,
                            journal,
                            event_type="state_conflict_rejected",
                            step=step,
                            actual_value=actual_value,
                            error_code="conflict_precondition_changed",
                        )
                        return report("conflict_precondition_changed")

                    step_rebases += 1
                    conflict_rebase_count += 1
                    known_state_version = probe_result.state_version
                    self._append_conflict_event(
                        environment,
                        journal,
                        event_type="state_conflict_rebased",
                        step=step,
                        actual_value=actual_value,
                    )
                    continue

                if result.status == "retryable_error" and retry_attempt < self.max_retries:
                    retry_attempt += 1
                    retry_count += 1
                    journal.append(
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

                return report(result.error_code)

        return report(None)
