"""Stable state-level evaluator extension protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StateEvaluator(Protocol):
    """Evaluate final state, invariants, and side effects from public-safe inputs."""

    def clauses(self) -> list[dict[str, Any]]:
        """Return versioned evaluator clause definitions."""
        ...

    def evaluate(
        self,
        *,
        initial_state: dict[str, Any],
        final_state: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Return clause outcomes and task/safety verdicts."""
        ...


__all__ = ["StateEvaluator"]
