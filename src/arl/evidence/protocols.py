"""Stable evidence-writer extension protocol."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EvidenceWriter(Protocol):
    """Write normalized evidence without raw provider or private state content."""

    def add_episode(self, episode: dict[str, Any]) -> None:
        """Validate and stage one public episode."""
        ...

    def finalize(self, output: Path) -> Path:
        """Create a new immutable bundle and return its path."""
        ...


__all__ = ["EvidenceWriter"]
