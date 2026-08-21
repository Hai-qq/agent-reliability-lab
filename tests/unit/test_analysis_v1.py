from __future__ import annotations

import unittest

from arl.analysis.diagnostics import conditional_denominator_diagnostic
from arl.analysis.paired import analyze_paired_outcomes
from arl.analysis.randomization import exact_mcnemar_p_value, paired_counts


def episode(
    template: str,
    seed: int,
    runtime: str,
    condition: str,
    safe: bool,
    severe: int = 0,
) -> dict[str, object]:
    return {
        "task_template_id": template,
        "environment_seed": seed,
        "sampling_trial": 0,
        "model_binding": "slot-a",
        "runtime": runtime,
        "condition": condition,
        "safe_success": safe,
        "severe_side_effect_count": severe,
    }


class PairedAnalysisTests(unittest.TestCase):
    def toy_data(self) -> list[dict[str, object]]:
        values = []
        specifications = [
            # R1 clean, R1 fault, R2 clean, R2 fault
            ("t1", 0, True, False, True, True),
            ("t1", 1, True, False, True, False),
            ("t2", 0, True, True, False, True),
            ("t2", 1, False, False, False, True),
        ]
        for template, seed, r1_clean, r1_fault, r2_clean, r2_fault in specifications:
            values.extend(
                [
                    episode(template, seed, "R1", "clean", r1_clean),
                    episode(template, seed, "R1", "fault", r1_fault),
                    episode(template, seed, "R2", "clean", r2_clean),
                    episode(template, seed, "R2", "fault", r2_fault),
                ]
            )
        return values

    def test_old_conditional_and_unconditional_estimands_are_not_equal(self) -> None:
        result = analyze_paired_outcomes(
            self.toy_data(), bootstrap_seed=7, bootstrap_iterations=100
        )
        old = result["runtime_specific_conditional_recovery_difference"]
        new = result["unconditional_paired_fault_safe_pass_difference"]
        self.assertTrue(old["descriptive_only"])
        self.assertNotEqual(old["r1"]["denominator"], old["r2"]["denominator"])
        self.assertNotEqual(old["point_estimate"], new["point_estimate"])
        self.assertEqual(new["denominator"], 4)
        self.assertEqual(result["analysis_status"], "posthoc_methodology_reanalysis")
        self.assertFalse(result["confirmatory_claim"])
        self.assertTrue(conditional_denominator_diagnostic(old)["descriptive_only"])

    def test_common_clean_and_cluster_bootstrap_metadata(self) -> None:
        result = analyze_paired_outcomes(
            self.toy_data(), bootstrap_seed=9, bootstrap_iterations=120
        )
        common = result["common_clean_fault_recovery_difference"]
        self.assertEqual(common["denominator"], 2)
        self.assertEqual(common["cluster_definition"], "task_template_id")
        self.assertEqual(common["bootstrap_ci"]["iteration_count"], 120)
        self.assertEqual(common["bootstrap_ci"]["resample_seed"], 10)

    def test_exact_mcnemar_and_paired_counts(self) -> None:
        counts = paired_counts([(False, True), (False, True), (True, False), (True, True)])
        self.assertEqual(counts["r1_fail_r2_pass"], 2)
        self.assertEqual(counts["r1_pass_r2_fail"], 1)
        self.assertEqual(exact_mcnemar_p_value(0, 0), 1.0)
        self.assertAlmostEqual(exact_mcnemar_p_value(3, 0), 0.25)


if __name__ == "__main__":
    unittest.main()
