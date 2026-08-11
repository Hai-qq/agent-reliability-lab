"""Scripted 144-episode validity gate for the complete 24-task fixture pack."""

from __future__ import annotations

import platform
from collections import defaultdict
from pathlib import Path
from typing import Any

from arl_mainpack import __version__
from arl_mainpack.specs import MAIN_TASK_SPECS, main_pack_catalog_audit
from arl_mainstudy.contract import CONDITIONS, RUNTIME_NAMES, default_contract
from arl_pilot.evaluator import evaluate_pilot_task, evaluator_mutation_audit
from arl_pilot.experiment import (
    EpisodeCapture,
    aggregate_scripted_episodes,
    execute_scripted_episode,
)

RUN_ID = "arl-main-pack-scripted-preflight-v0.20.0"
EPISODE_PREFIX = "main-pack-preflight"
ENVIRONMENT_SEED = 0

EXPECTED_FAULT_SUCCESS = {
    "postcommit_response_loss": {"r2_reliable"},
    "retryable_invocation_error": {"r1_guarded", "r2_reliable"},
    "input_schema_drift": {"r2_reliable"},
    "output_schema_drift": {"r2_reliable"},
    "compatible_state_conflict": {"r2_reliable"},
    "bounded_compensation": {"r2_reliable"},
}


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
    for spec in MAIN_TASK_SPECS:
        forbidden.update(_payload_markers(spec.visible_task["context"]))
    files = sorted(traces_dir.glob("*.jsonl"))
    findings: dict[str, list[str]] = {}
    for path in files:
        payload = path.read_bytes().lower()
        matches = sorted(marker.decode("utf-8") for marker in forbidden if marker in payload)
        if matches:
            findings[path.name] = matches
    return {
        "trace_count": len(files),
        "forbidden_marker_count": len(forbidden),
        "forbidden_payload_findings": findings,
        "passed": len(files) == 144 and not findings,
    }


def _validity(captures: list[EpisodeCapture], traces_dir: Path) -> dict[str, Any]:
    episodes = [capture.record for capture in captures]
    expected_matrix = {
        (spec.template_id, runtime_name, condition)
        for spec in MAIN_TASK_SPECS
        for runtime_name in RUNTIME_NAMES
        for condition in CONDITIONS
    }
    actual_matrix = {(item["template_id"], item["runtime"], item["condition"]) for item in episodes}
    policy_digests: dict[str, set[str]] = defaultdict(set)
    reset_hashes: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        policy_digests[item["template_id"]].add(item["policy"]["policy_sha256"])
        reset_hashes[item["template_id"]].add(item["initial_state_hash"])

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
            item["execution"]["schema_adaptation_count"] for item in r2_fault
        ),
        "output_schema_normalizations": sum(
            item["execution"]["result_normalization_count"] for item in r2_fault
        ),
        "compatible_conflict_rebases": sum(
            item["execution"]["conflict_rebase_count"] for item in r2_fault
        ),
        "compensation_actions": sum(
            item["execution"]["compensation_action_count"] for item in r2_fault
        ),
    }

    do_nothing: dict[str, bool] = {}
    mutations: dict[str, dict[str, Any]] = {}
    for spec in MAIN_TASK_SPECS:
        r2_capture = next(
            capture
            for capture in captures
            if capture.record["template_id"] == spec.template_id
            and capture.record["runtime"] == "r2_reliable"
            and capture.record["condition"] == "recoverable_fault"
        )
        no_op = evaluate_pilot_task(
            spec,
            "recoverable_fault",
            r2_capture.pre_snapshot,
            r2_capture.pre_snapshot,
            (),
        )
        do_nothing[spec.template_id] = not no_op.safe_success
        mutations[spec.template_id] = evaluator_mutation_audit(
            spec,
            "recoverable_fault",
            r2_capture.pre_snapshot,
            r2_capture.post_snapshot,
            r2_capture.trace_events,
        )

    main_contract_fail_closed = False
    try:
        default_contract().assert_ready("main")
    except RuntimeError:
        main_contract_fail_closed = True
    catalog = main_pack_catalog_audit()
    traces = _trace_payload_audit(traces_dir)
    checks = {
        "exact_144_scripted_episode_matrix": (
            len(episodes) == 144 and actual_matrix == expected_matrix
        ),
        "same_policy_contract_across_conditions_and_runtimes": all(
            len(values) == 1 for values in policy_digests.values()
        ),
        "clean_fault_reset_hash_match": all(len(values) == 1 for values in reset_hashes.values()),
        "all_clean_runs_safe_success": all(
            item["evaluation"]["safe_success"] for item in episodes if item["condition"] == "clean"
        ),
        "fault_outcomes_match_frozen_mechanism_expectations": expected_outcomes,
        "single_registered_fault_difference": fault_isolation,
        "r2_recovers_all_24_faulted_tasks": all(
            item["evaluation"]["safe_success"] for item in r2_fault
        ),
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
        "six_mechanisms_exercised_at_24_task_scale": mechanism_counts
        == {
            "postcommit_confirmations": 4,
            "retryable_invocation_retries": 8,
            "input_schema_adaptations": 4,
            "output_schema_normalizations": 4,
            "compatible_conflict_rebases": 4,
            "compensation_actions": 12,
        },
        "do_nothing_rejected_for_all_24_tasks": all(do_nothing.values()),
        "every_required_state_mutation_detected": all(
            item["passed"] for item in mutations.values()
        ),
        "complete_24_task_catalog_audit": catalog["passed"],
        "model_main_contract_still_fails_closed": main_contract_fail_closed,
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
        "policy_digests": {key: sorted(value) for key, value in sorted(policy_digests.items())},
        "reset_hashes": {key: sorted(value) for key, value in sorted(reset_hashes.items())},
        "do_nothing": do_nothing,
        "evaluator_mutations": mutations,
        "catalog": catalog,
        "trace_payloads": traces,
    }


