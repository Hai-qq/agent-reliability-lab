"""Deterministic design-stage power simulation for clustered paired outcomes."""

from __future__ import annotations

import math
import random
import statistics
from typing import Any


def simulate_clustered_power(
    template_count: int,
    *,
    repetitions_per_template: int = 9,
    baseline_probability: float = 0.60,
    target_difference: float = 0.082,
    cluster_standard_deviation: float = 0.08,
    simulation_count: int = 2000,
    seed: int = 20260821,
) -> float:
    """Estimate one-sided power using task-template cluster means.

    This is a frozen planning assumption, not evidence about any model.
    """

    if template_count < 2 or repetitions_per_template < 1 or simulation_count < 1:
        raise ValueError("power simulation sizes are invalid")
    generator = random.Random(seed + template_count)
    rejections = 0
    critical_value = 1.6448536269514722
    for _ in range(simulation_count):
        cluster_differences: list[float] = []
        for _template in range(template_count):
            cluster_shift = generator.gauss(0.0, cluster_standard_deviation)
            r1_probability = min(0.95, max(0.05, baseline_probability + cluster_shift))
            r2_probability = min(0.95, max(0.05, r1_probability + target_difference))
            differences = [
                int(generator.random() < r2_probability) - int(generator.random() < r1_probability)
                for _repeat in range(repetitions_per_template)
            ]
            cluster_differences.append(sum(differences) / repetitions_per_template)
        mean = statistics.fmean(cluster_differences)
        standard_error = statistics.stdev(cluster_differences) / math.sqrt(template_count)
        statistic = mean / standard_error if standard_error else 0.0
        rejections += statistic > critical_value
    return rejections / simulation_count


def select_template_count(
    candidates: list[int] | None = None,
    *,
    target_power: float = 0.80,
) -> dict[str, Any]:
    """Select the first frozen candidate meeting the design-stage power target."""

    selected_candidates = candidates or [24, 32, 40, 48, 56, 64]
    if selected_candidates != sorted(set(selected_candidates)):
        raise ValueError("power candidates must be unique and increasing")
    estimates = {str(count): simulate_clustered_power(count) for count in selected_candidates}
    eligible = [count for count in selected_candidates if estimates[str(count)] >= target_power]
    return {
        "status": "design_assumption_only",
        "model_results_used": False,
        "target_power": target_power,
        "alpha": 0.05,
        "test_sidedness": "one_sided",
        "target_safe_pass_difference": 0.082,
        "task_template_is_resampling_cluster": True,
        "environment_seeds": 3,
        "sampling_trials": 3,
        "simulation_count_per_candidate": 2000,
        "simulation_seed": 20260821,
        "estimated_power": estimates,
        "selected_template_count": eligible[0] if eligible else None,
    }
