"""Explicitly labelled exploratory analysis for a valid but unqualified v0.28 run."""

from __future__ import annotations

import copy
from typing import Any

from arl_opencode_v28.analysis import analyze_study


def build_exploratory_analysis(
    summary: dict[str, Any],
    *,
    iterations: int = 10_000,
    seed: int = 20_260_809,
) -> dict[str, Any]:
    """Analyze a valid matrix after the preregistered readiness gate fails.

    The confirmatory analyzer remains fail-closed. This wrapper verifies that its
    only failed analysis-validity check is the readiness gate, then relabels the
    resulting estimates as exploratory diagnostics.
    """

    if summary.get("validity", {}).get("all_selected_checks_passed") is not True:
        raise ValueError("Exploratory input must pass the infrastructure validity gate")
    if summary.get("readiness", {}).get("ready_for_confirmatory_analysis") is not False:
        raise ValueError("Exploratory path requires a recorded failed readiness gate")

    confirmatory = analyze_study(summary, iterations=iterations, seed=seed)
    confirmatory_checks = dict(confirmatory["validity"]["checks"])
    readiness_check = confirmatory_checks.pop("input_ready_for_confirmatory_analysis", None)
    if readiness_check is not False or not all(confirmatory_checks.values()):
        raise ValueError("Exploratory input has failed analysis checks beyond the readiness gate")

    result = copy.deepcopy(confirmatory)
    result["analysis_contract"].update(
        {
            "analysis_id": "arl-opencode-go-flash-qwen-exploratory-analysis-v1",
            "analysis_mode": "exploratory",
            "confirmatory_claim_allowed": False,
            "cross_model_consistency": False,
            "cross_model_comparison_available": True,
            "trigger": "pre_registered_model_quality_readiness_gate_failed",
        }
    )
    result["confirmatory_eligibility"] = {
        "infrastructure_valid": True,
        "model_quality_readiness_passed": False,
        "confirmatory_analysis_generated": False,
        "reason": ("qwen did not reach 75 percent clean SafePass@3 in every runtime"),
    }
    result["outcome_gates"]["primary_hypothesis_supported"] = False
    result["outcome_gates"]["primary_hypothesis_disposition"] = (
        "not_confirmed_because_the_pre_registered_readiness_gate_failed"
    )
    result["outcome_gates"]["exploratory_fault_effect_ci_positive_for_both_models"] = all(
        result["outcome_gates"]["positive_fault_effect_ci_per_model"].values()
    )
    result["validity"] = {
        "checks": {
            **confirmatory_checks,
            "failed_readiness_gate_recorded": True,
            "exploratory_mode_explicitly_labeled": True,
            "confirmatory_claim_not_emitted": True,
        },
        "all_selected_checks_passed": True,
    }
    result["limitations"] = [
        (
            "The preregistered model-quality readiness gate failed; these intervals "
            "are exploratory and cannot be cited as the confirmatory primary result."
        ),
        *result["limitations"],
    ]
    return result
