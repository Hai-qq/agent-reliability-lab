from __future__ import annotations

import unittest

from arl.runtime.journal import EventJournal
from arl_mainstudy.model import (
    ExactModelBinding,
    ModelAgent,
    ModelBudget,
    ModelDecision,
    ModelRequest,
    ModelUsage,
    SamplingConfig,
)
from arl_pilot.env import PilotEnvironment
from arl_pilot.evaluator import evaluate_pilot_task
from arl_pilot.runtime import PilotRuntime
from arl_pilot.specs import SPECS_BY_TEMPLATE_ID


class FakeStructuredBackend:
    binding = ExactModelBinding(
        provider="offline-test",
        model_id="fake-pilot-model",
        revision="test-v1",
    )

    def __init__(self, decisions: list[ModelDecision]) -> None:
        self.decisions = decisions
        self.requests: list[ModelRequest] = []

    def generate(self, request: ModelRequest) -> ModelDecision:
        self.requests.append(request)
        return self.decisions.pop(0)


class PilotModelContractIntegrationTests(unittest.TestCase):
    def test_provider_neutral_model_agent_can_drive_pilot_runtime(self) -> None:
        spec = SPECS_BY_TEMPLATE_ID["workspace.schedule-meeting.main-v1"]
        decisions = [
            ModelDecision(
                kind="tool",
                tool_name=action.tool_name,
                arguments=action.arguments,
                usage=ModelUsage(10, 4, 0.0),
            )
            for action in spec.semantic_actions
        ]
        backend = FakeStructuredBackend(decisions)
        agent = ModelAgent(
            backend=backend,
            tools=spec.model_tools,
            sampling=SamplingConfig(
                temperature=0.0, top_p=1.0, max_output_tokens=128, sampling_seed=0
            ),
            budget=ModelBudget(
                max_calls=4,
                max_input_tokens=1_000,
                max_output_tokens=200,
                max_monetary_cost=0.0,
            ),
        )
        environment = PilotEnvironment(spec, "clean")
        try:
            observation = environment.reset(spec.task_id, 0)
            pre_snapshot = environment.snapshot()
            agent.reset(observation)
            runtime = PilotRuntime("r2_reliable")
            journal = EventJournal(
                run_id="pilot-model-contract-test",
                episode_id="pilot-model-contract-test-episode",
                task_id=spec.task_id,
                seed=0,
            )
            feedback = None
            for ordinal in range(1, len(spec.semantic_actions) + 1):
                action = agent.next_action(feedback)
                self.assertIsNotNone(action)
                assert action is not None
                self.assertIsNone(action.idempotency_key)
                self.assertIsNone(action.expected_state_version)
                _, feedback = runtime.execute(
                    environment,
                    action,
                    journal,
                    episode_key="pilot-model-contract-test-episode",
                    action_ordinal=ordinal,
                )
                self.assertTrue(feedback.accepted)
            report = evaluate_pilot_task(
                spec,
                "clean",
                pre_snapshot,
                environment.snapshot(),
                journal.as_dicts(),
            )
            self.assertTrue(report.safe_success)
            self.assertEqual(agent.model_calls, 3)
            self.assertEqual(len(backend.requests), 3)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
