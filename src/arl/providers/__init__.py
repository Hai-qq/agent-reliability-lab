"""Stable provider backend protocol; the core package performs no network calls."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ModelBackend(Protocol):
    """Optional provider adapter returning normalized decisions and audit metadata."""

    @property
    def model_binding(self) -> str:
        """Return the frozen model binding referenced by a study manifest."""
        ...

    def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        """Execute one separately authorized logical call."""
        ...


__all__ = ["ModelBackend"]
