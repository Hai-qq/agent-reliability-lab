from __future__ import annotations

import unittest

from arl.core.types import Observation, digest_value
from arl_mainstudy.model import (
    ExactModelBinding,
    ModelAgent,
    ModelBudget,
    ModelDecision,
    ModelProtocolError,
    ModelRequest,
    ModelUsage,
    SamplingConfig,
    ToolDefinition,
)


class FakeBackend:
    binding = ExactModelBinding(
        provider="offline-test",
        model_id="fake-structured-model",
        revision="test-v1",
    )

    def __init__(self, decisions: list[ModelDecision]) -> None:
        self.decisions = decisions
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelDecision:
        self.requests.append(request)
        return self.decisions.pop(0)


def observation() -> Observation:
    return Observation(
        task_id="synthetic.test",
        seed=0,
        env_version="test-v1",
        state_version=0,
        timestamp_logical=0,
        state_hash=digest_value({"state": "initial"}),
        visible_task={"request": "synthetic"},
    )


def agent(backend: FakeBackend, *, max_calls: int = 2) -> ModelAgent:
    return ModelAgent(
        backend=backend,
        tools=(
            ToolDefinition(
                tool_name="records.update",
                schema_version="1.0",
                required_arguments=("record_id", "status"),
            ),
        ),
        sampling=SamplingConfig(
            temperature=0.0,
            top_p=1.0,
            max_output_tokens=128,
            sampling_seed=7,
        ),
        budget=ModelBudget(
            max_calls=max_calls,
            max_input_tokens=1_000,
            max_output_tokens=100,
            max_monetary_cost=1.0,
        ),
    )


class MainStudyModelContractTests(unittest.TestCase):
    def test_structured_decision_becomes_semantic_action(self) -> None:
        backend = FakeBackend(
            [
                ModelDecision(
                    kind="tool",
                    tool_name="records.update",
                    arguments={"record_id": "record-1", "status": "resolved"},
                    usage=ModelUsage(input_tokens=20, output_tokens=5, monetary_cost=0.01),
                )
            ]
        )
        policy = agent(backend)
        policy.reset(observation())
        action = policy.next_action(None)
        self.assertIsNotNone(action)
        assert action is not None
        self.assertIsNone(action.idempotency_key)
        self.assertIsNone(action.expected_state_version)
        self.assertEqual(action.tool_name, "records.update")
        self.assertEqual(policy.usage_summary()["model_calls"], 1)
        self.assertEqual(len(backend.requests), 1)

    def test_unknown_tool_and_argument_fail_closed(self) -> None:
        for decision in (
            ModelDecision(
                kind="tool",
                tool_name="records.delete",
                arguments={},
                usage=ModelUsage(1, 1, 0.0),
            ),
            ModelDecision(
                kind="tool",
                tool_name="records.update",
                arguments={"record_id": "record-1", "status": "resolved", "hidden": True},
                usage=ModelUsage(1, 1, 0.0),
            ),
        ):
            with self.subTest(tool=decision.tool_name):
                policy = agent(FakeBackend([decision]))
                policy.reset(observation())
                with self.assertRaises(ModelProtocolError):
                    policy.next_action(None)

    def test_call_and_post_response_budgets_stop_actions(self) -> None:
        finish = ModelDecision(
            kind="finish",
            usage=ModelUsage(input_tokens=1, output_tokens=1, monetary_cost=0.0),
        )
        policy = agent(FakeBackend([finish]), max_calls=1)
        policy.reset(observation())
        self.assertIsNone(policy.next_action(None))
        self.assertEqual(policy.terminal_reason, "model_finished")

        oversized = ModelDecision(
            kind="tool",
            tool_name="records.update",
            arguments={"record_id": "record-1", "status": "resolved"},
            usage=ModelUsage(input_tokens=2_000, output_tokens=1, monetary_cost=0.0),
        )
        policy = agent(FakeBackend([oversized]))
        policy.reset(observation())
        self.assertIsNone(policy.next_action(None))
        self.assertEqual(policy.terminal_reason, "model_budget_exceeded_after_response")

    def test_zero_monetary_budget_allows_zero_cost_local_response(self) -> None:
        backend = FakeBackend(
            [
                ModelDecision(
                    kind="finish",
                    usage=ModelUsage(input_tokens=1, output_tokens=1, monetary_cost=0.0),
                )
            ]
        )
        policy = ModelAgent(
            backend=backend,
            tools=(
                ToolDefinition(
                    tool_name="records.update",
                    schema_version="1.0",
                    required_arguments=("record_id", "status"),
                ),
            ),
            sampling=SamplingConfig(0.0, 1.0, 128, 7),
            budget=ModelBudget(1, 1_000, 100, 0.0),
        )
        policy.reset(observation())
        self.assertIsNone(policy.next_action(None))
        self.assertEqual(policy.terminal_reason, "model_finished")
        self.assertEqual(policy.model_calls, 1)

    def test_buffered_decision_does_not_count_as_another_provider_call(self) -> None:
        decision = ModelDecision(
            kind="tool",
            tool_name="records.update",
            arguments={"record_id": "record-1", "status": "resolved"},
            usage=ModelUsage(0, 0, 0.0),
            provider_call_count=0,
        )
        policy = agent(FakeBackend([decision]))
        policy.reset(observation())
        self.assertIsNotNone(policy.next_action(None))
        self.assertEqual(policy.model_calls, 0)


if __name__ == "__main__":
    unittest.main()
