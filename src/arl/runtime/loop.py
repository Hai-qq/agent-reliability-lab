"""R0/R1 deterministic runtime loop with typed retry handling."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value
from arl.envs.workspace import WorkspaceEnvironment
from arl.runtime.journal import EventJournal


@dataclass(frozen=True)
class ExecutionReport:
    runtime_name: str
    completed_plan: bool
    actions_planned: int
    tool_attempts: int
    retry_count: int
    failure_code: str | None
    result_contract_violations: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GuardedRuntime:
    """Execute a fixed policy plan under R0 or R1 runtime semantics."""

    def __init__(self, name: str) -> None:
        if name not in {"r0_raw", "r1_guarded"}:
            raise ValueError(f"Unknown runtime: {name}")
        self.name = name
        self.max_retries = 0 if name == "r0_raw" else 1
        self.validate_results = name == "r1_guarded"

    def _result_contract_valid(
        self,
        environment: WorkspaceEnvironment,
        action: ToolAction,
        result: StepResult,
    ) -> bool:
        if result.state_hash_after != environment.state_hash():
            return False
        if result.state_version != environment.state_version:
            return False
        if action.tool_name == "calendar.create_event":
            return bool(result.value and isinstance(result.value.get("created_event_id"), str))
        if action.tool_name == "messages.send_invitations":
            return bool(result.value and isinstance(result.value.get("invitation_count"), int))
        return False

    def execute(
        self,
        environment: WorkspaceEnvironment,
        actions: list[ToolAction],
        journal: EventJournal,
    ) -> ExecutionReport:
        tool_attempts = 0
        retry_count = 0
        contract_violations = 0

        for action in actions:
            attempt = 0
            while True:
                attempt += 1
                tool_attempts += 1
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
                result = environment.step(action)
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

                if result.ok:
                    if self.validate_results and not self._result_contract_valid(
                        environment, action, result
                    ):
                        contract_violations += 1
                        return ExecutionReport(
                            runtime_name=self.name,
                            completed_plan=False,
                            actions_planned=len(actions),
                            tool_attempts=tool_attempts,
                            retry_count=retry_count,
                            failure_code="result_contract_violation",
                            result_contract_violations=contract_violations,
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

                return ExecutionReport(
                    runtime_name=self.name,
                    completed_plan=False,
                    actions_planned=len(actions),
                    tool_attempts=tool_attempts,
                    retry_count=retry_count,
                    failure_code=result.error_code,
                    result_contract_violations=contract_violations,
                )

        return ExecutionReport(
            runtime_name=self.name,
            completed_plan=True,
            actions_planned=len(actions),
            tool_attempts=tool_attempts,
            retry_count=retry_count,
            failure_code=None,
            result_contract_violations=contract_violations,
        )
