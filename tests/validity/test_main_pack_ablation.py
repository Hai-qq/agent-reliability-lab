from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_mainpack.ablation import run_main_pack_ablation

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class MainPackAblationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-main-pack-ablation-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_main_pack_ablation(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_matrix_and_validity_pass(self) -> None:
        self.assertEqual(self.result["aggregate"]["episode_count"], 168)
        self.assertTrue(self.result["validity"]["all_selected_checks_passed"])
        self.assertEqual(self.result["validity"]["trace_payloads"]["trace_count"], 168)

    def test_each_mechanism_removal_loses_its_four_target_tasks(self) -> None:
        by_ablation = self.result["aggregate"]["by_ablation"]
        self.assertEqual(by_ablation["baseline"]["safe_successes"], 24)
        for ablation_id, value in by_ablation.items():
            if ablation_id == "baseline":
                continue
            with self.subTest(ablation_id=ablation_id):
                self.assertEqual(value["safe_successes"], 20)
                self.assertAlmostEqual(value["safe_success_rate_delta_vs_baseline"], -1 / 6)

    def test_agent_policy_is_identical_across_all_ablations(self) -> None:
        self.assertTrue(
            all(len(digests) == 1 for digests in self.result["validity"]["policy_digests"].values())
        )


if __name__ == "__main__":
    unittest.main()
