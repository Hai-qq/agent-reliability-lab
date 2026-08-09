from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_mainpack.experiment import run_main_pack_preflight

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MainPackValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-main-pack-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_main_pack_preflight(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_matrix_and_runtime_recovery_rates(self) -> None:
        aggregate = self.result["aggregate"]
        self.assertEqual(aggregate["episode_count"], 144)
        self.assertEqual(aggregate["task_count"], 24)
        self.assertEqual(aggregate["model_calls"], 0)
        self.assertEqual(aggregate["external_network_calls"], 0)
        self.assertEqual(aggregate["by_runtime"]["r0_raw"]["recovery_rate"], 0.0)
        self.assertEqual(
            aggregate["by_runtime"]["r1_guarded"]["recovery_rate"],
            4 / 24,
        )
        self.assertEqual(aggregate["by_runtime"]["r2_reliable"]["recovery_rate"], 1.0)

    def test_validity_and_mechanism_counts_pass(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(all(validity["checks"].values()))
        self.assertEqual(
            validity["mechanism_counts"],
            {
                "postcommit_confirmations": 4,
                "retryable_invocation_retries": 8,
                "input_schema_adaptations": 4,
                "output_schema_normalizations": 4,
                "compatible_conflict_rebases": 4,
                "compensation_actions": 12,
            },
        )

    def test_evaluator_privacy_and_main_fail_closed_gates_pass(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(all(validity["do_nothing"].values()))
        self.assertTrue(all(item["passed"] for item in validity["evaluator_mutations"].values()))
        self.assertEqual(validity["trace_payloads"]["trace_count"], 144)
        self.assertFalse(validity["trace_payloads"]["forbidden_payload_findings"])
        self.assertFalse(self.result["main_readiness"]["ready_for_864_episode_confirmatory_main"])


if __name__ == "__main__":
    unittest.main()
