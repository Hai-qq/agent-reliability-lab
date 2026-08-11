from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_pilot.experiment import run_pilot_preflight

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class PilotPreflightValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-pilot-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_pilot_preflight(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_matrix_and_runtime_recovery_rates(self) -> None:
        aggregate = self.result["aggregate"]
        self.assertEqual(aggregate["episode_count"], 48)
        self.assertEqual(aggregate["model_calls"], 0)
        self.assertEqual(aggregate["external_network_calls"], 0)
        self.assertEqual(aggregate["by_runtime"]["r0_raw"]["recovery_rate"], 0.0)
        self.assertEqual(aggregate["by_runtime"]["r1_guarded"]["recovery_rate"], 0.125)
        self.assertEqual(aggregate["by_runtime"]["r2_reliable"]["recovery_rate"], 1.0)
        self.assertEqual(aggregate["fault_recovery_rate_delta_r2_minus_r1"], 0.875)

    def test_all_validity_and_mechanism_gates_pass(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(all(validity["checks"].values()))
        self.assertEqual(
            validity["mechanism_counts"],
            {
                "postcommit_confirmations": 3,
                "retryable_invocation_retries": 2,
                "input_schema_adaptations": 1,
                "output_schema_normalizations": 1,
                "compatible_conflict_rebases": 1,
                "compensation_actions": 3,
            },
        )

    def test_evaluator_mutations_and_trace_privacy_pass(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(all(validity["do_nothing"].values()))
        self.assertTrue(all(item["passed"] for item in validity["evaluator_mutations"].values()))
        self.assertEqual(validity["trace_payloads"]["trace_count"], 48)
        self.assertFalse(validity["trace_payloads"]["forbidden_payload_findings"])
        self.assertEqual(len(list(self.traces_dir.glob("*.jsonl"))), 48)


if __name__ == "__main__":
    unittest.main()
