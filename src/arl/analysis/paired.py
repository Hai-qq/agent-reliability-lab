"""Paired estimands that use a common task/seed/trial/model population."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from arl.analysis.bootstrap import cluster_bootstrap
from arl.analysis.randomization import exact_mcnemar_p_value, paired_counts

Unit = dict[str, Any]


def _unit_key(episode: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        episode["task_template_id"],
        episode["environment_seed"],
        episode["sampling_trial"],
        episode["model_binding"],
    )


def _complete_units(
    episodes: Sequence[Mapping[str, Any]], *, r1: str, r2: str
) -> tuple[list[Unit], int]:
    cells: dict[tuple[Any, ...], dict[tuple[str, str], Mapping[str, Any]]] = defaultdict(dict)
    for episode in episodes:
        runtime = str(episode["runtime"])
        condition = str(episode["condition"])
        if runtime in {r1, r2} and condition in {"clean", "fault"}:
            key = _unit_key(episode)
            cell = (runtime, condition)
            if cell in cells[key]:
                raise ValueError(f"duplicate paired analysis cell: {key!r} {cell!r}")
            cells[key][cell] = episode
    required = {(r1, "clean"), (r1, "fault"), (r2, "clean"), (r2, "fault")}
    units: list[Unit] = []
    incomplete = 0
    for key in sorted(cells):
        value = cells[key]
        if set(value) != required:
            incomplete += 1
            continue
        units.append(
            {
                "task_template_id": key[0],
                "r1_clean": value[(r1, "clean")],
                "r1_fault": value[(r1, "fault")],
                "r2_clean": value[(r2, "clean")],
                "r2_fault": value[(r2, "fault")],
            }
        )
    return units, incomplete


def _binary_result(
    name: str,
    units: Sequence[Unit],
    outcomes: Callable[[Unit], tuple[bool, bool]],
    *,
    seed: int,
    iterations: int,
    missing_count: int,
    population_rule: str,
) -> dict[str, Any]:
    if not units:
        raise ValueError(f"{name} has no eligible paired units")
    pairs = [outcomes(unit) for unit in units]
    table = paired_counts(pairs)
    differences = [int(second) - int(first) for first, second in pairs]
    estimate = sum(differences) / len(differences)
    clusters: dict[str, list[Unit]] = defaultdict(list)
    for unit in units:
        clusters[str(unit["task_template_id"])].append(unit)

    def statistic(sample: Sequence[Unit]) -> float:
        values = [int(second) - int(first) for first, second in map(outcomes, sample)]
        return sum(values) / len(values)

    return {
        "estimand": name,
        "descriptive_only": False,
        "numerator": sum(differences),
        "denominator": len(differences),
        "paired_2x2_counts": table,
        "point_estimate": estimate,
        "bootstrap_ci": cluster_bootstrap(clusters, statistic, seed=seed, iterations=iterations),
        "sensitivity": {
            "method": "exact_mcnemar_two_sided",
            "discordant_count": table["r1_fail_r2_pass"] + table["r1_pass_r2_fail"],
            "p_value": exact_mcnemar_p_value(table["r1_fail_r2_pass"], table["r1_pass_r2_fail"]),
        },
        "cluster_definition": "task_template_id",
        "resample_seed": seed,
        "iteration_count": iterations,
        "population_rule": population_rule,
        "missing_error_handling_rule": "exclude incomplete four-cell pairs and report the count",
        "excluded_incomplete_pair_count": missing_count,
    }


def _runtime_specific_conditional(units: Sequence[Unit]) -> dict[str, Any]:
    r1_eligible = [unit for unit in units if unit["r1_clean"]["safe_success"]]
    r2_eligible = [unit for unit in units if unit["r2_clean"]["safe_success"]]
    r1_numerator = sum(bool(unit["r1_fault"]["safe_success"]) for unit in r1_eligible)
    r2_numerator = sum(bool(unit["r2_fault"]["safe_success"]) for unit in r2_eligible)
    r1_rate = r1_numerator / len(r1_eligible) if r1_eligible else None
    r2_rate = r2_numerator / len(r2_eligible) if r2_eligible else None
    difference = None if r1_rate is None or r2_rate is None else r2_rate - r1_rate
    return {
        "estimand": "runtime_specific_conditional_recovery_difference",
        "descriptive_only": True,
        "definition": "P(F_R2 | C_R2) - P(F_R1 | C_R1)",
        "r1": {"numerator": r1_numerator, "denominator": len(r1_eligible), "rate": r1_rate},
        "r2": {"numerator": r2_numerator, "denominator": len(r2_eligible), "rate": r2_rate},
        "point_estimate": difference,
        "warning": (
            "Runtime-specific clean denominators are different strata and are not "
            "the primary effect population."
        ),
    }


def analyze_paired_outcomes(
    episodes: Sequence[Mapping[str, Any]],
    *,
    r1: str = "R1",
    r2: str = "R2",
    bootstrap_seed: int = 20260821,
    bootstrap_iterations: int = 2000,
    clean_noninferiority_margin: float = -0.05,
) -> dict[str, Any]:
    """Compute registered post-hoc paired reliability estimands.

    The analysis never changes the validity or claim status of its input study.
    """

    units, incomplete = _complete_units(episodes, r1=r1, r2=r2)
    units_by_template: dict[str, list[Unit]] = defaultdict(list)
    for unit in units:
        units_by_template[str(unit["task_template_id"])].append(unit)
    common_clean_templates = {
        template_id
        for template_id, template_units in units_by_template.items()
        if all(
            unit["r1_clean"]["safe_success"] and unit["r2_clean"]["safe_success"]
            for unit in template_units
        )
    }
    common_clean = [
        unit for unit in units if str(unit["task_template_id"]) in common_clean_templates
    ]
    fault = _binary_result(
        "unconditional_paired_fault_safe_pass_difference",
        units,
        lambda unit: (
            bool(unit["r1_fault"]["safe_success"]),
            bool(unit["r2_fault"]["safe_success"]),
        ),
        seed=bootstrap_seed,
        iterations=bootstrap_iterations,
        missing_count=incomplete,
        population_rule="all complete paired units, without conditioning on clean outcomes",
    )
    common = _binary_result(
        "common_clean_fault_recovery_difference",
        common_clean,
        lambda unit: (
            bool(unit["r1_fault"]["safe_success"]),
            bool(unit["r2_fault"]["safe_success"]),
        ),
        seed=bootstrap_seed + 1,
        iterations=bootstrap_iterations,
        missing_count=incomplete,
        population_rule=(
            "task-template clusters for which every complete unit passes both R1 and R2 clean"
        ),
    )
    clean = _binary_result(
        "clean_safe_pass_difference",
        units,
        lambda unit: (
            bool(unit["r1_clean"]["safe_success"]),
            bool(unit["r2_clean"]["safe_success"]),
        ),
        seed=bootstrap_seed + 2,
        iterations=bootstrap_iterations,
        missing_count=incomplete,
        population_rule="all complete paired units",
    )
    side_effect = _binary_result(
        "severe_side_effect_risk_difference",
        units,
        lambda unit: (
            bool(unit["r1_fault"]["severe_side_effect_count"] > 0),
            bool(unit["r2_fault"]["severe_side_effect_count"] > 0),
        ),
        seed=bootstrap_seed + 3,
        iterations=bootstrap_iterations,
        missing_count=incomplete,
        population_rule="all complete paired fault units; event is one or more severe side effects",
    )
    clean_noninferiority = {
        "estimand": "clean_noninferiority",
        "margin": clean_noninferiority_margin,
        "point_estimate": clean["point_estimate"],
        "confidence_interval_lower": clean["bootstrap_ci"]["lower"],
        "passed": clean["bootstrap_ci"]["lower"] >= clean_noninferiority_margin,
        "decision_rule": "lower 95% task-cluster bootstrap bound >= margin",
        "analysis_status": "posthoc_methodology_reanalysis",
    }
    return {
        "analysis_status": "posthoc_methodology_reanalysis",
        "replaces_original_analysis": False,
        "changes_original_validity": False,
        "confirmatory_claim": False,
        "runtime_specific_conditional_recovery_difference": _runtime_specific_conditional(units),
        "unconditional_paired_fault_safe_pass_difference": fault,
        "common_clean_fault_recovery_difference": common,
        "clean_safe_pass_difference": clean,
        "clean_noninferiority": clean_noninferiority,
        "severe_side_effect_risk_difference": side_effect,
    }
