from __future__ import annotations

import unittest

from arl_mainstudy.contract import RUNTIME_NAMES
from arl_pilot.experiment import run_episode
from arl_pilot.specs import PILOT_TASK_SPECS


class PilotRuntimeIntegrationTests(unittest.TestCase):
    def test_clean_matrix_passes_with_same_policy_contract(self) -> None:
        for spec in PILOT_TASK_SPECS:
            results = [
                run_episode(
                    spec=spec,
                    runtime_name=runtime_name,
                    condition="clean",
                    trace_path=None,
                )
                for runtime_name in RUNTIME_NAMES
            ]
            with self.subTest(template_id=spec.template_id):
                self.assertEqual(len({item["policy"]["policy_sha256"] for item in results}), 1)
                self.assertTrue(all(item["evaluation"]["safe_success"] for item in results))
                self.assertTrue(all(item["execution"]["completed_plan"] for item in results))

    def test_fault_matrix_matches_runtime_capabilities(self) -> None:
        expected_success = {
            "postcommit_response_loss": {"r2_reliable"},
            "retryable_invocation_error": {"r1_guarded", "r2_reliable"},
            "input_schema_drift": {"r2_reliable"},
            "output_schema_drift": {"r2_reliable"},
            "compatible_state_conflict": {"r2_reliable"},
            "bounded_compensation": {"r2_reliable"},
        }
        for spec in PILOT_TASK_SPECS:
            for runtime_name in RUNTIME_NAMES:
                result = run_episode(
                    spec=spec,
                    runtime_name=runtime_name,
                    condition="recoverable_fault",
                    trace_path=None,
                )
                with self.subTest(template_id=spec.template_id, runtime=runtime_name):
                    self.assertEqual(
                        result["evaluation"]["safe_success"],
                        runtime_name in expected_success[spec.fault_family],
                    )
                    self.assertEqual(result["observed_fault_ids"], [spec.fault_id])


if __name__ == "__main__":
    unittest.main()
