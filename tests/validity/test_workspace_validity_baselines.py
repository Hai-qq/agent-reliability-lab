from __future__ import annotations

import unittest
from pathlib import Path

from arl_validity.baselines import run_dump_state_baseline, run_random_valid_tool_baseline
from arl_validity.experiment import run_workspace_validity_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class WorkspaceValidityBaselineTests(unittest.TestCase):
    def test_random_valid_tool_baseline_is_weak_and_deterministic(self) -> None:
        first = run_random_valid_tool_baseline()
        second = run_random_valid_tool_baseline()
        self.assertEqual(first, second)
        self.assertTrue(first["passed"])
        self.assertEqual(first["rollout_count"], 120)
        self.assertEqual(first["schema_error_count"], 0)

    def test_dump_state_baselines_are_rejected_without_state_change(self) -> None:
        result = run_dump_state_baseline()
        self.assertTrue(result["passed"])
        self.assertEqual(result["case_count"], 12)
        self.assertTrue(all(case["state_hash_unchanged"] for case in result["cases"]))
        self.assertFalse(any(case["task_success"] for case in result["cases"]))

    def test_full_validity_experiment_passes(self) -> None:
        result = run_workspace_validity_experiment(PROJECT_ROOT)
        self.assertTrue(result["validity"]["all_selected_checks_passed"])
        self.assertEqual(result["metadata"]["model_calls"], 0)
        self.assertEqual(result["metadata"]["external_network_calls"], 0)


if __name__ == "__main__":
    unittest.main()
