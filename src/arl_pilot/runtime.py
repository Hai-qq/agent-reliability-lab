"""Unified R0/R1/R2 runtime with all six pilot fault mechanisms."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value
from arl.runtime.journal import EventJournal
from arl_mainstudy.contract import RUNTIME_NAMES
from arl_mainstudy.protocol import AgentFeedback
from arl_pilot.env import PilotEnvironment


@dataclass(frozen=True)
class PilotRuntimeProfile:
    name: str
    validate_results: bool
    max_retries: int
    attach_state_version: bool
    reliable_mechanisms: bool


PROFILES = {
    "r0_raw": PilotRuntimeProfile(
        name="r0_raw",
        validate_results=False,
        max_retries=0,
        attach_state_version=False,
        reliable_mechanisms=False,
    ),
    "r1_guarded": PilotRuntimeProfile(
        name="r1_guarded",
        validate_results=True,
        max_retries=1,
        attach_state_version=True,
        reliable_mechanisms=False,
    ),
    "r2_reliable": PilotRuntimeProfile(
        name="r2_reliable",
        validate_results=True,
        max_retries=1,
        attach_state_version=True,
        reliable_mechanisms=True,
    ),
}

if tuple(PROFILES) != RUNTIME_NAMES:  # pragma: no cover - import-time contract
    raise RuntimeError("Pilot runtime order drifted from the main-study contract")


@dataclass(frozen=True)
class PilotActionReport:
    runtime_name: str
    accepted: bool
    tool_attempts: int
    retry_count: int
    confirmation_count: int
    schema_adaptation_count: int
    result_normalization_count: int
    conflict_rebase_count: int
    compensation_action_count: int
    result_contract_violation_count: int
    failure_code: str | None
    recovery_kind: str | None
    prepared_action_digest: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class PilotRuntime:
    """Apply runtime-owned reliability behavior to one policy-selected action."""

    def __init__(self, name: str) -> None:
        try:
            self.profile = PROFILES[name]
        except KeyError as error:
            raise ValueError(f"Unknown runtime: {name}") from error

    @staticmethod
    def _append_action_started(
        environment: PilotEnvironment,
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
        environment: PilotEnvironment,
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

    def _dispatch(
        self,
        environment: PilotEnvironment,
        journal: EventJournal,
        action: ToolAction,
    ) -> StepResult:
        self._append_action_started(environment, journal, action)
        result = environment.step(action)
        self._append_result(environment, journal, action, result)
        return result

    def _idempotency_key(
        self,
        semantic_action: ToolAction,
        *,
        episode_key: str,
        action_ordinal: int,
    ) -> str:
        return "arl-pilot:" + digest_value(
            {
                "episode_key": episode_key,
                "action_ordinal": action_ordinal,
                "tool_name": semantic_action.tool_name,
                "arguments": semantic_action.arguments,
            }
        )

    def _prepare_action(
        self,
        environment: PilotEnvironment,
        semantic_action: ToolAction,
        journal: EventJournal,
        *,
        episode_key: str,
        action_ordinal: int,
    ) -> tuple[ToolAction, bool]:
        if (
            semantic_action.idempotency_key is not None
            or semantic_action.expected_state_version is not None
        ):
            raise ValueError("Policies cannot set runtime-owned reliability metadata")
        dispatched = semantic_action
        adapted = False
        if self.profile.reliable_mechanisms:
            try:
                dispatched = environment.adapt_input_action(semantic_action)
            except ValueError as error:
                raise RuntimeError("schema_adapter_error") from error
            adapted = dispatched != semantic_action
            if adapted:
                state_hash = environment.state_hash()
                journal.append(
                    timestamp_logical=environment.logical_time,
                    actor="runtime",
                    event_type="schema_adapter_applied",
                    state_hash_before=state_hash,
                    state_hash_after=state_hash,
                    input_digest=digest_value(semantic_action.as_dict()),
                    output_digest=digest_value(dispatched.as_dict()),
                    tool_name=semantic_action.tool_name,
                    schema_version=dispatched.schema_version,
                )
        expected_state_version = (
            environment.state_version if self.profile.attach_state_version else None
        )
        idempotency_key = None
        if self.profile.reliable_mechanisms and environment.is_write(semantic_action):
            idempotency_key = self._idempotency_key(
                semantic_action,
                episode_key=episode_key,
                action_ordinal=action_ordinal,
            )
        return (
            replace(
                dispatched,
                idempotency_key=idempotency_key,
                expected_state_version=expected_state_version,
            ),
            adapted,
        )

    def execute(
        self,
        environment: PilotEnvironment,
        semantic_action: ToolAction,
        journal: EventJournal,
        *,
        episode_key: str,
        action_ordinal: int,
    ) -> tuple[PilotActionReport, AgentFeedback]:
        try:
            action, input_adapted = self._prepare_action(
                environment,
                semantic_action,
                journal,
                episode_key=episode_key,
                action_ordinal=action_ordinal,
            )
        except RuntimeError as error:
            if str(error) != "schema_adapter_error":
                raise
            action = semantic_action
            input_adapted = False
            preparation_failure = "schema_adapter_error"
        else:
            preparation_failure = None

        tool_attempts = 0
        retry_count = 0
        confirmation_count = 0
        schema_adaptation_count = int(input_adapted)
        result_normalization_count = 0
        conflict_rebase_count = 0
        compensation_action_count = 0
        result_contract_violation_count = 0

        def report(
            *,
            accepted: bool,
            failure_code: str | None,
            recovery_kind: str | None,
            value: dict[str, Any] | None,
        ) -> tuple[PilotActionReport, AgentFeedback]:
            action_report = PilotActionReport(
                runtime_name=self.profile.name,
                accepted=accepted,
                tool_attempts=tool_attempts,
                retry_count=retry_count,
                confirmation_count=confirmation_count,
                schema_adaptation_count=schema_adaptation_count,
                result_normalization_count=result_normalization_count,
                conflict_rebase_count=conflict_rebase_count,
                compensation_action_count=compensation_action_count,
                result_contract_violation_count=result_contract_violation_count,
                failure_code=failure_code,
                recovery_kind=recovery_kind,
                prepared_action_digest=digest_value(action.as_dict()),
            )
            return action_report, AgentFeedback(
                accepted=accepted,
                status="ok" if accepted else "error",
                error_code=failure_code,
                recovery_kind=recovery_kind,
                value=value,
            )

        if preparation_failure is not None:
            return report(
                accepted=False,
                failure_code=preparation_failure,
                recovery_kind=None,
                value=None,
            )

        attempt = 0
        while True:
            attempt += 1
            tool_attempts += 1
            result = self._dispatch(environment, journal, action)
            if result.ok:
                normalized = result
                if self.profile.reliable_mechanisms:
                    try:
                        normalized = environment.normalize_result(semantic_action, result)
                    except ValueError:
                        return report(
                            accepted=False,
                            failure_code="result_schema_normalization_error",
                            recovery_kind=None,
                            value=None,
                        )
                    if normalized != result:
                        result_normalization_count += 1
                        state_hash = environment.state_hash()
                        journal.append(
                            timestamp_logical=environment.logical_time,
                            actor="runtime",
                            event_type="result_schema_normalized",
                            state_hash_before=state_hash,
                            state_hash_after=state_hash,
                            input_digest=digest_value(result.as_dict()),
                            output_digest=digest_value(normalized.as_dict()),
                            tool_name=semantic_action.tool_name,
                            schema_version=semantic_action.schema_version,
                        )
                if self.profile.validate_results and not environment.result_contract_valid(
                    semantic_action, normalized
                ):
                    result_contract_violation_count += 1
                    return report(
                        accepted=False,
                        failure_code="result_contract_violation",
                        recovery_kind=None,
                        value=None,
                    )
                return report(
                    accepted=True,
                    failure_code=None,
                    recovery_kind=("schema_adapter" if input_adapted else None),
                    value=normalized.value,
                )

            ambiguous_commit = (
                self.profile.reliable_mechanisms
                and result.status == "retryable_error"
                and result.error_code == "tool_timeout_postcommit"
                and action.idempotency_key is not None
            )
            if ambiguous_commit:
                confirmation = environment.confirmation_action(semantic_action)
                if confirmation is None:
                    return report(
                        accepted=False,
                        failure_code="confirmation_not_supported",
                        recovery_kind="state_confirmation_failed",
                        value=None,
                    )
                confirmation_count += 1
                tool_attempts += 1
                state_hash = environment.state_hash()
                journal.append(
                    timestamp_logical=environment.logical_time,
                    actor="runtime",
                    event_type="state_confirmation_started",
                    state_hash_before=state_hash,
                    state_hash_after=state_hash,
                    input_digest=digest_value(semantic_action.as_dict()),
                    tool_name=confirmation.tool_name,
                    schema_version=confirmation.schema_version,
                )
                confirmation_result = self._dispatch(environment, journal, confirmation)
                if not environment.result_contract_valid(confirmation, confirmation_result):
                    return report(
                        accepted=False,
                        failure_code="confirmation_contract_violation",
                        recovery_kind="state_confirmation_failed",
                        value=None,
                    )
                if not environment.confirmation_matches(semantic_action, confirmation_result):
                    return report(
                        accepted=False,
                        failure_code="state_confirmation_mismatch",
                        recovery_kind="state_confirmation_failed",
                        value=None,
                    )
                confirmed_hash = environment.state_hash()
                journal.append(
                    timestamp_logical=environment.logical_time,
                    actor="runtime",
                    event_type="state_confirmation_succeeded",
                    state_hash_before=confirmed_hash,
                    state_hash_after=confirmed_hash,
                    input_digest=digest_value(semantic_action.as_dict()),
                    output_digest=digest_value(confirmation_result.as_dict()),
                    tool_name=semantic_action.tool_name,
                    schema_version=semantic_action.schema_version,
                )
                return report(
                    accepted=True,
                    failure_code=None,
                    recovery_kind="state_confirmation",
                    value={"commit_confirmed": True},
                )

            if (
                self.profile.reliable_mechanisms
                and result.status == "conflict"
                and result.error_code == "state_version_conflict"
            ):
                probe = environment.conflict_probe_action()
                if probe is not None:
                    tool_attempts += 1
                    probe_result = self._dispatch(environment, journal, probe)
                    if not environment.result_contract_valid(probe, probe_result):
                        return report(
                            accepted=False,
                            failure_code="conflict_probe_contract_violation",
                            recovery_kind="conflict_rebase_failed",
                            value=None,
                        )
                    if not environment.conflict_guard_matches(probe_result):
                        return report(
                            accepted=False,
                            failure_code="conflict_precondition_changed",
                            recovery_kind="conflict_rebase_failed",
                            value=None,
                        )
                    conflict_rebase_count += 1
                    action = replace(action, expected_state_version=environment.state_version)
                    state_hash = environment.state_hash()
                    journal.append(
                        timestamp_logical=environment.logical_time,
                        actor="runtime",
                        event_type="state_conflict_rebased",
                        state_hash_before=state_hash,
                        state_hash_after=state_hash,
                        input_digest=digest_value(semantic_action.as_dict()),
                        output_digest=digest_value(probe_result.as_dict()),
                        tool_name=semantic_action.tool_name,
                        schema_version=semantic_action.schema_version,
                    )
                    continue

            if (
                self.profile.reliable_mechanisms
                and result.error_code == "preferred_option_unavailable"
            ):
                recovery_actions = environment.compensation_actions(semantic_action)
                if recovery_actions:
                    state_hash = environment.state_hash()
                    journal.append(
                        timestamp_logical=environment.logical_time,
                        actor="runtime",
                        event_type="compensation_workflow_started",
                        state_hash_before=state_hash,
                        state_hash_after=state_hash,
                        input_digest=digest_value([item.as_dict() for item in recovery_actions]),
                        tool_name=semantic_action.tool_name,
                        schema_version=semantic_action.schema_version,
                        error_code=result.error_code,
                    )
                    for index, recovery_semantic in enumerate(recovery_actions, start=1):
                        recovery_action, _ = self._prepare_action(
                            environment,
                            recovery_semantic,
                            journal,
                            episode_key=episode_key,
                            action_ordinal=10_000 + action_ordinal * 100 + index,
                        )
                        tool_attempts += 1
                        recovery_result = self._dispatch(environment, journal, recovery_action)
                        if not environment.result_contract_valid(
                            recovery_semantic, recovery_result
                        ):
                            failed_hash = environment.state_hash()
                            journal.append(
                                timestamp_logical=environment.logical_time,
                                actor="runtime",
                                event_type="compensation_workflow_failed",
                                state_hash_before=failed_hash,
                                state_hash_after=failed_hash,
                                input_digest=digest_value(recovery_semantic.as_dict()),
                                output_digest=digest_value(recovery_result.as_dict()),
                                tool_name=recovery_semantic.tool_name,
                                schema_version=recovery_semantic.schema_version,
                                error_code=(
                                    recovery_result.error_code
                                    or "compensation_result_contract_violation"
                                ),
                            )
                            return report(
                                accepted=False,
                                failure_code=(
                                    recovery_result.error_code
                                    or "compensation_result_contract_violation"
                                ),
                                recovery_kind="bounded_compensation_failed",
                                value=None,
                            )
                        compensation_action_count += 1
                    recovered_hash = environment.state_hash()
                    journal.append(
                        timestamp_logical=environment.logical_time,
                        actor="runtime",
                        event_type="compensation_workflow_succeeded",
                        state_hash_before=recovered_hash,
                        state_hash_after=recovered_hash,
                        input_digest=digest_value(semantic_action.as_dict()),
                        output_digest=digest_value(
                            {"completed_actions": compensation_action_count}
                        ),
                        tool_name=semantic_action.tool_name,
                        schema_version=semantic_action.schema_version,
                    )
                    return report(
                        accepted=True,
                        failure_code=None,
                        recovery_kind="bounded_compensation",
                        value={"completed_actions": compensation_action_count},
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
                    tool_name=semantic_action.tool_name,
                    schema_version=semantic_action.schema_version,
                    error_code=result.error_code,
                )
                continue

            return report(
                accepted=False,
                failure_code=result.error_code,
                recovery_kind=None,
                value=None,
            )
