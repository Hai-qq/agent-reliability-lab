from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_conflict.experiment import run_conflict_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ConflictValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-conflict-v08-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_conflict_experiment(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_paired_matrix_and_conflict_delta(self) -> None:
        aggregate = self.result["aggregate"]
        baseline = aggregate["by_runtime"]["r2_confirmed"]
        aware = aggregate["by_runtime"]["r2_conflict_aware"]
        self.assertEqual(aggregate["episode_count"], 18)
        self.assertEqual(baseline["by_condition"]["clean"]["task_successes"], 3)
        self.assertEqual(
            baseline["by_condition"]["compatible_conflict"]["task_successes"],
            0,
        )
        self.assertEqual(aware["by_condition"]["clean"]["task_successes"], 3)
        self.assertEqual(
            aware["by_condition"]["compatible_conflict"]["task_successes"],
            3,
        )
        self.assertEqual(
            aware["by_condition"]["incompatible_conflict"]["task_successes"],
            0,
        )
        self.assertEqual(aware["incompatible_conflict_classified_abort_rate"], 1.0)
        self.assertEqual(aggregate["compatible_recovery_rate_delta"], 1.0)

    def test_validity_gates_and_historical_manifests(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(validity["compatible_conflict_recovered"]["passed"])
        self.assertTrue(validity["incompatible_conflict_fails_closed"]["passed"])
        self.assertTrue(validity["guard_contract_mutations"]["passed"])
        self.assertEqual(len(validity["guard_contract_mutations"]["cases"]), 4)
        self.assertTrue(validity["reset_snapshot_and_baselines"]["passed"])
        self.assertTrue(validity["historical_source_manifests"]["passed"])
        self.assertEqual(len(validity["historical_source_manifests"]["increments"]), 7)
        self.assertEqual(len(list(self.traces_dir.glob("*.jsonl"))), 18)


if __name__ == "__main__":
    unittest.main()
