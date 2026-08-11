from __future__ import annotations

import unittest

from arl_analysis.bootstrap import task_cluster_bootstrap


def _episodes(task_count: int = 4) -> list[dict[str, object]]:
    episodes: list[dict[str, object]] = []
    for task_index in range(task_count):
        for runtime in ("r0_raw", "r1_guarded", "r2_reliable"):
            for condition in ("clean", "recoverable_fault"):
                for trial in range(3):
                    safe = condition == "clean" or runtime == "r2_reliable" or task_index == 0
                    episodes.append(
                        {
                            "template_id": f"task-{task_index}",
                            "runtime": runtime,
                            "condition": condition,
                            "sampling_trial": trial,
                            "evaluation": {"safe_success": safe},
                        }
                    )
    return episodes


class TaskClusterBootstrapTests(unittest.TestCase):
    def test_observed_effect_and_deterministic_bootstrap(self) -> None:
        first = task_cluster_bootstrap(_episodes(), iterations=1_000, seed=7)
        second = task_cluster_bootstrap(_episodes(), iterations=1_000, seed=7)
        self.assertEqual(first, second)
        self.assertTrue(first["validity"]["all_selected_checks_passed"])
        self.assertEqual(first["analysis_contract"]["task_count"], 4)
        self.assertEqual(
            first["estimates"]["fault_recovery_rate_at_3_delta_r2_minus_r1"]["observed"],
            0.75,
        )
        self.assertEqual(
            first["estimates"]["clean_safe_pass_at_3_delta_r2_minus_r1"]["observed"],
            0.0,
        )

    def test_incomplete_trial_cell_is_rejected(self) -> None:
        episodes = _episodes()
        episodes.pop()
        with self.assertRaisesRegex(ValueError, "Incomplete SafePass@3 cell"):
            task_cluster_bootstrap(episodes, iterations=10)

    def test_invalid_iteration_or_seed_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            task_cluster_bootstrap(_episodes(), iterations=0)
        with self.assertRaises(ValueError):
            task_cluster_bootstrap(_episodes(), seed=-1)


if __name__ == "__main__":
    unittest.main()
