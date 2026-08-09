"""Per-model and jointly paired task bootstrap for the OpenCode Go main."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Any

from arl.core.types import digest_value
from arl_analysis.bootstrap import task_cluster_bootstrap
from arl_mainstudy.contract import RUNTIME_NAMES

MODEL_SLOT_IDS = ("flash", "mimo")
ANALYZED_RUNTIMES = ("r1_guarded", "r2_reliable")
MECHANISM_COUNTERS = (
    "retry_count",
    "confirmation_count",
    "schema_adaptation_count",
    "result_normalization_count",
    "conflict_rebase_count",
    "compensation_action_count",
)


def _nearest_rank(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def _joint_clusters(per_model: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = {
        slot: {item["template_id"]: item for item in result["task_clusters"]}
        for slot, result in per_model.items()
    }
    task_sets = {slot: set(items) for slot, items in rows.items()}
    if (
        set(rows) != set(MODEL_SLOT_IDS)
        or len({frozenset(items) for items in task_sets.values()}) != 1
    ):
        raise ValueError("Two model slots do not contain the same task clusters")
    return [
        {
            "template_id": template_id,
            "models": {slot: rows[slot][template_id]["runtimes"] for slot in MODEL_SLOT_IDS},
        }
        for template_id in sorted(next(iter(task_sets.values())))
    ]


def _metrics(sample: list[dict[str, Any]]) -> dict[str, float]:
    result: dict[str, float] = {}
    fault_deltas: list[float] = []
    clean_deltas: list[float] = []
    for slot in MODEL_SLOT_IDS:
        values: dict[str, float] = {}
        for runtime in ANALYZED_RUNTIMES:
            clean = sum(item["models"][slot][runtime]["clean_safe_pass_at_3"] for item in sample)
            recovered = sum(item["models"][slot][runtime]["recovered_fault"] for item in sample)
            values[f"{runtime}_clean"] = clean / len(sample)
            values[f"{runtime}_recovery"] = recovered / clean if clean else 0.0
        fault_delta = values["r2_reliable_recovery"] - values["r1_guarded_recovery"]
        clean_delta = values["r2_reliable_clean"] - values["r1_guarded_clean"]
        result[f"{slot}_fault_recovery_delta_r2_minus_r1"] = fault_delta
        result[f"{slot}_clean_delta_r2_minus_r1"] = clean_delta
        fault_deltas.append(fault_delta)
        clean_deltas.append(clean_delta)
    result["macro_fault_recovery_delta_r2_minus_r1"] = sum(fault_deltas) / len(fault_deltas)
    result["macro_clean_delta_r2_minus_r1"] = sum(clean_deltas) / len(clean_deltas)
    return result


def joint_model_task_bootstrap(
    per_model: dict[str, dict[str, Any]],
    *,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    if iterations < 1 or seed < 0:
        raise ValueError("Bootstrap iterations must be positive and seed non-negative")
    clusters = _joint_clusters(per_model)
    observed = _metrics(clusters)
    randomizer = random.Random(seed)
    distributions: dict[str, list[float]] = defaultdict(list)
    both_positive = 0
    for _ in range(iterations):
        sample = [clusters[randomizer.randrange(len(clusters))] for _ in clusters]
        metrics = _metrics(sample)
        for name, value in metrics.items():
            distributions[name].append(value)
        if all(metrics[f"{slot}_fault_recovery_delta_r2_minus_r1"] > 0 for slot in MODEL_SLOT_IDS):
            both_positive += 1
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
        "both_models_retained_in_each_cluster": all(
            set(cluster["models"]) == set(MODEL_SLOT_IDS) for cluster in clusters
        ),
        "exact_iteration_count_per_metric": all(
            len(values) == iterations for values in distributions.values()
        ),
        "task_is_the_resampling_unit": True,
    }
    return {
        "analysis_contract": {
            "method": "paired nonparametric task-cluster bootstrap across two models",
            "resampling_unit": "task with both models and all R1/R2 clean/fault trials",
            "iterations": iterations,
            "seed": seed,
            "task_count": len(clusters),
        },
        "task_clusters": clusters,
        "task_cluster_sha256": digest_value(clusters),
        "estimates": estimates,
        "joint_fault_effect": {
            "observed_both_models_greater_than_zero": all(
                observed[f"{slot}_fault_recovery_delta_r2_minus_r1"] > 0 for slot in MODEL_SLOT_IDS
            ),
            "bootstrap_probability_both_models_greater_than_zero": both_positive / iterations,
        },
        "validity": {"checks": checks, "all_selected_checks_passed": all(checks.values())},
    }


def analyze_openstudy(
    summary: dict[str, Any],
    *,
    iterations: int = 10_000,
    seed: int = 20_260_809,
) -> dict[str, Any]:
    episodes = summary.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("OpenCode Go full summary is missing episode records")
    episodes_by_model = {
        slot: [episode for episode in episodes if episode.get("model_slot") == slot]
        for slot in MODEL_SLOT_IDS
    }
    per_model = {
        slot: task_cluster_bootstrap(selected, iterations=iterations, seed=seed)
        for slot, selected in episodes_by_model.items()
    }
    joint = joint_model_task_bootstrap(per_model, iterations=iterations, seed=seed)
    observed_matches = all(
        math.isclose(
            per_model[slot]["estimates"]["fault_recovery_rate_at_3_delta_r2_minus_r1"]["observed"],
            summary["aggregate"]["by_model"][slot]["primary_effects"][
                "fault_recovery_rate_at_3_delta_r2_minus_r1"
            ],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        for slot in MODEL_SLOT_IDS
    )
    descriptors = {
        episode["template_id"]: (episode["domain"], episode["fault_family"]) for episode in episodes
    }
    reset_hashes: dict[str, set[str]] = defaultdict(set)
    for episode in episodes:
        reset_hashes[episode["template_id"]].add(episode["initial_state_hash"])
    mechanisms: dict[str, Any] = {}
    failure_codes: dict[str, Any] = {}
    for slot in MODEL_SLOT_IDS:
        mechanisms[slot] = {}
        failure_codes[slot] = {}
        for runtime in RUNTIME_NAMES:
            selected = [
                episode
                for episode in episodes_by_model[slot]
                if episode["runtime"] == runtime and episode["condition"] == "recoverable_fault"
            ]
            mechanisms[slot][runtime] = {
                counter: sum(episode["execution"][counter] for episode in selected)
                for counter in MECHANISM_COUNTERS
            }
            failure_codes[slot][runtime] = dict(
                sorted(
                    Counter(
                        episode["execution"]["failure_code"] or "none" for episode in selected
                    ).items()
                )
            )
    clean_quality = {
        slot: {
            "minimum_75_percent_clean_safe_pass_at_3_per_runtime": all(
                summary["aggregate"]["by_model"][slot]["by_runtime"][runtime]["by_condition"][
                    "clean"
                ]["safe_pass_at_3_rate"]
                >= 0.75
                for runtime in RUNTIME_NAMES
            ),
            "r2_clean_noninferiority_margin_minus_0_05": summary["aggregate"]["by_model"][slot][
                "primary_effects"
            ]["clean_safe_pass_at_3_delta_r2_minus_r1"]
            >= -0.05,
        }
        for slot in MODEL_SLOT_IDS
    }
    positive_ci = {
        slot: per_model[slot]["estimates"]["fault_recovery_rate_at_3_delta_r2_minus_r1"][
            "ci_95_percentile"
        ][0]
        > 0
        for slot in MODEL_SLOT_IDS
    }
    checks = {
        "input_infrastructure_valid": summary.get("validity", {}).get("all_selected_checks_passed")
        is True,
        "exact_432_episodes_per_model": all(
            len(episodes_by_model[slot]) == 432 for slot in MODEL_SLOT_IDS
        ),
        "exact_864_episode_input": len(episodes) == 864,
        "exact_24_task_catalog": len(descriptors) == 24,
        "three_balanced_domains": Counter(value[0] for value in descriptors.values())
        == {"workspace": 8, "retail": 8, "travel": 8},
        "six_balanced_fault_families": set(
            Counter(value[1] for value in descriptors.values()).values()
        )
        == {4},
        "same_reset_state_across_models": all(len(values) == 1 for values in reset_hashes.values()),
        "per_model_bootstrap_valid": all(
            per_model[slot]["validity"]["all_selected_checks_passed"] for slot in MODEL_SLOT_IDS
        ),
        "joint_bootstrap_valid": joint["validity"]["all_selected_checks_passed"],
        "observed_effects_match_frozen_aggregate": observed_matches,
    }
    return {
        "analysis_contract": {
            "analysis_id": "arl-opencode-go-two-model-analysis-v1",
            "cross_model_consistency": True,
            "cross_provider_generalization": False,
            "safe_pass_at_3": "all three trials must be SafeSuccess",
        },
        "per_model_bootstrap": per_model,
        "joint_model_bootstrap": joint,
        "recoverable_fault_mechanism_counts": mechanisms,
        "recoverable_fault_failure_codes": failure_codes,
        "outcome_gates": {
            "clean_quality": clean_quality,
            "positive_fault_effect_ci_per_model": positive_ci,
            "primary_hypothesis_supported": all(
                all(values.values()) for values in clean_quality.values()
            )
            and all(positive_ci.values()),
        },
        "validity": {"checks": checks, "all_selected_checks_passed": all(checks.values())},
        "limitations": [
            "Both models share one OpenCode Go gateway, so provider effects are not identified.",
            "The 24 task templates are synthetic and fault-family subgroups contain four tasks.",
            "Bootstrap proportions are descriptive and are not p-values.",
        ],
    }
