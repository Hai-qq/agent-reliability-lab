from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_schema.experiment import run_schema_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SchemaValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-schema-v07-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_schema_experiment(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_paired_matrix_and_adapter_delta(self) -> None:
        aggregate = self.result["aggregate"]
        r1 = aggregate["by_runtime"]["r1_guarded"]
        r2 = aggregate["by_runtime"]["r2_schema_adapted"]
        self.assertEqual(aggregate["episode_count"], 24)
        self.assertEqual(r1["clean_successes"], 6)
        self.assertEqual(r1["fault_successes"], 0)
        self.assertEqual(r2["clean_successes"], 6)
        self.assertEqual(r2["fault_successes"], 6)
        self.assertEqual(r2["schema_adaptation_count"], 3)
        self.assertEqual(r2["output_normalization_count"], 3)
        self.assertEqual(aggregate["paired_recovery_rate_delta_r2_minus_r1"], 1.0)

    def test_validity_gates_and_historical_manifests(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(validity["adapter_mutations_rejected"]["passed"])
        self.assertEqual(len(validity["adapter_mutations_rejected"]["cases"]), 9)
        self.assertTrue(validity["public_descriptors_non_oracular"]["passed"])
        self.assertTrue(validity["reset_and_snapshot_restore"]["passed"])
        self.assertTrue(validity["baselines_rejected"]["passed"])
        self.assertTrue(validity["historical_source_manifests"]["passed"])
        self.assertEqual(len(validity["historical_source_manifests"]["increments"]), 6)
        self.assertEqual(len(list(self.traces_dir.glob("*.jsonl"))), 24)


if __name__ == "__main__":
    unittest.main()
