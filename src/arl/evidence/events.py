"""Stable logical-call and transport-attempt audit events."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from arl.evidence.schema import SCHEMA_VERSION, validate_provider_event

ProviderEventType = Literal[
    "LogicalCallStarted",
    "TransportAttemptStarted",
    "TransportAttemptFailed",
    "ProviderResponseReceived",
    "ProviderUsageRecorded",
    "ResponseParseFailed",
    "DecisionAccepted",
    "DecisionRejected",
    "LogicalCallFinished",
]


@dataclass(frozen=True)
class ProviderAuditEvent:
    """Normalized provider metadata without absolute timestamps or raw content."""

    event_type: ProviderEventType
    sequence_index: int
    logical_call_id: str
    episode_id: str
    turn_index: int
    request_digest: str
    model_binding: str
    attempt_id: str | None = None
    ordinal: int | None = None
    duration_ms: int | None = None
    status: str | None = None
    error_type: str | None = None
    retry_decision: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: str | None = None
    currency: str | None = None
    accepted: bool | None = None
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict[str, Any]:
        """Return the canonical public event shape."""

        value = asdict(self)
        validate_provider_event(value)
        return value


@dataclass(frozen=True)
class ProviderAuditCounts:
    """Independent counts for policy calls, retries, usage, and decisions."""

    logical_call_count: int
    transport_attempt_count: int
    usage_bearing_response_count: int
    accepted_decision_count: int
    provider_failure_count: int
    parse_failure_count: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


def count_provider_events(events: list[dict[str, Any]]) -> ProviderAuditCounts:
    """Count provider semantics without conflating logical calls and retries."""

    for event in events:
        validate_provider_event(event)
    return ProviderAuditCounts(
        logical_call_count=sum(item["event_type"] == "LogicalCallStarted" for item in events),
        transport_attempt_count=sum(
            item["event_type"] == "TransportAttemptStarted" for item in events
        ),
        usage_bearing_response_count=sum(
            item["event_type"] == "ProviderUsageRecorded" for item in events
        ),
        accepted_decision_count=sum(item["event_type"] == "DecisionAccepted" for item in events),
        provider_failure_count=sum(
            item["event_type"] == "TransportAttemptFailed" for item in events
        ),
        parse_failure_count=sum(item["event_type"] == "ResponseParseFailed" for item in events),
    )


def validate_provider_event_ledger(events: list[dict[str, Any]]) -> None:
    """Validate ordering and one start/finish envelope per logical call."""

    for event in events:
        validate_provider_event(event)
    if [item["sequence_index"] for item in events] != list(range(1, len(events) + 1)):
        raise ValueError("provider event sequence_index must be contiguous from one")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event["logical_call_id"]), []).append(event)
    identity_fields = ("episode_id", "turn_index", "request_digest", "model_binding")
    for logical_call_id, group in grouped.items():
        event_types = [item["event_type"] for item in group]
        if event_types.count("LogicalCallStarted") != 1:
            raise ValueError(f"logical call must have one start: {logical_call_id}")
        if event_types.count("LogicalCallFinished") != 1:
            raise ValueError(f"logical call must have one finish: {logical_call_id}")
        if event_types[0] != "LogicalCallStarted" or event_types[-1] != "LogicalCallFinished":
            raise ValueError(f"logical call envelope order is invalid: {logical_call_id}")
        for field in identity_fields:
            if len({item[field] for item in group}) != 1:
                raise ValueError(f"logical call identity changed for {field}: {logical_call_id}")


def adapt_legacy_provider_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a digest-only legacy record into explicit audit semantics.

    This compatibility adapter never infers a successful call from token usage and
    never invents transport attempts. Missing legacy facts stay absent.
    """

    required = {"episode_id", "request_digest", "model_binding"}
    if not required.issubset(record):
        missing = sorted(required - set(record))
        raise ValueError(f"legacy provider record is missing fields: {missing}")
    logical_call_id = str(record.get("logical_call_id") or f"legacy:{record['episode_id']}:0")
    common = {
        "logical_call_id": logical_call_id,
        "episode_id": str(record["episode_id"]),
        "turn_index": int(record.get("turn_index", 0)),
        "request_digest": str(record["request_digest"]),
        "model_binding": str(record["model_binding"]),
        "attempt_id": None,
        "ordinal": None,
        "duration_ms": None,
        "status": None,
        "error_type": None,
        "retry_decision": None,
        "input_tokens": None,
        "output_tokens": None,
        "cost_usd": None,
        "currency": None,
        "accepted": None,
        "schema_version": SCHEMA_VERSION,
    }
    events: list[dict[str, Any]] = []

    def append(event_type: ProviderEventType, **changes: Any) -> None:
        event = {**common, "event_type": event_type, "sequence_index": len(events) + 1, **changes}
        validate_provider_event(event)
        events.append(event)

    append("LogicalCallStarted")
    if record.get("provider_error"):
        append(
            "TransportAttemptFailed",
            status="failed",
            error_type=str(record["provider_error"]),
            retry_decision="unknown_legacy",
        )
    usage = record.get("usage")
    if isinstance(usage, dict):
        append(
            "ProviderUsageRecorded",
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            cost_usd=(str(record["cost_usd"]) if record.get("cost_usd") is not None else None),
            currency=(
                str(record.get("currency", "USD")) if record.get("cost_usd") is not None else None
            ),
        )
    if record.get("parse_error"):
        append("ResponseParseFailed", error_type=str(record["parse_error"]))
    if record.get("decision_accepted") is True:
        append("DecisionAccepted", accepted=True)
    elif record.get("decision_accepted") is False:
        append("DecisionRejected", accepted=False)
    append("LogicalCallFinished", status=str(record.get("status", "unknown_legacy")))
    return events
