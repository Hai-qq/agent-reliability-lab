"""Stable environment extension protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StatefulEnvironment(Protocol):
    """Local stateful system controlled through normalized tool actions."""

    def reset(self, *, task_template_id: str, environment_seed: int) -> dict[str, Any]:
        """Reset to a deterministic synthetic state and return its public observation."""
        ...

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        """Apply one normalized action and return a typed result."""
        ...

    def snapshot(self) -> dict[str, Any]:
        """Return an integrity-hashable synthetic state snapshot."""
        ...


__all__ = ["StatefulEnvironment"]
