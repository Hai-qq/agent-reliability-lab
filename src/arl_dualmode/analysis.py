"""Paired task-cluster analysis across two inference modes of one model."""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

from arl.core.types import digest_value
from arl_analysis.bootstrap import task_cluster_bootstrap
from arl_mainstudy.contract import CONDITIONS, RUNTIME_NAMES

MODE_IDS = ("flash_non_thinking", "flash_thinking_high")
ANALYZED_RUNTIMES = ("r1_guarded", "r2_reliable")
TRIALS = (0, 1, 2)


def _nearest_rank(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def _mode_task_rows(episodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    descriptors: dict[str, tuple[str, str]] = {}
    cells: dict[tuple[str, str, str], dict[int, bool]] = defaultdict(dict)
    for episode in episodes:
        template_id = episode.get("template_id")
        domain = episode.get("domain")
        fault_family = episode.get("fault_family")
        runtime = episode.get("runtime")
        condition = episode.get("condition")
        trial = episode.get("sampling_trial")
        evaluation = episode.get("evaluation")
        if not all(isinstance(value, str) for value in (template_id, domain, fault_family)):
            raise ValueError("Episode is missing its task descriptor")
        if runtime not in RUNTIME_NAMES or condition not in CONDITIONS or trial not in TRIALS:
            raise ValueError("Episode has an invalid runtime, condition, or trial")
        if not isinstance(evaluation, dict) or not isinstance(evaluation.get("safe_success"), bool):
            raise ValueError("Episode is missing a boolean SafeSuccess outcome")
        assert isinstance(template_id, str)
        descriptor = (str(domain), str(fault_family))
        if template_id in descriptors and descriptors[template_id] != descriptor:
            raise ValueError(f"Task descriptor drifted: {template_id}")
        descriptors[template_id] = descriptor
        key = (template_id, str(runtime), str(condition))
        if int(trial) in cells[key]:
            raise ValueError(f"Duplicate trial in {key}")
        cells[key][int(trial)] = evaluation["safe_success"]

    rows: dict[str, dict[str, Any]] = {}
    for template_id, (domain, fault_family) in sorted(descriptors.items()):
        runtime_rows: dict[str, Any] = {}
        for runtime in ANALYZED_RUNTIMES:
            outcomes: dict[str, bool] = {}
            for condition in CONDITIONS:
                trials = cells.get((template_id, runtime, condition), {})
                if set(trials) != set(TRIALS):
                    raise ValueError(
                        f"Incomplete SafePass@3 cell: {template_id}/{runtime}/{condition}"
                    )
                outcomes[condition] = all(trials[trial] for trial in TRIALS)
            runtime_rows[runtime] = {
                "clean_safe_pass_at_3": outcomes["clean"],
                "fault_safe_pass_at_3": outcomes["recoverable_fault"],
                "recovered_fault": outcomes["clean"] and outcomes["recoverable_fault"],
            }
        rows[template_id] = {
            "template_id": template_id,
            "domain": domain,
            "fault_family": fault_family,
            "runtimes": runtime_rows,
        }
    return rows


def _paired_clusters(
    episodes_by_mode: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if set(episodes_by_mode) != set(MODE_IDS):
        raise ValueError(f"Expected exactly the two modes {MODE_IDS!r}")
    rows_by_mode = {
        mode_id: _mode_task_rows(episodes) for mode_id, episodes in episodes_by_mode.items()
    }
    task_sets = {mode_id: set(rows) for mode_id, rows in rows_by_mode.items()}
    if len({frozenset(values) for values in task_sets.values()}) != 1:
        raise ValueError("Inference modes do not contain the same task templates")
    task_ids = sorted(next(iter(task_sets.values())))
    clusters: list[dict[str, Any]] = []
    for template_id in task_ids:
        first = rows_by_mode[MODE_IDS[0]][template_id]
        second = rows_by_mode[MODE_IDS[1]][template_id]
        if (first["domain"], first["fault_family"]) != (
            second["domain"],
            second["fault_family"],
        ):
            raise ValueError(f"Task descriptor differs across modes: {template_id}")
        clusters.append(
            {
                "template_id": template_id,
                "domain": first["domain"],
                "fault_family": first["fault_family"],
                "modes": {
                    mode_id: rows_by_mode[mode_id][template_id]["runtimes"] for mode_id in MODE_IDS
                },
            }
        )
    return clusters


def _metrics(sample: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    fault_deltas: list[float] = []
    clean_deltas: list[float] = []
    for mode_id in MODE_IDS:
        values: dict[str, float] = {}
        for runtime in ANALYZED_RUNTIMES:
            clean = sum(item["modes"][mode_id][runtime]["clean_safe_pass_at_3"] for item in sample)
            recovered = sum(item["modes"][mode_id][runtime]["recovered_fault"] for item in sample)
            values[f"{runtime}_clean_rate"] = clean / len(sample)
            values[f"{runtime}_recovery_rate"] = recovered / clean if clean else 0.0
        fault_delta = values["r2_reliable_recovery_rate"] - values["r1_guarded_recovery_rate"]
        clean_delta = values["r2_reliable_clean_rate"] - values["r1_guarded_clean_rate"]
        result[f"{mode_id}_fault_recovery_delta_r2_minus_r1"] = fault_delta
        result[f"{mode_id}_clean_delta_r2_minus_r1"] = clean_delta
        fault_deltas.append(fault_delta)
        clean_deltas.append(clean_delta)
    result["macro_fault_recovery_delta_r2_minus_r1"] = sum(fault_deltas) / len(fault_deltas)
    result["macro_clean_delta_r2_minus_r1"] = sum(clean_deltas) / len(clean_deltas)
    return result


def dual_mode_task_cluster_bootstrap(
    episodes_by_mode: dict[str, list[dict[str, Any]]],
    *,
    iterations: int = 10_000,
    seed: int = 20_260_809,
) -> dict[str, Any]:
    """Resample tasks while keeping both modes and all paired cells together."""

    if iterations < 1:
        raise ValueError("Bootstrap iterations must be positive")
    if seed < 0:
        raise ValueError("Bootstrap seed must be non-negative")
    clusters = _paired_clusters(episodes_by_mode)
    observed = _metrics(clusters)
    randomizer = random.Random(seed)
    distributions: dict[str, list[float]] = defaultdict(list)
    both_positive_count = 0
    for _ in range(iterations):
        sample = [clusters[randomizer.randrange(len(clusters))] for _ in clusters]
        metrics = _metrics(sample)
        for name, value in metrics.items():
            distributions[name].append(value)
        if all(metrics[f"{mode_id}_fault_recovery_delta_r2_minus_r1"] > 0 for mode_id in MODE_IDS):
            both_positive_count += 1
    estimates = {
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
        "exact_24_paired_task_clusters": len(clusters) == 24,
        "both_modes_retained_within_each_cluster": all(
            set(item["modes"]) == set(MODE_IDS) for item in clusters
        ),
        "exact_iteration_count_per_metric": all(
            len(values) == iterations for values in distributions.values()
        ),
        "task_is_the_resampling_unit": True,
    }
    return {
        "analysis_contract": {
            "method": "paired nonparametric task-cluster bootstrap across inference modes",
            "resampling_unit": (
                "task template with both modes and all R1/R2 clean/fault trials retained"
            ),
            "safe_pass_at_3": "all three sampling trials must be SafeSuccess",
            "confidence_interval": "two-sided 95% nearest-rank percentile interval",
            "iterations": iterations,
            "seed": seed,
            "task_count": len(clusters),
            "mode_count": len(MODE_IDS),
        },
        "task_clusters": clusters,
        "task_cluster_sha256": digest_value(clusters),
        "estimates": estimates,
        "joint_fault_effect": {
            "observed_both_modes_greater_than_zero": all(
                observed[f"{mode_id}_fault_recovery_delta_r2_minus_r1"] > 0 for mode_id in MODE_IDS
            ),
            "bootstrap_probability_both_modes_greater_than_zero": (
                both_positive_count / iterations
            ),
        },
        "validity": {
            "checks": checks,
            "all_selected_checks_passed": all(checks.values()),
        },
    }


def analyze_dual_mode(
    summaries: dict[str, dict[str, Any]],
    *,
    iterations: int = 10_000,
    seed: int = 20_260_809,
) -> dict[str, Any]:
    """Build per-mode and jointly paired estimates from two valid full summaries."""

    if set(summaries) != set(MODE_IDS):
        raise ValueError(f"Expected exactly the two modes {MODE_IDS!r}")
    episodes_by_mode: dict[str, list[dict[str, Any]]] = {}
    per_mode: dict[str, Any] = {}
    for mode_id in MODE_IDS:
        episodes = summaries[mode_id].get("episodes")
        if not isinstance(episodes, list):
            raise ValueError(f"{mode_id} summary has no episode list")
        episodes_by_mode[mode_id] = episodes
        per_mode[mode_id] = task_cluster_bootstrap(
            episodes,
            iterations=iterations,
            seed=seed,
        )
    paired = dual_mode_task_cluster_bootstrap(
        episodes_by_mode,
        iterations=iterations,
        seed=seed,
    )
    reset_hashes: dict[str, set[str]] = defaultdict(set)
    for episodes in episodes_by_mode.values():
        for episode in episodes:
            reset_hashes[episode["template_id"]].add(episode["initial_state_hash"])
    observed_matches = all(
        per_mode[mode_id]["estimates"]["fault_recovery_rate_at_3_delta_r2_minus_r1"]["observed"]
        == summaries[mode_id]["aggregate"]["primary_effects"][
            "fault_recovery_rate_at_3_delta_r2_minus_r1"
        ]
        for mode_id in MODE_IDS
    )
    checks = {
        "both_input_infrastructure_gates_pass": all(
            summaries[mode_id].get("validity", {}).get("all_selected_checks_passed")
            for mode_id in MODE_IDS
        ),
        "exact_432_episodes_per_mode": all(
            len(episodes_by_mode[mode_id]) == 432 for mode_id in MODE_IDS
        ),
        "exact_864_episodes_total": sum(map(len, episodes_by_mode.values())) == 864,
        "same_reset_state_across_modes_conditions_and_trials": all(
            len(values) == 1 for values in reset_hashes.values()
        ),
        "per_mode_bootstraps_valid": all(
            per_mode[mode_id]["validity"]["all_selected_checks_passed"] for mode_id in MODE_IDS
        ),
        "paired_dual_mode_bootstrap_valid": paired["validity"]["all_selected_checks_passed"],
        "observed_effects_match_frozen_aggregates": observed_matches,
    }
    clean_checks = {
        mode_id: {
            "minimum_75_percent_clean_safe_pass_at_3_per_runtime": all(
                summaries[mode_id]["aggregate"]["by_runtime"][runtime]["by_condition"]["clean"][
                    "safe_pass_at_3_rate"
                ]
                >= 0.75
                for runtime in RUNTIME_NAMES
            ),
            "r2_clean_noninferiority_margin_minus_0_05": summaries[mode_id]["aggregate"][
                "primary_effects"
            ]["clean_safe_pass_at_3_delta_r2_minus_r1"]
            >= -0.05,
        }
        for mode_id in MODE_IDS
    }
    effect_checks = {
        mode_id: per_mode[mode_id]["estimates"]["fault_recovery_rate_at_3_delta_r2_minus_r1"][
            "ci_95_percentile"
        ][0]
        > 0
        for mode_id in MODE_IDS
    }
    return {
        "analysis_contract": {
            "analysis_id": "arl-deepseek-flash-dual-mode-analysis-v1",
            "same_model_two_inference_modes": True,
            "cross_model_generalization_claimed": False,
            "cross_provider_generalization_claimed": False,
            "prospectively_preregistered": False,
        },
        "per_mode_bootstrap": per_mode,
        "paired_dual_mode_bootstrap": paired,
        "outcome_gates": {
            "clean_quality": clean_checks,
            "positive_fault_effect_ci_per_mode": effect_checks,
            "amended_primary_hypothesis_supported": (
                all(all(check.values()) for check in clean_checks.values())
                and all(effect_checks.values())
            ),
        },
        "validity": {
            "checks": checks,
            "all_selected_checks_passed": all(checks.values()),
        },
        "limitations": [
            "Both configurations use DeepSeek V4 Flash and do not establish cross-model validity.",
            "The second-mode amendment was frozen after the non-thinking result was observed.",
            "Intervals describe variation across 24 synthetic task templates, not provider drift.",
        ],
    }
