"""Task-cluster bootstrap retaining all three v0.29 seeds inside each cluster."""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from typing import Any

from arl.core.types import digest_value
from arl_mainstudy.contract import RUNTIME_NAMES

from .experiment import MODEL_SLOT_IDS
from .specs import ENVIRONMENT_SEEDS, HOLDOUT_TEMPLATES

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


def _safe_pass_at_3(selected: list[dict[str, Any]]) -> bool:
    return len(selected) == 3 and all(item["evaluation"]["safe_success"] for item in selected)


def _clusters(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for declaration in HOLDOUT_TEMPLATES:
        models: dict[str, Any] = {}
        for slot in MODEL_SLOT_IDS:
            seeds: dict[str, Any] = {}
            for seed in ENVIRONMENT_SEEDS:
                runtimes: dict[str, Any] = {}
                for runtime in ANALYZED_RUNTIMES:
                    clean = _safe_pass_at_3(
                        [
                            item
                            for item in episodes
                            if item["model_slot"] == slot
                            and item["template_id"] == declaration.template_id
                            and item["environment_seed"] == seed
                            and item["runtime"] == runtime
                            and item["condition"] == "clean"
                        ]
                    )
                    fault = _safe_pass_at_3(
                        [
                            item
                            for item in episodes
                            if item["model_slot"] == slot
                            and item["template_id"] == declaration.template_id
                            and item["environment_seed"] == seed
                            and item["runtime"] == runtime
                            and item["condition"] == "recoverable_fault"
                        ]
                    )
                    runtimes[runtime] = {
                        "clean_safe_pass_at_3": clean,
                        "fault_safe_pass_at_3": fault,
                        "recovered_fault": clean and fault,
                    }
                seeds[str(seed)] = runtimes
            models[slot] = seeds
        result.append(
            {
                "template_id": declaration.template_id,
                "domain": declaration.domain,
                "fault_family": declaration.fault_family,
                "models": models,
            }
        )
    return result


def _metrics(sample: list[dict[str, Any]]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    model_fault_deltas: list[float] = []
    model_clean_deltas: list[float] = []
    for slot in MODEL_SLOT_IDS:
        runtime_values: dict[str, dict[str, float]] = {}
        for runtime in ANALYZED_RUNTIMES:
            clean = sum(
                item["models"][slot][str(seed)][runtime]["clean_safe_pass_at_3"]
                for item in sample
                for seed in ENVIRONMENT_SEEDS
            )
            recovered = sum(
                item["models"][slot][str(seed)][runtime]["recovered_fault"]
                for item in sample
                for seed in ENVIRONMENT_SEEDS
            )
            runtime_values[runtime] = {
                "clean": clean / (len(sample) * len(ENVIRONMENT_SEEDS)),
                "recovery": recovered / clean if clean else 0.0,
            }
        fault_delta = (
            runtime_values["r2_reliable"]["recovery"] - runtime_values["r1_guarded"]["recovery"]
        )
        clean_delta = runtime_values["r2_reliable"]["clean"] - runtime_values["r1_guarded"]["clean"]
        metrics[f"{slot}_fault_recovery_delta_r2_minus_r1"] = fault_delta
        metrics[f"{slot}_clean_delta_r2_minus_r1"] = clean_delta
        model_fault_deltas.append(fault_delta)
        model_clean_deltas.append(clean_delta)
        for seed in ENVIRONMENT_SEEDS:
            seed_values = {}
            for runtime in ANALYZED_RUNTIMES:
                clean_seed = sum(
                    item["models"][slot][str(seed)][runtime]["clean_safe_pass_at_3"]
                    for item in sample
                )
                recovered_seed = sum(
                    item["models"][slot][str(seed)][runtime]["recovered_fault"] for item in sample
                )
                seed_values[runtime] = {
                    "clean": clean_seed / len(sample),
                    "recovery": recovered_seed / clean_seed if clean_seed else 0.0,
                }
            metrics[f"{slot}_seed_{seed}_fault_recovery_delta_r2_minus_r1"] = (
                seed_values["r2_reliable"]["recovery"] - seed_values["r1_guarded"]["recovery"]
            )
            metrics[f"{slot}_seed_{seed}_clean_delta_r2_minus_r1"] = (
                seed_values["r2_reliable"]["clean"] - seed_values["r1_guarded"]["clean"]
            )
    metrics["macro_fault_recovery_delta_r2_minus_r1"] = sum(model_fault_deltas) / len(
        model_fault_deltas
    )
    metrics["macro_clean_delta_r2_minus_r1"] = sum(model_clean_deltas) / len(model_clean_deltas)
    return metrics


def task_cluster_bootstrap(
    clusters: list[dict[str, Any]], *, iterations: int, seed: int
) -> dict[str, Any]:
    if len(clusters) != 24 or iterations < 1 or seed < 0:
        raise ValueError("v0.29 bootstrap dimensions are invalid")
    observed = _metrics(clusters)
    distributions: dict[str, list[float]] = defaultdict(list)
    both_models_positive = 0
    all_model_seed_effects_positive = 0
    randomizer = random.Random(seed)
    for _ in range(iterations):
        sample = [clusters[randomizer.randrange(len(clusters))] for _ in clusters]
        metrics = _metrics(sample)
        for name, value in metrics.items():
            distributions[name].append(value)
        if all(metrics[f"{slot}_fault_recovery_delta_r2_minus_r1"] > 0 for slot in MODEL_SLOT_IDS):
            both_models_positive += 1
        if all(
            metrics[f"{slot}_seed_{environment_seed}_fault_recovery_delta_r2_minus_r1"] > 0
            for slot in MODEL_SLOT_IDS
            for environment_seed in ENVIRONMENT_SEEDS
        ):
            all_model_seed_effects_positive += 1
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
        "exact_24_task_clusters": len(clusters) == 24,
        "all_three_seeds_retained_inside_each_cluster": all(
            all(
                set(item["models"][slot]) == {str(seed) for seed in ENVIRONMENT_SEEDS}
                for slot in MODEL_SLOT_IDS
            )
            for item in clusters
        ),
        "both_models_retained_inside_each_cluster": all(
            set(item["models"]) == set(MODEL_SLOT_IDS) for item in clusters
        ),
        "exact_iteration_count_per_metric": all(
            len(values) == iterations for values in distributions.values()
        ),
        "task_template_is_the_resampling_unit": True,
    }
    return {
        "analysis_contract": {
            "method": "paired nonparametric task-template cluster bootstrap",
            "resampling_unit": "task template retaining both models, all seeds, and R1/R2 pairs",
            "iterations": iterations,
            "seed": seed,
            "task_count": len(clusters),
            "environment_seed_count": len(ENVIRONMENT_SEEDS),
        },
        "task_clusters": clusters,
        "task_cluster_sha256": digest_value(clusters),
        "estimates": estimates,
        "joint_fault_effect": {
            "observed_both_models_greater_than_zero": all(
                observed[f"{slot}_fault_recovery_delta_r2_minus_r1"] > 0 for slot in MODEL_SLOT_IDS
            ),
            "observed_all_model_seed_effects_greater_than_zero": all(
                observed[f"{slot}_seed_{environment_seed}_fault_recovery_delta_r2_minus_r1"] > 0
                for slot in MODEL_SLOT_IDS
                for environment_seed in ENVIRONMENT_SEEDS
            ),
            "bootstrap_probability_both_models_greater_than_zero": (
                both_models_positive / iterations
            ),
            "bootstrap_probability_all_model_seed_effects_greater_than_zero": (
                all_model_seed_effects_positive / iterations
            ),
        },
        "validity": {"checks": checks, "all_selected_checks_passed": all(checks.values())},
    }


def analyze_study(
    summary: dict[str, Any],
    *,
    iterations: int = 10_000,
    seed: int = 20_260_809,
    confirmatory: bool = True,
) -> dict[str, Any]:
    if summary.get("validity", {}).get("all_selected_checks_passed") is not True:
        raise RuntimeError("v0.29 analysis requires infrastructure-valid input")
    ready = summary.get("readiness", {}).get("ready_for_replication_analysis") is True
    if confirmatory and not ready:
        raise RuntimeError("v0.29 confirmatory analysis requires the frozen readiness gate")
    episodes = summary.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("v0.29 full summary is missing episode records")
    clusters = _clusters(episodes)
    bootstrap = task_cluster_bootstrap(clusters, iterations=iterations, seed=seed)
    descriptors = {item["template_id"]: (item["domain"], item["fault_family"]) for item in episodes}
    reset_hashes: dict[tuple[str, int], set[str]] = defaultdict(set)
    reset_by_template: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        reset_hashes[(item["template_id"], item["environment_seed"])].add(
            item["initial_state_hash"]
        )
        reset_by_template[item["template_id"]].add(item["initial_state_hash"])
    mechanisms: dict[str, Any] = {}
    failures: dict[str, Any] = {}
    for slot in MODEL_SLOT_IDS:
        mechanisms[slot] = {}
        failures[slot] = {}
        for runtime in RUNTIME_NAMES:
            mechanisms[slot][runtime] = {}
            failures[slot][runtime] = {}
            for environment_seed in ENVIRONMENT_SEEDS:
                selected = [
                    item
                    for item in episodes
                    if item["model_slot"] == slot
                    and item["runtime"] == runtime
                    and item["condition"] == "recoverable_fault"
                    and item["environment_seed"] == environment_seed
                ]
                mechanisms[slot][runtime][str(environment_seed)] = {
                    counter: sum(item["execution"][counter] for item in selected)
                    for counter in MECHANISM_COUNTERS
                }
                failures[slot][runtime][str(environment_seed)] = dict(
                    sorted(
                        Counter(
                            item["execution"]["failure_code"] or "none" for item in selected
                        ).items()
                    )
                )
    estimates = bootstrap["estimates"]
    positive_ci = {
        slot: estimates[f"{slot}_fault_recovery_delta_r2_minus_r1"]["ci_95_percentile"][0] > 0
        for slot in MODEL_SLOT_IDS
    }
    observed_each_seed = {
        slot: {
            str(environment_seed): estimates[
                f"{slot}_seed_{environment_seed}_fault_recovery_delta_r2_minus_r1"
            ]["observed"]
            > 0
            for environment_seed in ENVIRONMENT_SEEDS
        }
        for slot in MODEL_SLOT_IDS
    }
    observed_matches = all(
        math.isclose(
            estimates[f"{slot}_fault_recovery_delta_r2_minus_r1"]["observed"],
            summary["aggregate"]["by_model"][slot]["primary_effects"][
                "fault_recovery_rate_at_3_delta_r2_minus_r1"
            ],
            rel_tol=0.0,
            abs_tol=1e-12,
        )
        for slot in MODEL_SLOT_IDS
    )
    checks = {
        "input_infrastructure_valid": True,
        "input_readiness_gate_recorded": isinstance(ready, bool),
        "confirmatory_mode_requires_readiness": ready or not confirmatory,
        "exact_1296_episodes_per_model": all(
            sum(item["model_slot"] == slot for item in episodes) == 1296 for slot in MODEL_SLOT_IDS
        ),
        "exact_2592_episode_input": len(episodes) == 2592,
        "exact_24_holdout_tasks": len(descriptors) == 24,
        "three_balanced_domains": Counter(value[0] for value in descriptors.values())
        == {"workspace": 8, "retail": 8, "travel": 8},
        "six_balanced_fault_families": set(
            Counter(value[1] for value in descriptors.values()).values()
        )
        == {4},
        "same_reset_state_within_task_seed_cells": all(
            len(values) == 1 for values in reset_hashes.values()
        ),
        "three_distinct_reset_states_per_task": all(
            len(values) == 3 for values in reset_by_template.values()
        ),
        "task_cluster_bootstrap_valid": bootstrap["validity"]["all_selected_checks_passed"],
        "observed_effects_match_frozen_aggregate": observed_matches,
    }
    primary_supported = (
        confirmatory
        and ready
        and all(positive_ci.values())
        and all(all(values.values()) for values in observed_each_seed.values())
        and all(checks.values())
    )
    return {
        "analysis_contract": {
            "analysis_id": "arl-opencode-go-v29-holdout-analysis-v1",
            "analysis_mode": ("prospective_holdout_replication" if confirmatory else "exploratory"),
            "confirmatory_claim_allowed": confirmatory and ready and all(checks.values()),
            "v028_confirmatory_failure_superseded": False,
            "cross_model_comparison_available": True,
            "cross_provider_generalization": False,
            "safe_pass_at_3": "all three trials within a task-seed cell must be SafeSuccess",
        },
        "bootstrap": bootstrap,
        "recoverable_fault_mechanism_counts": mechanisms,
        "recoverable_fault_failure_codes": failures,
        "outcome_gates": {
            "frozen_model_quality_readiness": summary.get("readiness", {}).get(
                "model_quality_checks"
            ),
            "positive_fault_effect_ci_per_model": positive_ci,
            "positive_observed_fault_effect_per_model_and_seed": observed_each_seed,
            "primary_hypothesis_supported": primary_supported,
        },
        "validity": {"checks": checks, "all_selected_checks_passed": all(checks.values())},
        "limitations": [
            "This prospective holdout was designed after v0.28 outcomes were observed.",
            "The six runtime mechanism archetypes and public tool schemas are reused.",
            "Both models share OpenCode Go, so provider effects are not identified.",
            "Bootstrap proportions are descriptive and are not p-values.",
        ],
    }
