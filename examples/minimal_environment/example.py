"""Minimal local implementation of the stable environment Protocol."""

from __future__ import annotations

from typing import Any

from arl.environments import StatefulEnvironment


class CounterEnvironment:
    """A deterministic synthetic counter with one normalized tool."""

    def __init__(self) -> None:
        self._state = {"value": 0, "task_template_id": "", "seed": 0}

    def reset(self, *, task_template_id: str, environment_seed: int) -> dict[str, Any]:
        self._state = {
            "value": environment_seed,
            "task_template_id": task_template_id,
            "seed": environment_seed,
        }
        return self.snapshot()

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        if set(action) != {"tool_name", "amount"} or action["tool_name"] != "counter.add":
            return {"status": "rejected", "error_type": "unknown_action"}
        self._state["value"] += int(action["amount"])
        return {"status": "ok", "state": self.snapshot()}

    def snapshot(self) -> dict[str, Any]:
        return dict(self._state)


environment: StatefulEnvironment = CounterEnvironment()
print(environment.reset(task_template_id="example.counter", environment_seed=0))
print(environment.step({"tool_name": "counter.add", "amount": 1}))
