"""Zero-model 432-episode validity gate for the v0.30 replication catalog."""

from __future__ import annotations

import platform
from collections import defaultdict
from pathlib import Path
from typing import Any

from arl_mainpack.experiment import EXPECTED_FAULT_SUCCESS
from arl_mainstudy.contract import CONDITIONS, RUNTIME_NAMES
from arl_pilot.evaluator import evaluate_pilot_task, evaluator_mutation_audit
from arl_pilot.experiment import (
    EpisodeCapture,
    aggregate_scripted_episodes,
    execute_scripted_episode,
)

from . import __version__
from .contract import study_contract, transition_record
from .specs import ENVIRONMENT_SEEDS, all_seeded_specs, replication_catalog_audit

RUN_ID = "arl-replication-v30-scripted-preflight-v0.30.0"
EPISODE_PREFIX = "replication-v30-preflight"


def _payload_markers(value: Any) -> set[bytes]:
    if isinstance(value, dict):
        return {marker for item in value.values() for marker in _payload_markers(item)}
    if isinstance(value, (list, tuple)):
        return {marker for item in value for marker in _payload_markers(item)}
    if isinstance(value, str) and len(value) >= 7:
        return {value.lower().encode("utf-8")}
    return set()


def _trace_payload_audit(traces_dir: Path) -> dict[str, Any]:
    forbidden = {b'"arguments"', b'"visible_task"'}
    for spec in all_seeded_specs():
        forbidden.update(_payload_markers(spec.visible_task["context"]))
        forbidden.update(_payload_markers(spec.visible_task["user_request"]))
    files = sorted(traces_dir.glob("*.jsonl"))
    findings: dict[str, list[str]] = {}
    for path in files:
        raw = path.read_bytes().lower()
        matches = sorted(marker.decode("utf-8") for marker in forbidden if marker in raw)
        if matches:
            findings[path.name] = matches
    return {
        "trace_count": len(files),
        "forbidden_marker_count": len(forbidden),
        "forbidden_payload_findings": findings,
        "passed": len(files) == 432 and not findings,
    }


def _validity(captures: list[EpisodeCapture], traces_dir: Path) -> dict[str, Any]:
    episodes = [capture.record for capture in captures]
    specs = all_seeded_specs()
    expected_matrix = {
        (spec.template_id, spec.environment_seed, runtime, condition)
        for spec in specs
        for runtime in RUNTIME_NAMES
        for condition in CONDITIONS
    }
    actual_matrix = {
        (
            item["template_id"],
            item["environment_seed"],
            item["runtime"],
            item["condition"],
        )
        for item in episodes
    }
    policy_digests: dict[tuple[str, int], set[str]] = defaultdict(set)
    reset_hashes: dict[tuple[str, int], set[str]] = defaultdict(set)
    reset_hashes_by_template: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        key = (item["template_id"], item["environment_seed"])
        policy_digests[key].add(item["policy"]["policy_sha256"])
        reset_hashes[key].add(item["initial_state_hash"])
        reset_hashes_by_template[item["template_id"]].add(item["initial_state_hash"])

    expected_outcomes = all(
        item["evaluation"]["safe_success"]
        == (
            item["condition"] == "clean"
            or item["runtime"] in EXPECTED_FAULT_SUCCESS[item["fault_family"]]
        )
        for item in episodes
    )
    fault_isolation = all(
        (
            not item["observed_fault_ids"]
            if item["condition"] == "clean"
            else item["observed_fault_ids"] == [item["expected_fault_id"]]
        )
        for item in episodes
    )
    r2_fault = [
        item
        for item in episodes
        if item["runtime"] == "r2_reliable" and item["condition"] == "recoverable_fault"
    ]
    r0 = [item for item in episodes if item["runtime"] == "r0_raw"]
    mechanism_counts = {
        "postcommit_confirmations": sum(
            item["execution"]["confirmation_count"]
            for item in r2_fault
            if item["fault_family"] == "postcommit_response_loss"
        ),
        "retryable_invocation_retries": sum(
            item["execution"]["retry_count"]
            for item in episodes
            if item["condition"] == "recoverable_fault"
            and item["fault_family"] == "retryable_invocation_error"
        ),
        "input_schema_adaptations": sum(
            item["execution"]["schema_adaptation_count"]
            for item in r2_fault
            if item["fault_family"] == "input_schema_drift"
        ),
        "output_schema_normalizations": sum(
            item["execution"]["result_normalization_count"]
            for item in r2_fault
            if item["fault_family"] == "output_schema_drift"
        ),
        "compatible_conflict_rebases": sum(
            item["execution"]["conflict_rebase_count"]
            for item in r2_fault
            if item["fault_family"] == "compatible_state_conflict"
        ),
        "compensation_actions": sum(
            item["execution"]["compensation_action_count"]
            for item in r2_fault
            if item["fault_family"] == "bounded_compensation"
        ),
    }

    do_nothing: dict[str, bool] = {}
    mutations: dict[str, dict[str, Any]] = {}
    for spec in specs:
        capture = next(
            item
            for item in captures
            if item.record["template_id"] == spec.template_id
            and item.record["environment_seed"] == spec.environment_seed
            and item.record["runtime"] == "r2_reliable"
            and item.record["condition"] == "recoverable_fault"
        )
        no_op = evaluate_pilot_task(
            spec,
            "recoverable_fault",
            capture.pre_snapshot,
            capture.pre_snapshot,
            (),
        )
        key = f"{spec.template_id}/seed-{spec.environment_seed}"
        do_nothing[key] = not no_op.safe_success
        mutations[key] = evaluator_mutation_audit(
            spec,
            "recoverable_fault",
            capture.pre_snapshot,
            capture.post_snapshot,
            capture.trace_events,
        )

    catalog = replication_catalog_audit()
    traces = _trace_payload_audit(traces_dir)
    checks = {
        "exact_432_scripted_episode_matrix": len(episodes) == 432
        and actual_matrix == expected_matrix,
        "catalog_frozen_and_balanced": catalog["passed"],
        "same_oracle_policy_across_each_seeded_pair": all(
            len(values) == 1 for values in policy_digests.values()
        ),
        "clean_fault_reset_hash_match_within_seed": all(
            len(values) == 1 for values in reset_hashes.values()
        ),
        "three_distinct_reset_states_per_template": all(
            len(values) == 3 for values in reset_hashes_by_template.values()
        ),
        "all_clean_runs_safe_success": all(
            item["evaluation"]["safe_success"] for item in episodes if item["condition"] == "clean"
        ),
        "fault_outcomes_match_mechanism_expectations": expected_outcomes,
        "single_registered_fault_difference": fault_isolation,
        "r2_recovers_all_72_faulted_task_seed_cells": len(r2_fault) == 72
        and all(item["evaluation"]["safe_success"] for item in r2_fault),
        "r0_owns_no_reliability_mechanisms": all(
            sum(
                item["execution"][name]
                for name in (
                    "retry_count",
                    "confirmation_count",
                    "schema_adaptation_count",
                    "result_normalization_count",
                    "conflict_rebase_count",
                    "compensation_action_count",
                )
            )
            == 0
            for item in r0
        ),
        "six_mechanisms_exercised_at_three_seed_scale": mechanism_counts
        == {
            "postcommit_confirmations": 12,
            "retryable_invocation_retries": 24,
            "input_schema_adaptations": 12,
            "output_schema_normalizations": 12,
            "compatible_conflict_rebases": 12,
            "compensation_actions": 36,
        },
        "do_nothing_rejected_for_all_72_cells": len(do_nothing) == 72 and all(do_nothing.values()),
        "every_required_state_mutation_detected": len(mutations) == 72
        and all(item["passed"] for item in mutations.values()),
        "two_models_bound_for_full_three_seed_stage": _contract_ready(),
        "zero_model_and_network_calls": all(
            item["policy"]["model_calls"] == 0 and item["external_network_calls"] == 0
            for item in episodes
        ),
        "digest_only_traces": traces["passed"],
    }
    return {
        "checks": checks,
        "all_selected_checks_passed": all(checks.values()),
        "mechanism_counts": mechanism_counts,
        "policy_digests": {
            f"{template}/seed-{seed}": sorted(values)
            for (template, seed), values in sorted(policy_digests.items())
        },
        "reset_hashes": {
            f"{template}/seed-{seed}": sorted(values)
            for (template, seed), values in sorted(reset_hashes.items())
        },
        "do_nothing": do_nothing,
        "evaluator_mutations": mutations,
        "trace_payloads": traces,
    }


