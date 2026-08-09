"""Provider-neutral policy and runtime protocols for the ARL main study."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from arl.core.types import Observation, StepResult, ToolAction


@dataclass(frozen=True)
class AgentFeedback:
    """Normalized runtime feedback returned to a policy after one semantic action."""

    accepted: bool
    status: str
    error_code: str | None
    recovery_kind: str | None
    value: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgentPolicy(Protocol):
    """The interface shared by scripted smoke policies and future model adapters."""

    policy_id: str
    model_calls: int

    @property
    def policy_digest(self) -> str: ...

    def reset(self, observation: Observation) -> None: ...

    def next_action(self, feedback: AgentFeedback | None) -> ToolAction | None: ...


class RuntimeEnvironment(Protocol):
    """Minimal environment surface needed by the generic action runtime."""

    state_version: int
    logical_time: int
    last_fault_id: str | None

    def state_hash(self) -> str: ...

    def step(self, action: ToolAction) -> StepResult: ...


class RuntimeHooks(Protocol):
    """Domain semantics kept outside the generic R0/R1/R2 controller."""

    domain: str

    def is_write(self, action: ToolAction) -> bool: ...

    def result_contract_valid(
        self,
        environment: RuntimeEnvironment,
        action: ToolAction,
        result: StepResult,
    ) -> bool: ...

    def confirmation_action(self, action: ToolAction, state_version: int) -> ToolAction | None: ...

    def confirmation_matches(self, original: ToolAction, result: StepResult) -> bool: ...
