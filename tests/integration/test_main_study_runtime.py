from __future__ import annotations

import unittest

from arl.core.types import ToolAction
from arl_mainstudy.adapters import SMOKE_TEMPLATE_IDS
from arl_mainstudy.agents import ScriptedAgent
from arl_mainstudy.contract import RUNTIME_NAMES
from arl_mainstudy.experiment import run_episode


class MainStudyRuntimeIntegrationTests(unittest.TestCase):
    def test_same_policy_clean_passes_across_all_runtime_profiles(self) -> None:
        for template_id in SMOKE_TEMPLATE_IDS:
            results = [
                run_episode(
                    template_id=template_id,
                    runtime_name=runtime_name,
                    condition="clean",
                    trace_path=None,
                )
                for runtime_name in RUNTIME_NAMES
            ]
            with self.subTest(template_id=template_id):
                self.assertEqual(len({item["policy"]["policy_sha256"] for item in results}), 1)
                self.assertTrue(all(item["evaluation"]["safe_success"] for item in results))
                self.assertTrue(all(item["execution"]["completed_plan"] for item in results))

    def test_only_r2_confirms_and_recovers_postcommit_response_loss(self) -> None:
        for template_id in SMOKE_TEMPLATE_IDS:
            by_runtime = {
                runtime_name: run_episode(
                    template_id=template_id,
                    runtime_name=runtime_name,
                    condition="recoverable_fault",
                    trace_path=None,
                )
                for runtime_name in RUNTIME_NAMES
            }
            with self.subTest(template_id=template_id):
                self.assertFalse(by_runtime["r0_raw"]["evaluation"]["safe_success"])
                self.assertEqual(by_runtime["r0_raw"]["execution"]["retry_count"], 0)
                self.assertFalse(by_runtime["r1_guarded"]["evaluation"]["safe_success"])
                self.assertEqual(by_runtime["r1_guarded"]["execution"]["retry_count"], 1)
                self.assertTrue(by_runtime["r2_reliable"]["evaluation"]["safe_success"])
                self.assertEqual(by_runtime["r2_reliable"]["execution"]["confirmation_count"], 1)
                self.assertEqual(
                    by_runtime["r2_reliable"]["observed_fault_ids"],
                    [by_runtime["r2_reliable"]["expected_fault_id"]],
                )

    def test_scripted_policy_rejects_runtime_owned_metadata(self) -> None:
        with self.assertRaises(ValueError):
            ScriptedAgent(
                (
                    ToolAction(
                        tool_name="example.write",
                        schema_version="1.0",
                        arguments={},
                        idempotency_key="agent-supplied",
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
