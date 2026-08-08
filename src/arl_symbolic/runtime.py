"""One-shot and revision-aware symbolic-user authorization runtimes."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from arl.core.types import digest_value
from arl.runtime.journal import EventJournal
from arl_symbolic.protocol import (
    AuthorizationResponse,
    AuthorizationToken,
    CommitEvaluation,
    SymbolicUserSession,
)

PolicyName = Literal["one_shot", "revision_aware"]
POLICIES: tuple[PolicyName, ...] = ("one_shot", "revision_aware")


@dataclass(frozen=True)
class SymbolicExecutionReport:
    policy_name: PolicyName
    completed: bool
    user_request_count: int
    clarification_count: int
    authorization_check_count: int
    reauthorization_count: int
    revision_count: int
    commit_attempted: bool
    commit_accepted: bool
    task_success: bool
    safe_success: bool
    unsafe_commit: bool
    safe_abort: bool
    failure_code: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _append_event(
    journal: EventJournal,
    session: SymbolicUserSession,
    event_type: str,
    *,
    before_hash: str,
    input_value: Any = None,
    output_value: Any = None,
    error_code: str | None = None,
) -> None:
    journal.append(
        timestamp_logical=(
            session.request_count + session.clarification_count + session.revision_count
        ),
        actor="symbolic_user" if event_type == "user_response" else "runtime",
        event_type=event_type,
        state_hash_before=before_hash,
        state_hash_after=session.state_hash,
        input_digest=digest_value(input_value) if input_value is not None else None,
        output_digest=digest_value(output_value) if output_value is not None else None,
        error_code=error_code,
    )


def _response_descriptor(response: AuthorizationResponse) -> dict[str, Any]:
    return {
        "status": response.status,
        "revision": response.revision,
        "intent_digest": response.intent_digest,
        "missing_field_count": len(response.missing_fields),
        "missing_fields_digest": digest_value(response.missing_fields),
        "token_digest": response.token.token_digest if response.token else None,
    }


def _request(
    session: SymbolicUserSession,
    journal: EventJournal,
) -> AuthorizationResponse:
    before = session.state_hash
    _append_event(
        journal,
        session,
        "authorization_requested",
        before_hash=before,
        input_value={"known_revision": session.revision},
    )
    response = session.request_authorization()
    _append_event(
        journal,
        session,
        "user_response",
        before_hash=before,
        output_value=_response_descriptor(response),
        error_code=(
            None
            if response.status == "approved"
            else "intent_incomplete"
            if response.status == "needs_clarification"
            else "user_abandoned"
        ),
    )
    return response


def _revise_if_planned(session: SymbolicUserSession, journal: EventJournal) -> None:
    before = session.state_hash
    if session.revise_before_commit():
        _append_event(
            journal,
            session,
            "intent_revised",
            before_hash=before,
            output_value={
                "revision": session.revision,
                "intent_digest": session.intent_digest,
            },
        )


def _append_evaluation(
    journal: EventJournal,
    session: SymbolicUserSession,
    evaluation: CommitEvaluation,
) -> None:
    state_hash = session.state_hash
    _append_event(
        journal,
        session,
        "commit_accepted" if evaluation.accepted else "commit_rejected",
        before_hash=state_hash,
        output_value=evaluation.as_dict(),
        error_code=evaluation.failure_code,
    )
    _append_event(
        journal,
        session,
        "evaluation_completed",
        before_hash=state_hash,
        output_value=evaluation.as_dict(),
    )


def _report(
    policy: PolicyName,
    session: SymbolicUserSession,
    evaluation: CommitEvaluation,
    *,
    authorization_checks: int,
    reauthorizations: int,
    commit_attempted: bool,
) -> SymbolicExecutionReport:
    return SymbolicExecutionReport(
        policy_name=policy,
        completed=evaluation.accepted,
        user_request_count=session.request_count,
        clarification_count=session.clarification_count,
        authorization_check_count=authorization_checks,
        reauthorization_count=reauthorizations,
        revision_count=session.revision_count,
        commit_attempted=commit_attempted,
        commit_accepted=evaluation.accepted,
        task_success=evaluation.task_success,
        safe_success=evaluation.safe_success,
        unsafe_commit=evaluation.unsafe_commit,
        safe_abort=evaluation.safe_abort,
        failure_code=evaluation.failure_code,
    )


class OneShotAuthorizationRuntime:
    """Commit after one response without clarification or token freshness checks."""

    name: PolicyName = "one_shot"

    def execute(
        self,
        session: SymbolicUserSession,
        journal: EventJournal,
    ) -> SymbolicExecutionReport:
        start_hash = session.state_hash
        _append_event(
            journal,
            session,
            "symbolic_session_started",
            before_hash=start_hash,
            input_value={
                "template_id": session.template.template_id,
                "condition": session.condition,
                "policy": self.name,
            },
        )
        response = _request(session, journal)
        token = response.token
        proposed_digest = response.intent_digest
        _revise_if_planned(session, journal)
        evaluation = session.evaluate_commit(
            token=token,
            proposed_intent_digest=proposed_digest,
            attempted=True,
        )
        _append_evaluation(journal, session, evaluation)
        return _report(
            self.name,
            session,
            evaluation,
            authorization_checks=0,
            reauthorizations=0,
            commit_attempted=True,
        )


class RevisionAwareAuthorizationRuntime:
    """Clarify missing intent and fence commits with current authorization tokens."""

    name: PolicyName = "revision_aware"

    def execute(
        self,
        session: SymbolicUserSession,
        journal: EventJournal,
    ) -> SymbolicExecutionReport:
        start_hash = session.state_hash
        _append_event(
            journal,
            session,
            "symbolic_session_started",
            before_hash=start_hash,
            input_value={
                "template_id": session.template.template_id,
                "condition": session.condition,
                "policy": self.name,
            },
        )
        response = _request(session, journal)
        if response.status == "needs_clarification":
            before = session.state_hash
            answered = session.clarify(response.missing_fields)
            _append_event(
                journal,
                session,
                "clarification_answered" if answered else "clarification_abandoned",
                before_hash=before,
                input_value={
                    "missing_field_count": len(response.missing_fields),
                    "missing_fields_digest": digest_value(response.missing_fields),
                },
                error_code=None if answered else "user_abandoned",
            )
            response = _request(session, journal)

        token: AuthorizationToken | None = response.token
        proposed_digest: str | None = response.intent_digest if token else None
        _revise_if_planned(session, journal)
        authorization_checks = 0
        reauthorizations = 0
        if token is not None:
            authorization_checks += 1
            status = session.authorization_status(token)
            state_hash = session.state_hash
            _append_event(
                journal,
                session,
                "authorization_checked",
                before_hash=state_hash,
                input_value={"token_digest": token.token_digest},
                output_value={"status": status, "revision": session.revision},
                error_code=None if status == "current" else "stale_authorization",
            )
            if status != "current":
                reauthorizations += 1
                response = _request(session, journal)
                token = response.token
                proposed_digest = response.intent_digest if token else None
                if token is not None:
                    authorization_checks += 1
                    status = session.authorization_status(token)
                    state_hash = session.state_hash
                    _append_event(
                        journal,
                        session,
                        "authorization_checked",
                        before_hash=state_hash,
                        input_value={"token_digest": token.token_digest},
                        output_value={"status": status, "revision": session.revision},
                        error_code=None if status == "current" else "stale_authorization",
                    )
                    if status != "current":  # pragma: no cover - deterministic user is stable
                        token = None
                        proposed_digest = None

        commit_attempted = token is not None
        evaluation = session.evaluate_commit(
            token=token,
            proposed_intent_digest=proposed_digest,
            attempted=commit_attempted,
        )
        _append_evaluation(journal, session, evaluation)
        return _report(
            self.name,
            session,
            evaluation,
            authorization_checks=authorization_checks,
            reauthorizations=reauthorizations,
            commit_attempted=commit_attempted,
        )
