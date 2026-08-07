"""Typed, JSON-serializable contracts shared by the ARL prototype."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

StepStatus = Literal["ok", "retryable_error", "fatal_error", "conflict"]


def canonical_json(value: Any) -> str:
    """Serialize a value deterministically for hashing and artifacts."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def digest_value(value: Any) -> str:
    """Return a SHA-256 digest of a canonical JSON value."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolAction:
    """A versioned tool invocation visible to the runtime and environment."""

    tool_name: str
    schema_version: str
    arguments: dict[str, Any]
    idempotency_key: str | None = None
    expected_state_version: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StepResult:
    """A stable result contract; errors are classified instead of string-only."""

    status: StepStatus
    value: dict[str, Any] | None
    error_code: str | None
    state_version: int
    retry_after_ms: int | None
    state_hash_before: str
    state_hash_after: str
    timestamp_logical: int

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Observation:
    """The task-visible state returned by ``Environment.reset``."""

    task_id: str
    seed: int
    env_version: str
    state_version: int
    timestamp_logical: int
    state_hash: str
    visible_task: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SnapshotRef:
    """An immutable, integrity-checked local environment snapshot."""

    payload_json: str
    sha256: str

    @classmethod
    def from_value(cls, value: dict[str, Any]) -> SnapshotRef:
        payload = canonical_json(value)
        return cls(
            payload_json=payload,
            sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        )

    def load(self) -> dict[str, Any]:
        actual = hashlib.sha256(self.payload_json.encode("utf-8")).hexdigest()
        if actual != self.sha256:
            raise ValueError("Snapshot integrity check failed")
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):
            raise ValueError("Snapshot payload must be an object")
        return value


@dataclass(frozen=True)
class EvaluationReport:
    """Machine-readable state and process evaluation output."""

    task_success: bool
    safe_success: bool
    expected_state_ok: bool
    collateral_damage: tuple[str, ...]
    milestones: dict[str, bool]
    minefields_triggered: tuple[str, ...]
    policy_violations: tuple[str, ...]
    recovery_events: tuple[str, ...]
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
