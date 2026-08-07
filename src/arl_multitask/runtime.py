"""Generalized R1/R2 runtime for both Workspace v0.3 tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value
from arl.envs.workspace import SCHEMA_VERSION
from arl.runtime.journal import EventJournal
from arl_multitask.env import MultiTaskWorkspaceEnvironment


@dataclass(frozen=True)
class MultiTaskExecutionReport:
    runtime_name: str
    completed_plan: bool
    actions_planned: int
    tool_attempts: int
    retry_count: int
    confirmation_count: int
    failure_code: str | None
    result_contract_violations: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class MultiTaskRuntime:
    """Run R1 blind-retry or R2 confirm-before-retry semantics."""

    def __init__(self, name: str) -> None:
        if name not in {"r1_guarded", "r2_confirmed"}:
            raise ValueError(f"Unknown runtime: {name}")
        self.name = name
        self.max_retries = 1
        self.confirm_ambiguous_commits = name == "r2_confirmed"

    @staticmethod
    def _result_contract_valid(
        environment: MultiTaskWorkspaceEnvironment,
        action: ToolAction,
        result: StepResult,
    ) -> bool:
        if result.state_hash_after != environment.state_hash():
            return False
        if result.state_version != environment.state_version:
            return False
        if action.tool_name == "calendar.create_event":
            return bool(
                result.value
                and result.value.get("created_event_id") == action.arguments.get("event_id")
            )
        if action.tool_name == "calendar.get_event":
            return bool(result.value and isinstance(result.value.get("event"), dict))
        if action.tool_name == "calendar.update_event_time":
            return bool(
                result.value
                and result.value.get("updated_event_id") == action.arguments.get("event_id")
                and result.value.get("new_start_at") == action.arguments.get("new_start_at")
            )
        if action.tool_name == "messages.send_invitations":
            return bool(
                result.value
                and result.value.get("invitation_count") == len(action.arguments["recipients"])
            )
        if action.tool_name == "messages.send_reschedule_notifications":
            return bool(
                result.value
                and result.value.get("notification_count") == len(action.arguments["recipients"])
            )
        if action.tool_name == "messages.get_reschedule_notifications":
            return bool(result.value and isinstance(result.value.get("notifications"), list))
        if action.tool_name == "workspace.resolve_change_request":
            return bool(
                result.value
                and result.value.get("resolved_request_id") == action.arguments.get("request_id")
            )
        return False

    @staticmethod
    def _append_action_started(
        environment: MultiTaskWorkspaceEnvironment,
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
        environment: MultiTaskWorkspaceEnvironment,
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
        if action.tool_name == "calendar.create_event":
            return ToolAction(
                tool_name="calendar.get_event",
                schema_version=SCHEMA_VERSION,
                arguments={"event_id": action.arguments["event_id"]},
                expected_state_version=state_version,
            )
        if action.tool_name == "messages.send_reschedule_notifications":
            return ToolAction(
                tool_name="messages.get_reschedule_notifications",
                schema_version=SCHEMA_VERSION,
                arguments={"event_id": action.arguments["event_id"]},
                expected_state_version=state_version,
            )
        return None

    @staticmethod
    def _confirmation_matches(
        original: ToolAction,
        confirmation_result: StepResult,
    ) -> bool:
        if confirmation_result.value is None:
            return False
        if original.tool_name == "calendar.create_event":
            expected = {
                "event_id": original.arguments["event_id"],
                "title": original.arguments["title"],
                "start_at": original.arguments["start_at"],
                "organizer": original.arguments["organizer"],
                "participants": original.arguments["participants"],
            }
            return confirmation_result.value.get("event") == expected
        if original.tool_name == "messages.send_reschedule_notifications":
            actual = {
                (
                    notification["event_id"],
                    notification["recipient"],
                    notification["kind"],
                    notification["target_start_at"],
                )
                for notification in confirmation_result.value.get("notifications", [])
            }
            expected = {
                (
                    original.arguments["event_id"],
                    recipient,
                    "reschedule",
                    original.arguments["target_start_at"],
                )
                for recipient in original.arguments["recipients"]
            }
            return actual == expected
        return False

    def _confirm(
        self,
        environment: MultiTaskWorkspaceEnvironment,
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

    def _report(
        self,
        *,
        actions: list[ToolAction],
        tool_attempts: int,
        retry_count: int,
        confirmation_count: int,
        failure_code: str | None,
        contract_violations: int,
    ) -> MultiTaskExecutionReport:
        return MultiTaskExecutionReport(
            runtime_name=self.name,
            completed_plan=failure_code is None,
            actions_planned=len(actions),
            tool_attempts=tool_attempts,
            retry_count=retry_count,
            confirmation_count=confirmation_count,
            failure_code=failure_code,
            result_contract_violations=contract_violations,
        )

    def execute(
        self,
        environment: MultiTaskWorkspaceEnvironment,
        actions: list[ToolAction],
        journal: EventJournal,
    ) -> MultiTaskExecutionReport:
        tool_attempts = 0
        retry_count = 0
        confirmation_count = 0
        contract_violations = 0

        for action in actions:
            attempt = 0
            while True:
                attempt += 1
                tool_attempts += 1
                self._append_action_started(environment, journal, action)
                result = environment.step(action)
                self._append_result(environment, journal, action, result)
                if result.ok:
                    if not self._result_contract_valid(environment, action, result):
                        contract_violations += 1
                        return self._report(
                            actions=actions,
                            tool_attempts=tool_attempts,
                            retry_count=retry_count,
                            confirmation_count=confirmation_count,
                            failure_code="result_contract_violation",
                            contract_violations=contract_violations,
                        )
                    break

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
                    if not confirmed:
                        return self._report(
                            actions=actions,
                            tool_attempts=tool_attempts,
                            retry_count=retry_count,
                            confirmation_count=confirmation_count,
                            failure_code=failure_code,
                            contract_violations=contract_violations,
                        )
                    break

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

                return self._report(
                    actions=actions,
                    tool_attempts=tool_attempts,
                    retry_count=retry_count,
                    confirmation_count=confirmation_count,
                    failure_code=result.error_code,
                    contract_violations=contract_violations,
                )

        return self._report(
            actions=actions,
            tool_attempts=tool_attempts,
            retry_count=retry_count,
            confirmation_count=confirmation_count,
            failure_code=None,
            contract_violations=contract_violations,
        )
