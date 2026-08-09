"""Provider-neutral model policy contract with no built-in network implementation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Protocol

from arl.core.types import Observation, ToolAction, digest_value
from arl_mainstudy.protocol import AgentFeedback


class ModelProtocolError(RuntimeError):
    """Raised when a backend response violates the frozen structured-action contract."""


@dataclass(frozen=True)
class ExactModelBinding:
    provider: str
    model_id: str
    revision: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.provider, self.model_id, self.revision)):
            raise ValueError("Exact model binding fields must be non-empty")

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class SamplingConfig:
    temperature: float
    top_p: float
    max_output_tokens: int
    sampling_seed: int | None

    def __post_init__(self) -> None:
        if self.temperature < 0:
            raise ValueError("temperature must be non-negative")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0, 1]")
        if self.max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelBudget:
    max_calls: int
    max_input_tokens: int
    max_output_tokens: int
    max_monetary_cost: float

    def __post_init__(self) -> None:
        if min(self.max_calls, self.max_input_tokens, self.max_output_tokens) < 1:
            raise ValueError("Model call and token budgets must be positive")
        if self.max_monetary_cost < 0:
            raise ValueError("Model monetary budget must be non-negative")


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    monetary_cost: float

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0 or self.monetary_cost < 0:
            raise ValueError("Model usage cannot be negative")

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)


@dataclass(frozen=True)
class ToolDefinition:
    tool_name: str
    schema_version: str
    required_arguments: tuple[str, ...]
    optional_arguments: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.tool_name or not self.schema_version:
            raise ValueError("Tool name and schema version are required")
        names = (*self.required_arguments, *self.optional_arguments)
        if len(set(names)) != len(names):
            raise ValueError("Tool argument names must be unique")

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        keys = set(arguments)
        required = set(self.required_arguments)
        allowed = required | set(self.optional_arguments)
        if not required.issubset(keys):
            raise ModelProtocolError(
                f"Missing required arguments for {self.tool_name}: {sorted(required - keys)}"
            )
        if not keys.issubset(allowed):
            raise ModelProtocolError(
                f"Unknown arguments for {self.tool_name}: {sorted(keys - allowed)}"
            )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModelRequest:
    prompt_contract_version: str
    binding: ExactModelBinding
    task_id: str
    turn_index: int
    observation: dict[str, Any]
    feedback: dict[str, Any] | None
    tools: tuple[ToolDefinition, ...]
    sampling: SamplingConfig

    def as_dict(self) -> dict[str, Any]:
        return {
            "prompt_contract_version": self.prompt_contract_version,
            "binding": self.binding.as_dict(),
            "task_id": self.task_id,
            "turn_index": self.turn_index,
            "observation": self.observation,
            "feedback": self.feedback,
            "tools": [tool.as_dict() for tool in self.tools],
            "sampling": self.sampling.as_dict(),
        }

    @property
    def sha256(self) -> str:
        return digest_value(self.as_dict())


@dataclass(frozen=True)
class ModelDecision:
    kind: Literal["tool", "finish"]
    usage: ModelUsage
    provider_call_count: int = 1
    tool_name: str | None = None
    arguments: dict[str, Any] | None = None
    response_digest: str | None = None

    def __post_init__(self) -> None:
        if self.provider_call_count not in {0, 1}:
            raise ValueError("provider_call_count must be zero or one")
        if self.kind == "tool":
            if not self.tool_name or self.arguments is None:
                raise ValueError("Tool decisions require tool_name and arguments")
        elif self.tool_name is not None or self.arguments is not None:
            raise ValueError("Finish decisions cannot contain a tool action")
        if self.response_digest is not None and len(self.response_digest) != 64:
            raise ValueError("response_digest must be a SHA-256 hex digest")


class ModelBackend(Protocol):
    """A callable backend supplied later by an authorized local or API adapter."""

    binding: ExactModelBinding

    def generate(self, request: ModelRequest) -> ModelDecision: ...


class ModelAgent:
    """Turn structured backend decisions into semantic actions with hard local budgets."""

    policy_id = "structured-model-agent-v1"

    def __init__(
        self,
        *,
        backend: ModelBackend,
        tools: tuple[ToolDefinition, ...],
        sampling: SamplingConfig,
        budget: ModelBudget,
        prompt_contract_version: str = "arl-model-prompt-v1",
    ) -> None:
        if not tools:
            raise ValueError("ModelAgent requires at least one tool definition")
        if len({tool.tool_name for tool in tools}) != len(tools):
            raise ValueError("Model tool names must be unique")
        self.backend = backend
        self.tools = tools
        self.sampling = sampling
        self.budget = budget
        self.prompt_contract_version = prompt_contract_version
        self.model_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.monetary_cost = 0.0
        self.terminal_reason: str | None = None
        self._observation: Observation | None = None
        self._turn_index = 0
        self._tools_by_name = {tool.tool_name: tool for tool in tools}

    @property
    def policy_digest(self) -> str:
        return digest_value(
            {
                "policy_id": self.policy_id,
                "prompt_contract_version": self.prompt_contract_version,
                "binding": self.backend.binding.as_dict(),
                "tools": [tool.as_dict() for tool in self.tools],
                "sampling": self.sampling.as_dict(),
                "budget": asdict(self.budget),
            }
        )

    def reset(self, observation: Observation) -> None:
        self._observation = observation
        self._turn_index = 0
        self.model_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.monetary_cost = 0.0
        self.terminal_reason = None

    def _budget_available(self) -> bool:
        return (
            self.model_calls < self.budget.max_calls
            and self.input_tokens < self.budget.max_input_tokens
            and self.output_tokens < self.budget.max_output_tokens
            and self.monetary_cost <= self.budget.max_monetary_cost
        )

    def _budget_respected(self) -> bool:
        return (
            self.model_calls <= self.budget.max_calls
            and self.input_tokens <= self.budget.max_input_tokens
            and self.output_tokens <= self.budget.max_output_tokens
            and self.monetary_cost <= self.budget.max_monetary_cost
        )

    def next_action(self, feedback: AgentFeedback | None) -> ToolAction | None:
        if self._observation is None:
            raise RuntimeError("ModelAgent must be reset before use")
        if self.terminal_reason is not None:
            return None
        if not self._budget_available():
            self.terminal_reason = "model_budget_exhausted"
            return None
        request = ModelRequest(
            prompt_contract_version=self.prompt_contract_version,
            binding=self.backend.binding,
            task_id=self._observation.task_id,
            turn_index=self._turn_index,
            observation=self._observation.as_dict(),
            feedback=feedback.as_dict() if feedback is not None else None,
            tools=self.tools,
            sampling=self.sampling,
        )
        decision = self.backend.generate(request)
        self.model_calls += decision.provider_call_count
        self.input_tokens += decision.usage.input_tokens
        self.output_tokens += decision.usage.output_tokens
        self.monetary_cost += decision.usage.monetary_cost
        self._turn_index += 1
        if not self._budget_respected():
            self.terminal_reason = "model_budget_exceeded_after_response"
            return None
        if decision.kind == "finish":
            self.terminal_reason = "model_finished"
            return None
        assert decision.tool_name is not None  # guarded by ModelDecision
        assert decision.arguments is not None
        try:
            tool = self._tools_by_name[decision.tool_name]
        except KeyError as error:
            self.terminal_reason = "unknown_model_tool"
            raise ModelProtocolError(
                f"Unknown model-selected tool: {decision.tool_name}"
            ) from error
        tool.validate_arguments(decision.arguments)
        return ToolAction(
            tool_name=tool.tool_name,
            schema_version=tool.schema_version,
            arguments=decision.arguments,
        )

    def usage_summary(self) -> dict[str, int | float | str | None]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "monetary_cost": self.monetary_cost,
            "terminal_reason": self.terminal_reason,
        }