def _contract_ready() -> bool:
    try:
        study_contract().assert_ready("full_three_seed")
    except RuntimeError:
        return False
    return True


def run_replication_preflight(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    if traces_dir.exists():
        raise FileExistsError(f"Refusing to reuse traces directory: {traces_dir}")
    traces_dir.mkdir(parents=True)
    catalog = replication_catalog_audit()
    captures = [
        execute_scripted_episode(
            spec=spec,
            runtime_name=runtime,
            condition=condition,
            seed=spec.environment_seed,
            trace_path=traces_dir
            / (
                f"{EPISODE_PREFIX}-s{spec.environment_seed}-{spec.template_id}-"
                f"{runtime}-{condition}.jsonl"
            ),
            run_id=RUN_ID,
            episode_prefix=f"{EPISODE_PREFIX}-s{spec.environment_seed}",
            catalog_sha256=catalog["catalog_sha256"],
        )
        for spec in all_seeded_specs()
        for runtime in RUNTIME_NAMES
        for condition in CONDITIONS
    ]
    episodes = [capture.record for capture in captures]
    aggregate = aggregate_scripted_episodes(episodes)
    validity = _validity(captures, traces_dir)
    if aggregate["episode_count"] != 432:
        raise AssertionError("Replication preflight episode count drifted")
    if not validity["all_selected_checks_passed"]:
        failed = [name for name, passed in validity["checks"].items() if not passed]
        raise AssertionError(f"Replication preflight validity failed: {failed}")
    return {
        "metadata": {
            "run_id": RUN_ID,
            "package_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "provider_content_persisted": False,
            "result_scope": "432-episode zero-model replication task and mechanism gate",
        },
        "transition": transition_record(),
        "main_study_contract": study_contract().as_dict(),
        "replication_catalog": catalog,
        "scripted_preflight": {
            "formula": "24 tasks × 3 seeds × 2 conditions × 3 runtimes",
            "episode_count": 432,
            "environment_seeds": list(ENVIRONMENT_SEEDS),
            "model_calls": 0,
        },
        "aggregate": aggregate,
        "validity": validity,
        "readiness": {
            "task_fixture_gate_passed": catalog["passed"],
            "scripted_validity_gate_passed": validity["all_selected_checks_passed"],
            "ready_for_provider_probe": validity["all_selected_checks_passed"],
        },
        "episodes": episodes,
    }
