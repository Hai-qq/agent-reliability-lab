"""Stable agent-policy and reliability-runtime extension protocols."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from arl.environments import StatefulEnvironment
from arl.evaluation import StateEvaluator


@runtime_checkable
class AgentPolicy(Protocol):
    """Select normalized actions from a public synthetic observation."""

    def decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        """Return one normalized action or terminal decision."""
        ...


@runtime_checkable
class ReliabilityRuntime(Protocol):
    """Coordinate a policy, stateful environment, and evaluator."""

    @property
    def runtime_id(self) -> str:
        """Return the versioned runtime mechanism identifier."""
        ...

    def run(
        self,
        *,
        environment: StatefulEnvironment,
        policy: AgentPolicy,
        evaluator: StateEvaluator,
    ) -> dict[str, Any]:
        """Execute one episode and return normalized public-safe evidence."""
        ...


__all__ = ["AgentPolicy", "ReliabilityRuntime"]
