"""Stable deterministic fault-injection extension protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class FaultInjector(Protocol):
    """Inject a declared synthetic fault at a deterministic sequence point."""

    @property
    def fault_id(self) -> str:
        """Return the versioned fault identifier."""
        ...

    def inject(self, *, sequence_index: int, state: dict[str, Any]) -> dict[str, Any]:
        """Return normalized observable metadata; never hidden raw state."""
        ...


__all__ = ["FaultInjector"]
