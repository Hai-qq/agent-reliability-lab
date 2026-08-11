"""Paired task-cluster bootstrap for SafePass-at-three model-study outcomes."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from arl.core.types import digest_value

ANALYZED_RUNTIMES = ("r1_guarded", "r2_reliable")
ANALYZED_CONDITIONS = ("clean", "recoverable_fault")
EXPECTED_TRIALS = (0, 1, 2)


def _nearest_rank(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("Cannot compute a quantile from an empty distribution")
    if not 0 <= probability <= 1:
        raise ValueError("Probability must be between zero and one")
    ordered = sorted(values)
    index = max(0, math.ceil(probability * len(ordered)) - 1)
    return ordered[index]


def _task_clusters(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cells: dict[tuple[str, str, str], dict[int, bool]] = defaultdict(dict)
    template_ids: set[str] = set()
    for episode in episodes:
        runtime = episode.get("runtime")
        condition = episode.get("condition")
        if runtime not in ANALYZED_RUNTIMES or condition not in ANALYZED_CONDITIONS:
            continue
        template_id = episode.get("template_id")
        trial = episode.get("sampling_trial")
        evaluation = episode.get("evaluation")
        if not isinstance(template_id, str) or trial not in EXPECTED_TRIALS:
            raise ValueError("Episode has an invalid task or sampling trial")
        if not isinstance(evaluation, dict) or not isinstance(evaluation.get("safe_success"), bool):
            raise ValueError("Episode is missing a boolean SafeSuccess outcome")
        key = (template_id, runtime, condition)
        if trial in cells[key]:
            raise ValueError(f"Duplicate sampling trial in {key}")
        cells[key][trial] = evaluation["safe_success"]
        template_ids.add(template_id)

    clusters: list[dict[str, Any]] = []
    for template_id in sorted(template_ids):
        runtimes: dict[str, Any] = {}
        for runtime in ANALYZED_RUNTIMES:
            outcomes: dict[str, bool] = {}
            for condition in ANALYZED_CONDITIONS:
                trials = cells.get((template_id, runtime, condition), {})
                if set(trials) != set(EXPECTED_TRIALS):
                    raise ValueError(
                        f"Incomplete SafePass@3 cell: {template_id}/{runtime}/{condition}"
                    )
                outcomes[condition] = all(trials[index] for index in EXPECTED_TRIALS)
            runtimes[runtime] = {
                "clean_safe_pass_at_3": outcomes["clean"],
                "fault_safe_pass_at_3": outcomes["recoverable_fault"],
                "recovered_fault": outcomes["clean"] and outcomes["recoverable_fault"],
            }
        clusters.append({"template_id": template_id, "runtimes": runtimes})
    if not clusters:
        raise ValueError("No paired R1/R2 task clusters were found")
    return clusters


def _metrics(sample: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    for runtime in ANALYZED_RUNTIMES:
        clean = sum(item["runtimes"][runtime]["clean_safe_pass_at_3"] for item in sample)
        recovered = sum(item["runtimes"][runtime]["recovered_fault"] for item in sample)
        result[f"{runtime}_clean_safe_pass_at_3_rate"] = clean / len(sample)
        result[f"{runtime}_fault_recovery_rate_at_3"] = recovered / clean if clean else 0.0
    result["fault_recovery_rate_at_3_delta_r2_minus_r1"] = (
        result["r2_reliable_fault_recovery_rate_at_3"]
        - result["r1_guarded_fault_recovery_rate_at_3"]
    )
    result["clean_safe_pass_at_3_delta_r2_minus_r1"] = (
        result["r2_reliable_clean_safe_pass_at_3_rate"]
        - result["r1_guarded_clean_safe_pass_at_3_rate"]
    )
    return result


def task_cluster_bootstrap(
    episodes: list[dict[str, Any]],
    *,
    iterations: int = 10_000,
    seed: int = 20_260_808,
) -> dict[str, Any]:
    """Resample paired tasks, never individual trials or runtime-condition cells."""

    if iterations < 1:
        raise ValueError("Bootstrap iterations must be positive")
    if seed < 0:
        raise ValueError("Bootstrap seed must be non-negative")
    clusters = _task_clusters(episodes)
    observed = _metrics(clusters)
    randomizer = random.Random(seed)
    distributions: dict[str, list[float]] = defaultdict(list)
    for _ in range(iterations):
        sample = [clusters[randomizer.randrange(len(clusters))] for _ in clusters]
        for name, value in _metrics(sample).items():
            distributions[name].append(value)

    intervals = {
        name: {
            "observed": observed[name],
            "bootstrap_median": _nearest_rank(values, 0.5),
            "ci_95_percentile": [
                _nearest_rank(values, 0.025),
                _nearest_rank(values, 0.975),
            ],
            "probability_greater_than_zero": sum(value > 0 for value in values) / len(values),
        }
        for name, values in sorted(distributions.items())
    }
    checks = {
        "complete_three_trial_cells": len(clusters) * 12
        == sum(
            1
            for episode in episodes
            if episode.get("runtime") in ANALYZED_RUNTIMES
            and episode.get("condition") in ANALYZED_CONDITIONS
        ),
        "paired_r1_r2_task_clusters": all(
            set(item["runtimes"]) == set(ANALYZED_RUNTIMES) for item in clusters
        ),
        "exact_iteration_count_per_metric": all(
            len(values) == iterations for values in distributions.values()
        ),
        "task_is_the_resampling_unit": True,
    }
    return {
        "analysis_contract": {
            "method": "paired nonparametric task-cluster bootstrap",
            "resampling_unit": "task template with all R1/R2 clean/fault trial cells kept together",
            "safe_pass_at_3": "all three sampling trials must be SafeSuccess",
            "confidence_interval": "two-sided 95% nearest-rank percentile interval",
            "iterations": iterations,
            "seed": seed,
            "task_count": len(clusters),
        },
        "task_clusters": clusters,
        "task_cluster_sha256": digest_value(clusters),
        "estimates": intervals,
        "validity": {
            "checks": checks,
            "all_selected_checks_passed": all(checks.values()),
        },
        "limitations": [
            "The interval describes variation across the observed synthetic task templates.",
            "It does not capture model-provider drift, new domains, or unseen fault families.",
            "Small task packs produce discrete, potentially wide percentile intervals.",
        ],
    }
