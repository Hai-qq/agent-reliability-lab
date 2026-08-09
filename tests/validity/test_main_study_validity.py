from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_mainstudy.experiment import run_scripted_smoke

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MainStudyValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-main-study-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_scripted_smoke(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_smoke_matrix_and_recovery_delta(self) -> None:
        aggregate = self.result["aggregate"]
        self.assertEqual(aggregate["episode_count"], 12)
        self.assertEqual(aggregate["model_calls"], 0)
        self.assertEqual(aggregate["external_network_calls"], 0)
        self.assertEqual(
            aggregate["by_runtime"]["r0_raw"]["by_condition"]["clean"]["safe_successes"],
            2,
        )
        self.assertEqual(
            aggregate["by_runtime"]["r1_guarded"]["by_condition"]["recoverable_fault"][
                "safe_successes"
            ],
            0,
        )
        self.assertEqual(
            aggregate["by_runtime"]["r2_reliable"]["by_condition"]["recoverable_fault"][
                "safe_successes"
            ],
            2,
        )
        self.assertEqual(aggregate["fault_recovery_rate_delta_r2_minus_r1"], 1.0)

    def test_validity_and_trace_privacy_gates(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(all(validity["checks"].values()))
        self.assertEqual(validity["trace_payloads"]["trace_count"], 12)
        self.assertFalse(validity["trace_payloads"]["forbidden_payload_findings"])
        self.assertEqual(len(list(self.traces_dir.glob("*.jsonl"))), 12)

    def test_planned_catalog_is_not_reported_as_implemented(self) -> None:
        catalog = self.result["validity"]["catalog"]
        self.assertEqual(catalog["implementation_status_counts"]["existing_core"], 6)
        self.assertEqual(catalog["implementation_status_counts"]["planned"], 18)
        self.assertIn("Only two existing task templates", self.result["limitations"][0])


if __name__ == "__main__":
    unittest.main()
