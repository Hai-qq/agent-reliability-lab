from __future__ import annotations

import unittest

from arl_replication_v30.analysis import analyze_study
from arl_replication_v30.experiment import aggregate_study
from arl_replication_v30.specs import ENVIRONMENT_SEEDS, REPLICATION_TEMPLATES


def summary() -> dict[str, object]:
    episodes: list[dict[str, object]] = []
    r1_pass_counts = {"flash": 5, "pro": 8}
    for slot, r1_count in r1_pass_counts.items():
        for task_index, declaration in enumerate(REPLICATION_TEMPLATES):
            for seed in ENVIRONMENT_SEEDS:
                for runtime in ("r0_raw", "r1_guarded", "r2_reliable"):
                    for condition in ("clean", "recoverable_fault"):
                        for trial in range(3):
                            safe = condition == "clean"
                            if condition == "recoverable_fault":
                                safe = runtime == "r2_reliable" or (
                                    runtime == "r1_guarded" and task_index < r1_count
                                )
                            episodes.append(
                                {
                                    "model_slot": slot,
                                    "template_id": declaration.template_id,
                                    "domain": declaration.domain,
                                    "fault_family": declaration.fault_family,
                                    "environment_seed": seed,
                                    "runtime": runtime,
                                    "condition": condition,
                                    "sampling_trial": trial,
                                    "initial_state_hash": (
                                        f"reset-{declaration.template_id}-seed-{seed}"
                                    ),
                                    "evaluation": {"safe_success": safe},
                                    "policy": {"model_calls": 0},
                                    "provider": {"calls": [], "transport_retry_count": 0},
                                    "external_network_calls": 0,
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
        "readiness": {
            "ready_for_replication_analysis": True,
            "model_quality_checks": {"synthetic": True},
        },
        "aggregate": aggregate_study(episodes, canary=False),
        "episodes": episodes,
    }


class ReplicationV30AnalysisTests(unittest.TestCase):
    def test_task_bootstrap_retains_all_seeds_and_supports_positive_fixture(self) -> None:
        result = analyze_study(summary(), iterations=100, seed=7, confirmatory=True)
        self.assertTrue(result["validity"]["all_selected_checks_passed"])
        self.assertTrue(result["outcome_gates"]["primary_hypothesis_supported"])
        self.assertEqual(result["bootstrap"]["analysis_contract"]["task_count"], 24)
        self.assertEqual(result["bootstrap"]["analysis_contract"]["environment_seed_count"], 3)

    def test_confirmatory_fails_closed_but_exploratory_remains_labeled(self) -> None:
        value = summary()
        value["readiness"] = {"ready_for_replication_analysis": False}
        with self.assertRaisesRegex(RuntimeError, "readiness"):
            analyze_study(value, iterations=10, seed=7, confirmatory=True)
        exploratory = analyze_study(value, iterations=10, seed=7, confirmatory=False)
        self.assertEqual(exploratory["analysis_contract"]["analysis_mode"], "exploratory")
        self.assertFalse(exploratory["outcome_gates"]["primary_hypothesis_supported"])


if __name__ == "__main__":
    unittest.main()
