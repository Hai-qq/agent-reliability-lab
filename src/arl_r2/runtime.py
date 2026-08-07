"""R2 runtime with bounded retry, idempotency, and state confirmation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value
from arl.envs.workspace import SCHEMA_VERSION
from arl.runtime.journal import EventJournal
from arl_r2.env import ReliableWorkspaceEnvironment


@dataclass(frozen=True)
class ReliableExecutionReport:
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


class ReliableRuntime:
    """Execute an R2 plan and confirm ambiguous post-commit outcomes by state."""

    name = "r2_confirmed"
    max_retries = 1

    @staticmethod
    def _result_contract_valid(
        environment: ReliableWorkspaceEnvironment,
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
        if action.tool_name == "messages.send_invitations":
            return bool(
                result.value
                and result.value.get("invitation_count") == len(action.arguments["recipients"])
            )
        if action.tool_name == "calendar.get_event":
            return bool(result.value and isinstance(result.value.get("event"), dict))
        return False

    @staticmethod
    def _append_result(
        environment: ReliableWorkspaceEnvironment,
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
    def _append_action_started(
        environment: ReliableWorkspaceEnvironment,
        journal: EventJournal,
        action: ToolAction,
    ) -> None:
        before_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="action_started",
            state_hash_before=before_hash,
            state_hash_after=before_hash,
            input_digest=digest_value(action.as_dict()),
            tool_name=action.tool_name,
            schema_version=action.schema_version,
        )

    def _confirm_event(
        self,
        environment: ReliableWorkspaceEnvironment,
        action: ToolAction,
        journal: EventJournal,
    ) -> tuple[bool, str | None]:
        current_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="state_confirmation_started",
            state_hash_before=current_hash,
            state_hash_after=current_hash,
            input_digest=digest_value(
                {
                    "tool_name": action.tool_name,
                    "request_digest": digest_value(action.as_dict()),
                }
            ),
            tool_name="calendar.get_event",
            schema_version=SCHEMA_VERSION,
        )
        confirmation = ToolAction(
            tool_name="calendar.get_event",
            schema_version=SCHEMA_VERSION,
            arguments={"event_id": action.arguments["event_id"]},
            expected_state_version=environment.state_version,
        )
        self._append_action_started(environment, journal, confirmation)
        result = environment.step(confirmation)
        self._append_result(environment, journal, confirmation, result)
        if not result.ok or not self._result_contract_valid(environment, confirmation, result):
            return False, result.error_code or "confirmation_contract_violation"
        expected_event = {
            "event_id": action.arguments["event_id"],
            "title": action.arguments["title"],
            "start_at": action.arguments["start_at"],
            "organizer": action.arguments["organizer"],
            "participants": action.arguments["participants"],
        }
        if result.value is None or result.value["event"] != expected_event:
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
    ) -> ReliableExecutionReport:
        return ReliableExecutionReport(
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
        environment: ReliableWorkspaceEnvironment,
        actions: list[ToolAction],
        journal: EventJournal,
    ) -> ReliableExecutionReport:
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

                is_ambiguous_commit = (
                    result.status == "retryable_error"
                    and result.error_code == "tool_timeout_postcommit"
                    and action.tool_name == "calendar.create_event"
                    and action.idempotency_key is not None
                    and result.state_hash_before != result.state_hash_after
                )
                if is_ambiguous_commit:
                    confirmation_count += 1
                    tool_attempts += 1
                    confirmed, failure_code = self._confirm_event(
                        environment,
                        action,
                        journal,
                    )
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
