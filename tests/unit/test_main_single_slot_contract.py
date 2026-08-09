from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl.core.types import Observation, canonical_json, digest_value
from arl_mainmodel.experiment import SingleSlotModelAgent, main_single_slot_manifest
from arl_mainstudy.model import ModelBudget, SamplingConfig, ToolDefinition
from arl_modelpilot.deepseek import DeepSeekChatBackend
from arl_modelpilot.experiment import bound_pilot_contract
from scripts.run_main_single_slot import validate_paths


class MainSingleSlotContractTests(unittest.TestCase):
    def test_manifest_freezes_exact_432_episode_matrix_without_raw_payloads(self) -> None:
        manifest = main_single_slot_manifest()
        self.assertEqual(len(manifest.jobs), 432)
        payloads = [job.payload() for job in manifest.jobs]
        matrix = {
            (
                payload["template_id"],
                payload["runtime"],
                payload["condition"],
                payload["sampling_trial"],
            )
            for payload in payloads
        }
        self.assertEqual(len(matrix), 432)
        self.assertEqual(len({payload["template_id"] for payload in payloads}), 24)
        serialized = canonical_json(manifest.as_dict()).lower()
        self.assertNotIn("user_request", serialized)
        self.assertNotIn("arguments", serialized)
        self.assertNotIn("api_key", serialized)

    def test_single_bound_slot_does_not_open_confirmatory_main(self) -> None:
        contract = bound_pilot_contract()
        contract.assert_ready("pilot")
        with self.assertRaisesRegex(RuntimeError, "requires 2 exact model binding"):
            contract.assert_ready("main")

    def test_agent_reserves_a_maximum_response_before_calling_provider(self) -> None:
        backend = DeepSeekChatBackend(api_key="sk-budget-reservation-test")
        policy = SingleSlotModelAgent(
            backend=backend,
            tools=(ToolDefinition("records.update", "1.0", ("record_id",)),),
            sampling=SamplingConfig(0.0, 1.0, 512, None),
            budget=ModelBudget(8, 20_000, 2_000, 0.01),
        )
        policy.reset(
            Observation(
                task_id="synthetic.test",
                seed=0,
                env_version="test-v1",
                state_version=0,
                timestamp_logical=0,
                state_hash=digest_value({"state": "initial"}),
                visible_task={"request": "synthetic"},
            )
        )
        policy.output_tokens = 1_592

        self.assertIsNone(policy.next_action(None))
        self.assertEqual(policy.terminal_reason, "model_budget_exhausted")
        self.assertEqual(backend.call_records, [])

    def test_cli_refuses_overwrite_and_unsafe_layout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-main-single-cli-") as temporary:
            root = Path(temporary)
            workspace = root / "study"
            summary = root / "summary.json"
            validate_paths(workspace, summary, resume=False)

            workspace.mkdir()
            with self.assertRaises(SystemExit):
                validate_paths(workspace, summary, resume=False)
            validate_paths(workspace, summary, resume=True)

            with self.assertRaises(SystemExit):
                validate_paths(root / "missing", summary, resume=True)
            with self.assertRaises(SystemExit):
                validate_paths(workspace, workspace / "summary.json", resume=True)


if __name__ == "__main__":
    unittest.main()
