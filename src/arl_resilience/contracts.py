"""Public-read guards and auditable compensation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from arl.core.types import StepResult, ToolAction, digest_value


@dataclass(frozen=True)
class StateGuard:
    """An exact precondition or postcondition evaluated through a public read."""

    tool_name: str
    schema_version: str
    arguments: dict[str, Any]
    value_path: tuple[str, ...]
    expected_value: Any

    def __post_init__(self) -> None:
        if not self.tool_name or not self.schema_version:
            raise ValueError("Guard tool name and schema version are required")
        if not self.value_path or any(not item for item in self.value_path):
            raise ValueError("Guard value path must be non-empty")

    def read_action(self, state_version: int) -> ToolAction:
        return ToolAction(
            tool_name=self.tool_name,
            schema_version=self.schema_version,
            arguments=self.arguments,
            expected_state_version=state_version,
        )

    def observed_value(self, result: StepResult) -> tuple[bool, Any]:
        value: Any = result.value
        for key in self.value_path:
            if not isinstance(value, dict) or key not in value:
                return False, None
            value = value[key]
        return True, value

    def matches(self, result: StepResult) -> bool:
        found, value = self.observed_value(result)
        return found and value == self.expected_value

    def audit_descriptor(self) -> dict[str, Any]:
        """Return typed metadata without exporting public-read arguments or values."""
        return {
            "tool_name": self.tool_name,
            "schema_version": self.schema_version,
            "argument_digest": digest_value(self.arguments),
            "value_path": list(self.value_path),
            "expected_digest": digest_value(self.expected_value),
        }


@dataclass(frozen=True)
class GuardedAction:
    action: ToolAction
    guards: tuple[StateGuard, ...] = ()


@dataclass(frozen=True)
class CompensationContract:
    """A bounded recovery write with explicit trigger, preconditions, and postconditions."""

    contract_id: str
    trigger_tool: str
    trigger_error: str
    action: ToolAction
    preconditions: tuple[StateGuard, ...]
    postconditions: tuple[StateGuard, ...]
    max_attempts: int = 1

    def __post_init__(self) -> None:
        if not self.contract_id or not self.trigger_tool or not self.trigger_error:
            raise ValueError("Compensation contract identity and trigger are required")
        if self.max_attempts != 1:
            raise ValueError("Compensation contracts currently require exactly one attempt")
        if not self.preconditions or not self.postconditions:
            raise ValueError("Compensation contracts require preconditions and postconditions")
        if not isinstance(self.action.idempotency_key, str) or not self.action.idempotency_key:
            raise ValueError("Compensation action must use a non-empty idempotency key")

    def matches_trigger(self, tool_name: str, error_code: str | None) -> bool:
        return tool_name == self.trigger_tool and error_code == self.trigger_error

    def guarded_action(self) -> GuardedAction:
        return GuardedAction(action=self.action, guards=self.preconditions)

    def audit_descriptor(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "trigger_tool": self.trigger_tool,
            "trigger_error": self.trigger_error,
            "action_tool": self.action.tool_name,
            "action_digest": digest_value(self.action.as_dict()),
            "preconditions": [item.audit_descriptor() for item in self.preconditions],
            "postconditions": [item.audit_descriptor() for item in self.postconditions],
            "max_attempts": self.max_attempts,
        }
