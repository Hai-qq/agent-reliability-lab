"""Deterministic reactive oracle policy for the pilot preflight."""

from __future__ import annotations

from arl.core.types import Observation, ToolAction, digest_value
from arl_mainstudy.protocol import AgentFeedback
from arl_pilot.specs import PilotTaskSpec


class PilotOracleAgent:
    """Emit the same policy while requiring canonical feedback where the task needs it."""

    policy_id = "pilot-reactive-oracle-v1"
    model_calls = 0

    def __init__(self, spec: PilotTaskSpec) -> None:
        self.spec = spec
        self._actions = spec.semantic_actions
        self._fault_action_index = next(
            index
            for index, operation in enumerate(spec.semantic_operations)
            if operation.operation_id == spec.fault_operation_id
        )
        self._index = 0
        self._started = False
        self.terminal_reason: str | None = None

    @property
    def policy_digest(self) -> str:
        return digest_value(
            {
                "policy_id": self.policy_id,
                "template_id": self.spec.template_id,
                "semantic_actions": [action.as_dict() for action in self._actions],
                "reactive_contract": (
                    "require the exact canonical result after the drifted result operation"
                    if self.spec.fault_family == "output_schema_drift"
                    else "accepted feedback advances the fixed semantic plan"
                ),
            }
        )

    @property
    def action_count(self) -> int:
        return len(self._actions)

    def reset(self, observation: Observation) -> None:
        if observation.task_id != self.spec.task_id:
            raise ValueError("Pilot oracle received the wrong task observation")
        self._index = 0
        self._started = True
        self.terminal_reason = None

    def next_action(self, feedback: AgentFeedback | None) -> ToolAction | None:
        if not self._started:
            raise RuntimeError("PilotOracleAgent must be reset before use")
        if feedback is not None and not feedback.accepted:
            self.terminal_reason = feedback.error_code or "runtime_rejected_action"
            return None
        if (
            self.spec.fault_family == "output_schema_drift"
            and self._index == self._fault_action_index + 1
            and (
                feedback is None
                or feedback.value
                != dict(self.spec.semantic_operations[self._fault_action_index].result_value)
            )
        ):
            self.terminal_reason = "canonical_drifted_result_missing"
            return None
        if self._index >= len(self._actions):
            self.terminal_reason = "plan_complete"
            return None
        action = self._actions[self._index]
        self._index += 1
        return action
