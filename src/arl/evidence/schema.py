"""Strict, dependency-free validation for the ``arl-evidence-v1`` contract.

The JSON Schema documents are published for interoperability. Runtime validation
is intentionally implemented with the Python standard library so the core package
does not acquire a third-party dependency.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, cast

SCHEMA_VERSION = "arl-evidence-v1"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")

EPISODE_FIELDS = frozenset(
    {
        "schema_version",
        "episode_id",
        "study_id",
        "task_template_id",
        "task_version",
        "domain",
        "fault_family",
        "environment_seed",
        "sampling_trial",
        "runtime",
        "condition",
        "model_binding",
        "provider_binding",
        "execution_order_index",
        "schedule_block_id",
        "request_digest",
        "policy_digest",
        "source_manifest_digest",
        "initial_state_digest",
        "final_state_digest",
        "initial_public_state",
        "final_public_state",
        "public_state_diff",
        "semantic_decisions",
        "tool_calls",
        "tool_results",
        "fault_injection_events",
        "runtime_recovery_events",
        "evaluator_clause_definitions",
        "evaluator_clause_outcomes",
        "task_success",
        "safe_success",
        "severe_side_effect_count",
        "terminal_reason",
        "logical_provider_call_ids",
        "trace_digest",
    }
)

PROVIDER_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_type",
        "sequence_index",
        "logical_call_id",
        "episode_id",
        "turn_index",
        "request_digest",
        "model_binding",
        "attempt_id",
        "ordinal",
        "duration_ms",
        "status",
        "error_type",
        "retry_decision",
        "input_tokens",
        "output_tokens",
        "cost_usd",
        "currency",
        "accepted",
    }
)

STUDY_FIELDS = frozenset(
    {
        "schema_version",
        "study_id",
        "study_contract_version",
        "task_catalog_version",
        "source_commit",
        "analysis_mode",
        "schedule_seed",
        "schedule_digest",
        "task_catalog_digest",
        "source_manifest_digest",
        "expected_episode_count",
        "expected_provider_event_count",
        "expected_cells",
        "runtime_order",
        "condition_order",
        "model_bindings",
        "provider_bindings",
        "execution_order",
        "public_data_only",
        "synthetic_only",
        "provider_calls_permitted",
    }
)

ANALYSIS_FIELDS = frozenset(
    {
        "schema_version",
        "study_id",
        "analysis_status",
        "episode_ledger_digest",
        "aggregate_digest",
        "estimands",
        "limitations",
    }
)

MANIFEST_FIELDS = frozenset(
    {
        "schema_version",
        "bundle_version",
        "study_id",
        "files",
        "episode_count",
        "provider_event_count",
        "study_digest",
        "episode_ledger_digest",
        "provider_event_ledger_digest",
        "aggregate_digest",
        "analysis_digest",
        "redaction_policy_digest",
        "source_manifest_digest",
        "schedule_digest",
        "task_catalog_digest",
    }
)


class SchemaValidationError(ValueError):
    """Raised when public evidence fails a strict contract check."""


def _require_exact_fields(value: Mapping[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise SchemaValidationError(f"{label} fields invalid; missing={missing}, unknown={unknown}")


def _require_string(value: Mapping[str, Any], key: str, *, allow_empty: bool = False) -> str:
    item = value[key]
    if not isinstance(item, str) or (not allow_empty and not item):
        raise SchemaValidationError(f"{key} must be a non-empty string")
    return item


def _require_int(value: Mapping[str, Any], key: str, *, minimum: int = 0) -> int:
    item = value[key]
    if isinstance(item, bool) or not isinstance(item, int) or item < minimum:
        raise SchemaValidationError(f"{key} must be an integer >= {minimum}")
    return cast(int, item)


def _require_bool(value: Mapping[str, Any], key: str) -> bool:
    item = value[key]
    if not isinstance(item, bool):
        raise SchemaValidationError(f"{key} must be boolean")
    return item


def _require_digest(value: Mapping[str, Any], key: str) -> str:
    item = _require_string(value, key)
    if not SHA256_PATTERN.fullmatch(item):
        raise SchemaValidationError(f"{key} must be a lowercase SHA-256 digest")
    return item


def _require_list(value: Mapping[str, Any], key: str) -> list[Any]:
    item = value[key]
    if not isinstance(item, list):
        raise SchemaValidationError(f"{key} must be an array")
    return item


def _require_object(value: Mapping[str, Any], key: str) -> dict[str, Any]:
    item = value[key]
    if not isinstance(item, dict) or not all(isinstance(name, str) for name in item):
        raise SchemaValidationError(f"{key} must be an object with string keys")
    return item


def validate_episode(value: Mapping[str, Any]) -> None:
    """Validate a single public episode and reject all unknown fields."""

    _require_exact_fields(value, EPISODE_FIELDS, "episode")
    if value["schema_version"] != SCHEMA_VERSION:
        raise SchemaValidationError("episode schema_version mismatch")
    for key in (
        "episode_id",
        "study_id",
        "task_template_id",
        "task_version",
        "domain",
        "fault_family",
        "runtime",
        "condition",
        "model_binding",
        "provider_binding",
        "schedule_block_id",
        "terminal_reason",
    ):
        _require_string(value, key)
    for key in (
        "request_digest",
        "policy_digest",
        "source_manifest_digest",
        "initial_state_digest",
        "final_state_digest",
        "trace_digest",
    ):
        _require_digest(value, key)
    for key in ("environment_seed", "sampling_trial", "execution_order_index"):
        _require_int(value, key)
    _require_int(value, "severe_side_effect_count")
    _require_bool(value, "task_success")
    _require_bool(value, "safe_success")
    for key in ("initial_public_state", "final_public_state", "public_state_diff"):
        _require_object(value, key)
    for key in (
        "semantic_decisions",
        "tool_calls",
        "tool_results",
        "fault_injection_events",
        "runtime_recovery_events",
        "evaluator_clause_definitions",
        "evaluator_clause_outcomes",
        "logical_provider_call_ids",
    ):
        _require_list(value, key)
    if not all(isinstance(item, str) and item for item in value["logical_provider_call_ids"]):
        raise SchemaValidationError("logical_provider_call_ids must contain non-empty strings")


def validate_provider_event(value: Mapping[str, Any]) -> None:
    """Validate one normalized provider audit event."""

    _require_exact_fields(value, PROVIDER_EVENT_FIELDS, "provider event")
    if value["schema_version"] != SCHEMA_VERSION:
        raise SchemaValidationError("provider event schema_version mismatch")
    allowed_types = {
        "LogicalCallStarted",
        "TransportAttemptStarted",
        "TransportAttemptFailed",
        "ProviderResponseReceived",
        "ProviderUsageRecorded",
        "ResponseParseFailed",
        "DecisionAccepted",
        "DecisionRejected",
        "LogicalCallFinished",
    }
    event_type = _require_string(value, "event_type")
    if event_type not in allowed_types:
        raise SchemaValidationError("provider event_type is unknown")
    _require_int(value, "sequence_index", minimum=1)
    _require_string(value, "logical_call_id")
    _require_string(value, "episode_id")
    _require_int(value, "turn_index")
    _require_digest(value, "request_digest")
    _require_string(value, "model_binding")
    nullable_strings = ("attempt_id", "status", "error_type", "retry_decision")
    for key in nullable_strings:
        if value[key] is not None and not isinstance(value[key], str):
            raise SchemaValidationError(f"{key} must be string or null")
    for key in ("ordinal", "duration_ms", "input_tokens", "output_tokens"):
        if value[key] is not None:
            _require_int(value, key, minimum=0 if key != "ordinal" else 1)
    if value["accepted"] is not None and not isinstance(value["accepted"], bool):
        raise SchemaValidationError("accepted must be boolean or null")
    if (value["cost_usd"] is None) != (value["currency"] is None):
        raise SchemaValidationError("cost_usd and currency must be materialized together")
    if value["cost_usd"] is not None:
        if (
            not isinstance(value["cost_usd"], str)
            or not DECIMAL_PATTERN.fullmatch(value["cost_usd"])
            or value["currency"] != "USD"
        ):
            raise SchemaValidationError("cost must be a decimal string denominated in USD")
        try:
            cost = Decimal(value["cost_usd"])
        except InvalidOperation as error:
            raise SchemaValidationError("cost_usd must be a decimal string") from error
        if not cost.is_finite() or cost < 0:
            raise SchemaValidationError("cost_usd must be finite and non-negative")
    usage_fields = ("input_tokens", "output_tokens", "cost_usd", "currency")
    if event_type == "ProviderUsageRecorded":
        if value["input_tokens"] is None or value["output_tokens"] is None:
            raise SchemaValidationError("provider usage event requires input/output tokens")
    elif any(value[key] is not None for key in usage_fields):
        raise SchemaValidationError("usage fields are allowed only on ProviderUsageRecorded")
    if event_type == "DecisionAccepted" and value["accepted"] is not True:
        raise SchemaValidationError("DecisionAccepted requires accepted=true")
    if event_type == "DecisionRejected" and value["accepted"] is not False:
        raise SchemaValidationError("DecisionRejected requires accepted=false")
    if event_type not in {"DecisionAccepted", "DecisionRejected"} and value["accepted"] is not None:
        raise SchemaValidationError("accepted is allowed only on decision events")
    if event_type in {"ResponseParseFailed", "TransportAttemptFailed"} and not value["error_type"]:
        raise SchemaValidationError(f"{event_type} requires error_type")
    if event_type == "LogicalCallFinished" and not value["status"]:
        raise SchemaValidationError("LogicalCallFinished requires status")
    legacy_transport = value["retry_decision"] == "unknown_legacy"
    if (
        event_type
        in {
            "TransportAttemptStarted",
            "TransportAttemptFailed",
            "ProviderResponseReceived",
        }
        and not legacy_transport
    ):
        if value["attempt_id"] is None or value["ordinal"] is None:
            raise SchemaValidationError(f"{event_type} requires attempt_id and ordinal")
        if event_type != "TransportAttemptStarted" and value["duration_ms"] is None:
            raise SchemaValidationError(f"{event_type} requires monotonic duration_ms")


def validate_study(value: Mapping[str, Any]) -> None:
    """Validate a public study contract."""

    _require_exact_fields(value, STUDY_FIELDS, "study")
    if value["schema_version"] != SCHEMA_VERSION:
        raise SchemaValidationError("study schema_version mismatch")
    for key in (
        "study_id",
        "study_contract_version",
        "task_catalog_version",
        "source_commit",
        "analysis_mode",
    ):
        _require_string(value, key)
    for key in ("schedule_digest", "task_catalog_digest", "source_manifest_digest"):
        _require_digest(value, key)
    _require_int(value, "schedule_seed")
    _require_int(value, "expected_episode_count", minimum=1)
    _require_int(value, "expected_provider_event_count")
    for key in (
        "expected_cells",
        "runtime_order",
        "condition_order",
        "model_bindings",
        "provider_bindings",
        "execution_order",
    ):
        _require_list(value, key)
    _require_bool(value, "public_data_only")
    _require_bool(value, "synthetic_only")
    _require_bool(value, "provider_calls_permitted")


def validate_analysis(value: Mapping[str, Any]) -> None:
    """Validate a public analysis result."""

    _require_exact_fields(value, ANALYSIS_FIELDS, "analysis")
    if value["schema_version"] != SCHEMA_VERSION:
        raise SchemaValidationError("analysis schema_version mismatch")
    _require_string(value, "study_id")
    _require_string(value, "analysis_status")
    _require_digest(value, "episode_ledger_digest")
    _require_digest(value, "aggregate_digest")
    _require_object(value, "estimands")
    limitations = _require_list(value, "limitations")
    if not all(isinstance(item, str) for item in limitations):
        raise SchemaValidationError("analysis limitations must be strings")


def validate_manifest(value: Mapping[str, Any]) -> None:
    """Validate the bundle manifest shape before trusting any path or digest."""

    _require_exact_fields(value, MANIFEST_FIELDS, "manifest")
    if value["schema_version"] != SCHEMA_VERSION:
        raise SchemaValidationError("manifest schema_version mismatch")
    _require_string(value, "bundle_version")
    _require_string(value, "study_id")
    files = _require_object(value, "files")
    if not files:
        raise SchemaValidationError("manifest files must not be empty")
    for relative_path, descriptor in files.items():
        if relative_path.startswith(("/", "\\")) or ".." in relative_path.split("/"):
            raise SchemaValidationError(f"unsafe manifest path: {relative_path}")
        if not isinstance(descriptor, dict) or set(descriptor) != {"sha256", "size"}:
            raise SchemaValidationError(f"invalid file descriptor: {relative_path}")
        _require_digest(descriptor, "sha256")
        _require_int(descriptor, "size")
    _require_int(value, "episode_count")
    _require_int(value, "provider_event_count")
    for key in (
        "study_digest",
        "episode_ledger_digest",
        "provider_event_ledger_digest",
        "aggregate_digest",
        "analysis_digest",
        "redaction_policy_digest",
        "source_manifest_digest",
        "schedule_digest",
        "task_catalog_digest",
    ):
        _require_digest(value, key)


def schema_documents() -> dict[str, dict[str, Any]]:
    """Return the published JSON Schema documents used in public bundles."""

    digest = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    non_empty = {"type": "string", "minLength": 1}
    nullable_string = {"type": ["string", "null"]}
    nullable_integer = {"type": ["integer", "null"], "minimum": 0}
    base = {"$schema": "https://json-schema.org/draft/2020-12/schema"}

    def strict_object(
        properties: dict[str, Any], required: Sequence[str], *, title: str
    ) -> dict[str, Any]:
        return {
            **base,
            "title": title,
            "type": "object",
            "properties": properties,
            "required": list(required),
            "additionalProperties": False,
        }

    item_properties: dict[str, dict[str, Any]] = {
        "semantic_decisions": {
            "decision_type": non_empty,
            "value": {},
            "sequence_index": {"type": "integer", "minimum": 0},
        },
        "tool_calls": {
            "call_id": non_empty,
            "tool_name": non_empty,
            "arguments_digest": digest,
            "sequence_index": {"type": "integer", "minimum": 0},
            "idempotency_key_digest": digest,
        },
        "tool_results": {
            "call_id": non_empty,
            "status": non_empty,
            "result_digest": digest,
            "error_type": nullable_string,
            "sequence_index": {"type": "integer", "minimum": 0},
        },
        "fault_injection_events": {
            "fault_id": non_empty,
            "fault_family": non_empty,
            "injection_point": non_empty,
            "observable_symptom": non_empty,
            "sequence_index": {"type": "integer", "minimum": 0},
        },
        "runtime_recovery_events": {
            "mechanism": non_empty,
            "outcome": non_empty,
            "related_call_id": non_empty,
            "sequence_index": {"type": "integer", "minimum": 0},
        },
        "evaluator_clause_definitions": {
            "clause_id": non_empty,
            "description": non_empty,
            "severity": non_empty,
            "state_path": non_empty,
            "operator": {"enum": ["digest_equals", "digest_not_equals"]},
            "expected_digest": digest,
        },
        "evaluator_clause_outcomes": {
            "clause_id": non_empty,
            "passed": {"type": "boolean"},
            "observed_digest": digest,
            "evidence_paths": {"type": "array", "items": non_empty},
        },
    }
    episode_properties: dict[str, Any] = {
        "schema_version": {"const": SCHEMA_VERSION},
        **{
            key: non_empty
            for key in (
                "episode_id",
                "study_id",
                "task_template_id",
                "task_version",
                "domain",
                "fault_family",
                "runtime",
                "condition",
                "model_binding",
                "provider_binding",
                "schedule_block_id",
                "terminal_reason",
            )
        },
        **{
            key: digest
            for key in (
                "request_digest",
                "policy_digest",
                "source_manifest_digest",
                "initial_state_digest",
                "final_state_digest",
                "trace_digest",
            )
        },
        **{
            key: {"type": "integer", "minimum": 0}
            for key in (
                "environment_seed",
                "sampling_trial",
                "execution_order_index",
                "severe_side_effect_count",
            )
        },
        "task_success": {"type": "boolean"},
        "safe_success": {"type": "boolean"},
        **{
            key: {"type": "object"}
            for key in ("initial_public_state", "final_public_state", "public_state_diff")
        },
        **{
            key: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": sorted(properties),
                    "additionalProperties": False,
                },
            }
            for key, properties in item_properties.items()
        },
        "logical_provider_call_ids": {
            "type": "array",
            "items": non_empty,
            "uniqueItems": True,
        },
    }
    provider_properties = {
        "schema_version": {"const": SCHEMA_VERSION},
        "event_type": {
            "enum": [
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
        },
        "sequence_index": {"type": "integer", "minimum": 1},
        "logical_call_id": non_empty,
        "episode_id": non_empty,
        "turn_index": {"type": "integer", "minimum": 0},
        "request_digest": digest,
        "model_binding": non_empty,
        "attempt_id": nullable_string,
        "ordinal": {"type": ["integer", "null"], "minimum": 1},
        "duration_ms": nullable_integer,
        "status": nullable_string,
        "error_type": nullable_string,
        "retry_decision": nullable_string,
        "input_tokens": nullable_integer,
        "output_tokens": nullable_integer,
        "cost_usd": {
            "type": ["string", "null"],
            "pattern": r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        },
        "currency": {"enum": ["USD", None]},
        "accepted": {"type": ["boolean", "null"]},
    }
    string_array = {"type": "array", "items": non_empty, "uniqueItems": True}
    study_properties = {
        "schema_version": {"const": SCHEMA_VERSION},
        **{
            key: non_empty
            for key in (
                "study_id",
                "study_contract_version",
                "task_catalog_version",
                "source_commit",
                "analysis_mode",
            )
        },
        "schedule_seed": {"type": "integer", "minimum": 0},
        "schedule_digest": digest,
        "task_catalog_digest": digest,
        "source_manifest_digest": digest,
        "expected_episode_count": {"type": "integer", "minimum": 1},
        "expected_provider_event_count": {"type": "integer", "minimum": 0},
        "expected_cells": string_array,
        "runtime_order": string_array,
        "condition_order": string_array,
        "model_bindings": string_array,
        "provider_bindings": string_array,
        "execution_order": string_array,
        "public_data_only": {"const": True},
        "synthetic_only": {"const": True},
        "provider_calls_permitted": {"type": "boolean"},
    }
    analysis_properties = {
        "schema_version": {"const": SCHEMA_VERSION},
        "study_id": non_empty,
        "analysis_status": non_empty,
        "episode_ledger_digest": digest,
        "aggregate_digest": digest,
        "estimands": {"type": "object"},
        "limitations": {"type": "array", "items": {"type": "string"}},
    }
    file_descriptor = {
        "type": "object",
        "properties": {
            "sha256": digest,
            "size": {"type": "integer", "minimum": 0},
        },
        "required": ["sha256", "size"],
        "additionalProperties": False,
    }
    manifest_properties = {
        "schema_version": {"const": SCHEMA_VERSION},
        "bundle_version": non_empty,
        "study_id": non_empty,
        "files": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": file_descriptor,
        },
        "episode_count": {"type": "integer", "minimum": 0},
        "provider_event_count": {"type": "integer", "minimum": 0},
        **{
            key: digest
            for key in (
                "study_digest",
                "episode_ledger_digest",
                "provider_event_ledger_digest",
                "aggregate_digest",
                "analysis_digest",
                "redaction_policy_digest",
                "source_manifest_digest",
                "schedule_digest",
                "task_catalog_digest",
            )
        },
    }
    return {
        "episode.schema.json": strict_object(
            episode_properties, sorted(EPISODE_FIELDS), title="ARL public episode v1"
        ),
        "provider-call.schema.json": strict_object(
            provider_properties,
            sorted(PROVIDER_EVENT_FIELDS),
            title="ARL provider audit event v1",
        ),
        "study.schema.json": strict_object(
            study_properties, sorted(STUDY_FIELDS), title="ARL public study v1"
        ),
        "analysis.schema.json": strict_object(
            analysis_properties, sorted(ANALYSIS_FIELDS), title="ARL public analysis v1"
        ),
        "manifest.schema.json": strict_object(
            manifest_properties, sorted(MANIFEST_FIELDS), title="ARL evidence manifest v1"
        ),
    }
