from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_resilience.experiment import run_resilience_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ResilienceValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-v09-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_resilience_experiment(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_cross_domain_matrix_and_recovery_delta(self) -> None:
        aggregate = self.result["aggregate"]
        baseline = aggregate["by_runtime"]["r2_confirmed"]
        guarded = aggregate["by_runtime"]["r2_contract_guarded"]
        self.assertEqual(aggregate["episode_count"], 36)
        self.assertEqual(baseline["by_condition"]["control"]["task_successes"], 6)
        self.assertEqual(
            baseline["by_condition"]["compatible_conflict"]["task_successes"],
            0,
        )
        self.assertEqual(guarded["by_condition"]["control"]["task_successes"], 6)
        self.assertEqual(
            guarded["by_condition"]["compatible_conflict"]["task_successes"],
            6,
        )
        self.assertEqual(
            guarded["by_condition"]["incompatible_conflict"]["task_successes"],
            0,
        )
        self.assertEqual(aggregate["compatible_recovery_rate_delta"], 1.0)
        self.assertEqual(guarded["incompatible_conflict_classified_abort_rate"], 1.0)

    def test_validity_gates_and_historical_manifests(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(validity["cross_domain_compatible_recovery"]["passed"])
        self.assertTrue(validity["cross_domain_incompatible_fail_closed"]["passed"])
        self.assertTrue(validity["compensation_contract_audit"]["passed"])
        self.assertEqual(validity["compensation_contract_audit"]["attempts"], 9)
        self.assertEqual(validity["compensation_contract_audit"]["successes"], 6)
        self.assertEqual(validity["compensation_contract_audit"]["failures"], 3)
        self.assertTrue(validity["guard_contract_mutations"]["passed"])
        self.assertTrue(validity["compensation_contract_mutations"]["passed"])
        self.assertTrue(validity["reset_snapshot_and_baselines"]["passed"])
        self.assertTrue(validity["historical_source_manifests"]["passed"])
        self.assertEqual(len(validity["historical_source_manifests"]["increments"]), 8)
        self.assertEqual(len(list(self.traces_dir.glob("*.jsonl"))), 36)


if __name__ == "__main__":
    unittest.main()
