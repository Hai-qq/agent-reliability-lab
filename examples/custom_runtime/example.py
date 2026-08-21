"""Minimal custom reliability runtime using stable public Protocols."""

from __future__ import annotations

from typing import Any

from arl.environments import StatefulEnvironment
from arl.evaluation import StateEvaluator
from arl.runtime import AgentPolicy, ReliabilityRuntime


class IncrementPolicy:
    def decide(self, observation: dict[str, Any]) -> dict[str, Any]:
        return {"tool_name": "counter.add", "amount": 1}


class OneStepRuntime:
    @property
    def runtime_id(self) -> str:
        return "example.one-step.v1"

    def run(
        self,
        *,
        environment: StatefulEnvironment,
        policy: AgentPolicy,
        evaluator: StateEvaluator,
    ) -> dict[str, Any]:
        observation = environment.snapshot()
        result = environment.step(policy.decide(observation))
        final = environment.snapshot()
        return {
            "runtime_id": self.runtime_id,
            "result_status": result["status"],
            "evaluation": evaluator.evaluate(
                initial_state=observation, final_state=final, events=[]
            ),
        }


print(
    "This module defines OneStepRuntime; combine it with the minimal environment and "
    "a StateEvaluator implementation in your local study."
)
assert isinstance(IncrementPolicy(), AgentPolicy)
assert isinstance(OneStepRuntime(), ReliabilityRuntime)