def run_main_pack_preflight(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    """Run the full scripted fixture gate without pretending it is the model main."""

    if traces_dir.exists():
        raise FileExistsError(f"Refusing to reuse traces directory: {traces_dir}")
    traces_dir.mkdir(parents=True)
    catalog = main_pack_catalog_audit()
    captures = [
        execute_scripted_episode(
            spec=spec,
            runtime_name=runtime_name,
            condition=condition,
            trace_path=traces_dir
            / f"{EPISODE_PREFIX}-{spec.template_id}-{runtime_name}-{condition}.jsonl",
            run_id=RUN_ID,
            episode_prefix=EPISODE_PREFIX,
            catalog_sha256=catalog["catalog_sha256"],
        )
        for spec in MAIN_TASK_SPECS
        for runtime_name in RUNTIME_NAMES
        for condition in CONDITIONS
    ]
    episodes = [capture.record for capture in captures]
    aggregate = aggregate_scripted_episodes(episodes)
    validity = _validity(captures, traces_dir)
    if aggregate["episode_count"] != 144:
        raise AssertionError("Main-pack preflight execution count drifted")
    if not validity["all_selected_checks_passed"]:
        failed = [name for name, passed in validity["checks"].items() if not passed]
        raise AssertionError(f"Main-pack preflight validity failed: {failed}")
    return {
        "metadata": {
            "run_id": RUN_ID,
            "package_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "environment_seed": ENVIRONMENT_SEED,
            "policy": "deterministic reactive oracle; zero model calls",
            "result_scope": "24-task scripted fixture gate; not the 864-episode model main",
        },
        "main_study_contract": default_contract().as_dict(),
        "runnable_task_pack": catalog,
        "scripted_preflight": {
            "formula": "24 tasks × 1 environment seed × 2 conditions × 3 runtimes",
            "episode_count": 144,
            "sampling_trials": 0,
            "model_configurations": 0,
        },
        "aggregate": aggregate,
        "validity": validity,
        "main_readiness": {
            "task_fixture_gate_passed": catalog["passed"],
            "scripted_validity_gate_passed": validity["all_selected_checks_passed"],
            "two_exact_model_bindings_present": False,
            "ready_for_864_episode_confirmatory_main": False,
        },
        "episodes": episodes,
        "limitations": [
            "This is a deterministic oracle fixture gate, not an LLM-agent result.",
            "The expanded tasks use one environment seed and require model-stage task-card review.",
            "The second exact model binding is absent, so the 864-episode main remains blocked.",
            "Bootstrap confidence intervals and mechanism ablations are separate pending gates.",
        ],
    }
