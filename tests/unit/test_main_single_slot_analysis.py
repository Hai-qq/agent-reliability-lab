from __future__ import annotations

import unittest

from scripts.build_main_single_slot_analysis import analyze_main_single_slot


def summary() -> dict[str, object]:
    fault_families = tuple(f"fault-{index}" for index in range(6))
    episodes: list[dict[str, object]] = []
    for task_index in range(24):
        for runtime in ("r0_raw", "r1_guarded", "r2_reliable"):
            for condition in ("clean", "recoverable_fault"):
                for trial in range(3):
                    safe = condition == "clean" or runtime == "r2_reliable"
                    episodes.append(
                        {
                            "template_id": f"task-{task_index:02d}",
                            "domain": f"domain-{task_index % 3}",
                            "fault_family": fault_families[task_index % 6],
                            "runtime": runtime,
                            "condition": condition,
                            "sampling_trial": trial,
                            "evaluation": {"safe_success": safe},
                            "execution": {
                                "failure_code": None,
                                "retry_count": 0,
                                "confirmation_count": 0,
                                "schema_adaptation_count": 0,
                                "result_normalization_count": 0,
                                "conflict_rebase_count": 0,
                                "compensation_action_count": 0,
                            },
                        }
                    )
    return {
        "validity": {"all_selected_checks_passed": True},
        "aggregate": {
            "primary_effects": {
                "fault_recovery_rate_at_3_delta_r2_minus_r1": 1.0,
                "clean_safe_pass_at_3_delta_r2_minus_r1": 0.0,
            }
        },
        "episodes": episodes,
    }


class MainSingleSlotAnalysisTests(unittest.TestCase):
    def test_exact_main_matrix_builds_valid_grouped_analysis(self) -> None:
        result = analyze_main_single_slot(summary(), iterations=100, seed=7)
        self.assertTrue(result["validity"]["all_selected_checks_passed"])
        self.assertEqual(result["task_count"], 24)
        self.assertEqual(len(result["by_fault_family"]), 6)
        self.assertEqual(len(result["by_domain"]), 3)
        self.assertEqual(
            result["bootstrap"]["estimates"]["fault_recovery_rate_at_3_delta_r2_minus_r1"][
                "observed"
            ],
            1.0,
        )

    def test_duplicate_trial_is_rejected(self) -> None:
        value = summary()
        episodes = value["episodes"]
        assert isinstance(episodes, list)
        episodes.append(episodes[0])
        with self.assertRaisesRegex(ValueError, "Duplicate sampling trial"):
            analyze_main_single_slot(value, iterations=10)


if __name__ == "__main__":
    unittest.main()
