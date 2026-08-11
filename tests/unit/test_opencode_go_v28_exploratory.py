from __future__ import annotations

import unittest

from arl_opencode_v28.exploratory import build_exploratory_analysis
from tests.unit.test_opencode_go_v28_analysis import _summary


class OpenCodeGoV28ExploratoryAnalysisTests(unittest.TestCase):
    def test_failed_readiness_builds_explicit_exploratory_result(self) -> None:
        summary = _summary()
        summary["readiness"] = {"ready_for_confirmatory_analysis": False}

        result = build_exploratory_analysis(summary, iterations=10, seed=7)

        self.assertTrue(result["validity"]["all_selected_checks_passed"])
        self.assertEqual(result["analysis_contract"]["analysis_mode"], "exploratory")
        self.assertFalse(result["analysis_contract"]["confirmatory_claim_allowed"])
        self.assertFalse(result["analysis_contract"]["cross_model_consistency"])
        self.assertTrue(result["analysis_contract"]["cross_model_comparison_available"])
        self.assertFalse(result["outcome_gates"]["primary_hypothesis_supported"])

    def test_ready_input_is_refused_by_exploratory_path(self) -> None:
        with self.assertRaisesRegex(ValueError, "failed readiness gate"):
            build_exploratory_analysis(_summary(), iterations=10, seed=7)

    def test_invalid_infrastructure_is_refused(self) -> None:
        summary = _summary()
        summary["validity"] = {"all_selected_checks_passed": False}
        summary["readiness"] = {"ready_for_confirmatory_analysis": False}
        with self.assertRaisesRegex(ValueError, "infrastructure validity"):
            build_exploratory_analysis(summary, iterations=10, seed=7)


if __name__ == "__main__":
    unittest.main()
