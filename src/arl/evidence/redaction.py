"""Deny-by-default redaction policy for public evidence.

Redaction is validation, not best-effort scrubbing. Unknown fields or suspected
secrets abort publication so that a caller cannot mistake silently transformed
content for the evidence actually evaluated.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from arl.evidence.schema import EPISODE_FIELDS, PROVIDER_EVENT_FIELDS


class RedactionError(ValueError):
    """Raised when evidence contains a disallowed or sensitive value."""


_SENSITIVE_FIELD = re.compile(
    r"(?:api[_-]?key|authorization|bearer|cookie|credential|password|secret|"
    r"raw[_-]?(?:prompt|response|reasoning)|system[_-]?prompt|access[_-]?token|"
    r"refresh[_-]?token|private[_-]?key)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("authorization", re.compile(r"\b(?:authorization\s*:|bearer\s+)[^\s]+", re.I)),
    ("key-like token", re.compile(r"\b(?:sk|pk|api)[-_][A-Za-z0-9_-]{12,}\b", re.I)),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\b")),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
    ("cookie", re.compile(r"\b(?:set-cookie|cookie)\s*:", re.I)),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

_LIST_ITEM_ALLOWLISTS: dict[str, frozenset[str]] = {
    "semantic_decisions": frozenset({"decision_type", "value", "sequence_index"}),
    "tool_calls": frozenset(
        {"call_id", "tool_name", "arguments_digest", "sequence_index", "idempotency_key_digest"}
    ),
    "tool_results": frozenset(
        {"call_id", "status", "result_digest", "error_type", "sequence_index"}
    ),
    "fault_injection_events": frozenset(
        {"fault_id", "fault_family", "injection_point", "observable_symptom", "sequence_index"}
    ),
    "runtime_recovery_events": frozenset(
        {"mechanism", "outcome", "related_call_id", "sequence_index"}
    ),
    "evaluator_clause_definitions": frozenset(
        {"clause_id", "description", "severity", "state_path", "operator", "expected_digest"}
    ),
    "evaluator_clause_outcomes": frozenset(
        {"clause_id", "passed", "observed_digest", "evidence_paths"}
    ),
}


def _scan_sensitive(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RedactionError(f"non-string field at {path}")
            if _SENSITIVE_FIELD.search(key):
                raise RedactionError(f"sensitive field rejected at {path}.{key}")
            _scan_sensitive(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            _scan_sensitive(item, f"{path}[{index}]")
    elif isinstance(value, str):
        for label, pattern in _SENSITIVE_VALUE_PATTERNS:
            if pattern.search(value):
                raise RedactionError(f"suspected {label} rejected at {path}")


class EvidenceRedactor:
    """Validate explicit project-owned synthetic fields for public export.

    Parameters are per-bundle allowlists. No state field is public unless its
    top-level name is explicitly present in ``public_state_fields``.
    """

    def __init__(self, *, public_state_fields: Sequence[str]) -> None:
        fields = tuple(public_state_fields)
        if not fields or any(not isinstance(item, str) or not item for item in fields):
            raise RedactionError("public_state_fields must contain non-empty names")
        if len(set(fields)) != len(fields):
            raise RedactionError("public_state_fields must be unique")
        for field in fields:
            if _SENSITIVE_FIELD.search(field):
                raise RedactionError(f"sensitive state field cannot be allowlisted: {field}")
        self._public_state_fields = frozenset(fields)

    @property
    def public_state_fields(self) -> tuple[str, ...]:
        """Return the sorted allowlist used by this redactor."""

        return tuple(sorted(self._public_state_fields))

    def policy(self) -> dict[str, Any]:
        """Return the complete machine-readable publication policy."""

        return {
            "schema_version": "arl-evidence-v1",
            "policy_id": "deny-by-default-v1",
            "unknown_field_behavior": "reject",
            "sensitive_value_behavior": "reject",
            "synthetic_only": True,
            "public_state_fields": list(self.public_state_fields),
            "episode_fields": sorted(EPISODE_FIELDS),
            "provider_event_fields": sorted(PROVIDER_EVENT_FIELDS),
            "list_item_fields": {
                key: sorted(value) for key, value in sorted(_LIST_ITEM_ALLOWLISTS.items())
            },
            "prohibited_content": [
                "api_key",
                "authorization_header",
                "cookie",
                "credential",
                "email",
                "raw_model_response",
                "raw_prompt",
                "raw_reasoning",
                "real_account_data",
                "system_prompt",
                "unknown_state_field",
            ],
        }

    def _validate_projection(self, value: Any, label: str) -> None:
        if not isinstance(value, dict):
            raise RedactionError(f"{label} must be an object")
        unknown = sorted(set(value) - self._public_state_fields)
        if unknown:
            raise RedactionError(f"{label} contains non-allowlisted fields: {unknown}")
        _scan_sensitive(value, label)

    def _validate_list_items(self, episode: Mapping[str, Any], field: str) -> None:
        values = episode.get(field)
        if not isinstance(values, list):
            raise RedactionError(f"{field} must be an array")
        allowed = _LIST_ITEM_ALLOWLISTS[field]
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                raise RedactionError(f"{field}[{index}] must be an object")
            unknown = sorted(set(item) - allowed)
            if unknown:
                raise RedactionError(f"{field}[{index}] contains unknown fields: {unknown}")
            _scan_sensitive(item, f"{field}[{index}]")

    def validate_episode(self, episode: Mapping[str, Any]) -> None:
        """Fail closed unless an episode is safe for deterministic publication."""

        unknown = sorted(set(episode) - EPISODE_FIELDS)
        if unknown:
            raise RedactionError(f"episode contains unknown fields: {unknown}")
        for field in ("initial_public_state", "final_public_state", "public_state_diff"):
            self._validate_projection(episode.get(field), field)
        for field in _LIST_ITEM_ALLOWLISTS:
            self._validate_list_items(episode, field)
        _scan_sensitive(episode)

    def validate_provider_event(self, event: Mapping[str, Any]) -> None:
        """Fail closed unless a provider audit event contains normalized metadata only."""

        unknown = sorted(set(event) - PROVIDER_EVENT_FIELDS)
        if unknown:
            raise RedactionError(f"provider event contains unknown fields: {unknown}")
        _scan_sensitive(event)

    def validate_document(self, value: Any, *, label: str) -> None:
        """Scan a non-ledger public document for secret patterns."""

        _scan_sensitive(value, label)
