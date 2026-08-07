from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_retail.experiment import run_retail_experiment


class RetailValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-retail-v05-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_retail_experiment(cls.traces_dir)

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

    def test_validity_and_transaction_gates(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["reset_determinism"]["passed"])
        self.assertTrue(validity["snapshot_restore"]["passed"])
        self.assertTrue(validity["refund_transaction_rollback"]["passed"])
        self.assertTrue(validity["nonrefundable_policy_guard"]["passed"])
        self.assertTrue(validity["evaluator_mutations"]["passed"])
        self.assertEqual(len(validity["evaluator_mutations"]["cases"]), 8)
        self.assertEqual(len(list(self.traces_dir.glob("*.jsonl"))), 24)


if __name__ == "__main__":
    unittest.main()
