from __future__ import annotations

import unittest

from arl_dualmode.analysis import analyze_dual_mode, dual_mode_task_cluster_bootstrap


def _summary(mode_id: str) -> dict[str, object]:
    episodes: list[dict[str, object]] = []
    r1_fault_pass_count = 1 if mode_id == "flash_non_thinking" else 6
    for task_index in range(24):
        for runtime in ("r0_raw", "r1_guarded", "r2_reliable"):
            for condition in ("clean", "recoverable_fault"):
                for trial in range(3):
                    safe = condition == "clean"
                    if condition == "recoverable_fault":
                        safe = runtime == "r2_reliable" or (
                            runtime == "r1_guarded" and task_index < r1_fault_pass_count
                        )
                    episodes.append(
                        {
                            "template_id": f"task-{task_index:02d}",
                            "domain": f"domain-{task_index % 3}",
                            "fault_family": f"fault-{task_index % 6}",
                            "runtime": runtime,
                            "condition": condition,
                            "sampling_trial": trial,
                            "initial_state_hash": f"reset-{task_index:02d}",
                            "evaluation": {"safe_success": safe},
                        }
                    )
    return {
        "validity": {"all_selected_checks_passed": True},
        "aggregate": {
            "primary_effects": {
                "fault_recovery_rate_at_3_delta_r2_minus_r1": (24 - r1_fault_pass_count) / 24,
                "clean_safe_pass_at_3_delta_r2_minus_r1": 0.0,
            },
            "by_runtime": {
                runtime: {
                    "by_condition": {
                        "clean": {"safe_pass_at_3_rate": 1.0},
                        "recoverable_fault": {"safe_pass_at_3_rate": 1.0},
                    }
                }
                for runtime in ("r0_raw", "r1_guarded", "r2_reliable")
            },
        },
        "episodes": episodes,
    }


class DualModeAnalysisTests(unittest.TestCase):
    def test_paired_bootstrap_keeps_both_modes_inside_each_task_cluster(self) -> None:
        summaries = {
            "flash_non_thinking": _summary("flash_non_thinking"),
            "flash_thinking_high": _summary("flash_thinking_high"),
        }
        result = analyze_dual_mode(summaries, iterations=100, seed=7)
        self.assertTrue(result["validity"]["all_selected_checks_passed"])
        paired = result["paired_dual_mode_bootstrap"]
        self.assertEqual(paired["analysis_contract"]["task_count"], 24)
        self.assertEqual(len(paired["task_clusters"]), 24)
        self.assertTrue(paired["joint_fault_effect"]["observed_both_modes_greater_than_zero"])
        self.assertEqual(
            paired["estimates"]["flash_non_thinking_fault_recovery_delta_r2_minus_r1"]["observed"],
            23 / 24,
        )
        self.assertTrue(result["outcome_gates"]["amended_primary_hypothesis_supported"])

    def test_missing_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expected exactly the two modes"):
            dual_mode_task_cluster_bootstrap(
                {"flash_non_thinking": _summary("flash_non_thinking")["episodes"]},
                iterations=10,
            )


if __name__ == "__main__":
    unittest.main()
