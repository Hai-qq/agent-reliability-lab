"""Offline policies implementing the same interface reserved for model adapters."""

from __future__ import annotations

from arl.core.types import Observation, ToolAction, digest_value
from arl_mainstudy.protocol import AgentFeedback


class ScriptedAgent:
    """Emit a frozen semantic plan without using model or runtime-owned metadata."""

    policy_id = "scripted-semantic-plan-v1"
    model_calls = 0

    def __init__(self, actions: tuple[ToolAction, ...]) -> None:
        if not actions:
            raise ValueError("ScriptedAgent requires at least one semantic action")
        if any(
            action.idempotency_key is not None or action.expected_state_version is not None
            for action in actions
        ):
            raise ValueError("Semantic plans cannot contain runtime-owned reliability metadata")
        self._actions = actions
        self._index = 0
        self._started = False

    @property
    def policy_digest(self) -> str:
        return digest_value([action.as_dict() for action in self._actions])

    @property
    def action_count(self) -> int:
        return len(self._actions)

    def reset(self, observation: Observation) -> None:
        _ = observation
        self._index = 0
        self._started = True

    def next_action(self, feedback: AgentFeedback | None) -> ToolAction | None:
        if not self._started:
            raise RuntimeError("ScriptedAgent must be reset before use")
        if feedback is not None and not feedback.accepted:
            return None
        if self._index >= len(self._actions):
            return None
        action = self._actions[self._index]
        self._index += 1
        return action
