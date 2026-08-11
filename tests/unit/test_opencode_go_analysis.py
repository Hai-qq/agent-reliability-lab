from __future__ import annotations

import unittest

from arl_openstudy.analysis import analyze_openstudy


def _summary() -> dict[str, object]:
    episodes: list[dict[str, object]] = []
    pass_counts = {"flash": 4, "mimo": 8}
    by_model: dict[str, object] = {}
    for slot, r1_pass_count in pass_counts.items():
        by_model[slot] = {
            "primary_effects": {
                "fault_recovery_rate_at_3_delta_r2_minus_r1": (24 - r1_pass_count) / 24,
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
        }
        for task_index in range(24):
            for runtime in ("r0_raw", "r1_guarded", "r2_reliable"):
                for condition in ("clean", "recoverable_fault"):
                    for trial in range(3):
                        safe = condition == "clean"
                        if condition == "recoverable_fault":
                            safe = runtime == "r2_reliable" or (
                                runtime == "r1_guarded" and task_index < r1_pass_count
                            )
                        episodes.append(
                            {
                                "model_slot": slot,
                                "template_id": f"task-{task_index:02d}",
                                "domain": ("workspace", "retail", "travel")[task_index % 3],
                                "fault_family": f"fault-{task_index % 6}",
                                "runtime": runtime,
                                "condition": condition,
                                "sampling_trial": trial,
                                "initial_state_hash": f"reset-{task_index:02d}",
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
        "aggregate": {"by_model": by_model},
        "episodes": episodes,
    }


class OpenCodeGoAnalysisTests(unittest.TestCase):
    def test_exact_two_model_matrix_builds_joint_task_bootstrap(self) -> None:
        result = analyze_openstudy(_summary(), iterations=100, seed=7)
        self.assertTrue(result["validity"]["all_selected_checks_passed"])
        self.assertTrue(result["outcome_gates"]["primary_hypothesis_supported"])
        joint = result["joint_model_bootstrap"]
        self.assertEqual(joint["analysis_contract"]["task_count"], 24)
        self.assertTrue(joint["joint_fault_effect"]["observed_both_models_greater_than_zero"])

    def test_incomplete_model_matrix_is_rejected(self) -> None:
        summary = _summary()
        episodes = summary["episodes"]
        assert isinstance(episodes, list)
        episodes.pop()
        with self.assertRaisesRegex(ValueError, "Incomplete SafePass@3 cell"):
            analyze_openstudy(summary, iterations=10, seed=7)


if __name__ == "__main__":
    unittest.main()
