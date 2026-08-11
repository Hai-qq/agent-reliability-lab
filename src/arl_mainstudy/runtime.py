"""Generic action-at-a-time R0/R1/R2 controller for the main-study harness."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value
from arl.runtime.journal import EventJournal
from arl_mainstudy.contract import RUNTIME_NAMES
from arl_mainstudy.protocol import AgentFeedback, RuntimeEnvironment, RuntimeHooks


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    max_retries: int
    validate_results: bool
    attach_state_version: bool
    attach_idempotency_key: bool
    confirm_ambiguous_commit: bool


PROFILES = {
    "r0_raw": RuntimeProfile(
        name="r0_raw",
        max_retries=0,
        validate_results=False,
        attach_state_version=False,
        attach_idempotency_key=False,
        confirm_ambiguous_commit=False,
    ),
    "r1_guarded": RuntimeProfile(
        name="r1_guarded",
        max_retries=1,
        validate_results=True,
        attach_state_version=True,
        attach_idempotency_key=False,
        confirm_ambiguous_commit=False,
    ),
    "r2_reliable": RuntimeProfile(
        name="r2_reliable",
        max_retries=1,
        validate_results=True,
        attach_state_version=True,
        attach_idempotency_key=True,
        confirm_ambiguous_commit=True,
    ),
}

if tuple(PROFILES) != RUNTIME_NAMES:  # pragma: no cover - import-time contract
    raise RuntimeError("Runtime profile order drifted from the main-study contract")


@dataclass(frozen=True)
class RuntimeActionReport:
    runtime_name: str
    accepted: bool
    tool_attempts: int
    retry_count: int
    confirmation_count: int
    result_contract_violations: int
    failure_code: str | None
    recovery_kind: str | None
    prepared_action_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActionRuntime:
    """Execute one policy-selected action while keeping runtime differences explicit."""

    def __init__(self, name: str, hooks: RuntimeHooks) -> None:
        try:
            self.profile = PROFILES[name]
        except KeyError as error:
            raise ValueError(f"Unknown runtime: {name}") from error
        self.hooks = hooks

    @staticmethod
    def _append_action_started(
        environment: RuntimeEnvironment,
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
        environment: RuntimeEnvironment,
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

    def _prepare_action(
        self,
        environment: RuntimeEnvironment,
        semantic_action: ToolAction,
        *,
        episode_key: str,
        action_ordinal: int,
    ) -> ToolAction:
        if (
            semantic_action.idempotency_key is not None
            or semantic_action.expected_state_version is not None
        ):
            raise ValueError("Agent actions cannot set runtime-owned reliability metadata")
        expected_state_version = (
            environment.state_version if self.profile.attach_state_version else None
        )
        idempotency_key: str | None = None
        if self.profile.attach_idempotency_key and self.hooks.is_write(semantic_action):
            identity = digest_value(
                {
                    "episode_key": episode_key,
                    "action_ordinal": action_ordinal,
                    "tool_name": semantic_action.tool_name,
                    "arguments": semantic_action.arguments,
                }
            )
            idempotency_key = f"arl-main:{identity}"
        return replace(
            semantic_action,
            idempotency_key=idempotency_key,
            expected_state_version=expected_state_version,
        )

    def _confirm(
        self,
        environment: RuntimeEnvironment,
        action: ToolAction,
        journal: EventJournal,
    ) -> tuple[bool, StepResult | None, str | None]:
        confirmation = self.hooks.confirmation_action(action, environment.state_version)
        if confirmation is None:
            return False, None, "confirmation_not_supported"
        state_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="runtime",
            event_type="state_confirmation_started",
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            input_digest=digest_value(
                {"tool_name": action.tool_name, "request_digest": digest_value(action.as_dict())}
            ),
            tool_name=confirmation.tool_name,
            schema_version=confirmation.schema_version,
        )
        self._append_action_started(environment, journal, confirmation)
        result = environment.step(confirmation)
        self._append_result(environment, journal, confirmation, result)
        if not result.ok:
            return False, result, result.error_code or "confirmation_failed"
        if not self.hooks.result_contract_valid(environment, confirmation, result):
            return False, result, "confirmation_contract_violation"
        if not self.hooks.confirmation_matches(action, result):
            return False, result, "state_confirmation_mismatch"
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
        return True, result, None

    def execute(
        self,
        environment: RuntimeEnvironment,
        semantic_action: ToolAction,
        journal: EventJournal,
        *,
        episode_key: str,
        action_ordinal: int,
    ) -> tuple[RuntimeActionReport, AgentFeedback]:
        action = self._prepare_action(
            environment,
            semantic_action,
            episode_key=episode_key,
            action_ordinal=action_ordinal,
        )
        tool_attempts = 0
        retry_count = 0
        confirmation_count = 0
        contract_violations = 0
        attempt = 0

        def report(
            *,
            accepted: bool,
            failure_code: str | None,
            recovery_kind: str | None,
            value: dict[str, Any] | None,
        ) -> tuple[RuntimeActionReport, AgentFeedback]:
            action_report = RuntimeActionReport(
                runtime_name=self.profile.name,
                accepted=accepted,
                tool_attempts=tool_attempts,
                retry_count=retry_count,
                confirmation_count=confirmation_count,
                result_contract_violations=contract_violations,
                failure_code=failure_code,
                recovery_kind=recovery_kind,
                prepared_action_digest=digest_value(action.as_dict()),
            )
            feedback = AgentFeedback(
                accepted=accepted,
                status="ok" if accepted else "error",
                error_code=failure_code,
                recovery_kind=recovery_kind,
                value=value,
            )
            return action_report, feedback

        while True:
            attempt += 1
            tool_attempts += 1
            self._append_action_started(environment, journal, action)
            result = environment.step(action)
            self._append_result(environment, journal, action, result)
            if result.ok:
                if self.profile.validate_results and not self.hooks.result_contract_valid(
                    environment, action, result
                ):
                    contract_violations += 1
                    return report(
                        accepted=False,
                        failure_code="result_contract_violation",
                        recovery_kind=None,
                        value=None,
                    )
                return report(
                    accepted=True,
                    failure_code=None,
                    recovery_kind=None,
                    value=result.value,
                )

            ambiguous_commit = (
                self.profile.confirm_ambiguous_commit
                and result.status == "retryable_error"
                and result.error_code == "tool_timeout_postcommit"
                and action.idempotency_key is not None
                and result.state_hash_before != result.state_hash_after
            )
            if ambiguous_commit:
                confirmation_count += 1
                tool_attempts += 1
                confirmed, confirmation_result, failure_code = self._confirm(
                    environment, action, journal
                )
                if confirmed:
                    return report(
                        accepted=True,
                        failure_code=None,
                        recovery_kind="state_confirmation",
                        value={
                            "commit_confirmed": True,
                            "confirmation_digest": digest_value(
                                confirmation_result.as_dict() if confirmation_result else None
                            ),
                        },
                    )
                return report(
                    accepted=False,
                    failure_code=failure_code,
                    recovery_kind="state_confirmation_failed",
                    value=None,
                )

            if result.status == "retryable_error" and attempt <= self.profile.max_retries:
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

            return report(
                accepted=False,
                failure_code=result.error_code,
                recovery_kind=None,
                value=None,
            )
