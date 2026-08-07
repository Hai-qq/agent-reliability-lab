from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_multitask.experiment import run_workspace_multitask_experiment


class WorkspaceMultiTaskValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-v03-validity-")
        cls.result = run_workspace_multitask_experiment(Path(cls._temporary.name) / "traces")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_two_task_paired_matrix(self) -> None:
        aggregate = self.result["aggregate"]
        self.assertEqual(aggregate["episode_count"], 24)
        self.assertEqual(aggregate["task_count"], 2)
        self.assertEqual(aggregate["by_runtime"]["r1_guarded"]["clean_successes"], 6)
        self.assertEqual(aggregate["by_runtime"]["r1_guarded"]["fault_successes"], 0)
        self.assertEqual(aggregate["by_runtime"]["r2_confirmed"]["clean_successes"], 6)
        self.assertEqual(aggregate["by_runtime"]["r2_confirmed"]["fault_successes"], 6)
        self.assertEqual(aggregate["paired_recovery_rate_delta_r2_minus_r1"], 1.0)
        self.assertTrue(self.result["validity"]["all_selected_checks_passed"])

    def test_allowed_change_and_evaluator_mutations(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["allowed_metadata_change"]["passed"])
        self.assertTrue(validity["evaluator_mutations"]["passed"])
        self.assertEqual(len(validity["evaluator_mutations"]["cases"]), 5)
        self.assertTrue(validity["notification_idempotent_replay"]["passed"])
        self.assertTrue(validity["notification_transaction_rollback"]["passed"])


if __name__ == "__main__":
    unittest.main()
