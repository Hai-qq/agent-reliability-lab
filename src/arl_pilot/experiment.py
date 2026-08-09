"""Forty-eight-episode scripted preflight for the future 144-episode model pilot."""

from __future__ import annotations

import hashlib
import platform
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arl.core.types import SnapshotRef, digest_value
from arl.runtime.journal import EventJournal
from arl_mainstudy.contract import CONDITIONS, RUNTIME_NAMES, default_contract
from arl_mainstudy.protocol import AgentFeedback
from arl_pilot import __version__
from arl_pilot.agent import PilotOracleAgent
from arl_pilot.env import PilotEnvironment
from arl_pilot.evaluator import evaluate_pilot_task, evaluator_mutation_audit
from arl_pilot.runtime import PilotRuntime
from arl_pilot.specs import PILOT_TASK_SPECS, PilotTaskSpec, pilot_catalog_audit

RUN_ID = "arl-pilot-scripted-preflight-v0.17.0"
ENVIRONMENT_SEED = 0


@dataclass(frozen=True)
class EpisodeCapture:
    record: dict[str, Any]
    pre_snapshot: SnapshotRef
    post_snapshot: SnapshotRef
    trace_events: tuple[dict[str, Any], ...]


def _episode_id(
    template_id: str,
    runtime_name: str,
    condition: str,
    *,
    prefix: str = "pilot-preflight",
) -> str:
    return f"{prefix}-{template_id}-{runtime_name}-{condition}"


def execute_scripted_episode(
    *,
    spec: PilotTaskSpec,
    runtime_name: str,
    condition: str,
    seed: int = ENVIRONMENT_SEED,
    trace_path: Path | None,
    run_id: str = RUN_ID,
    episode_prefix: str = "pilot-preflight",
    catalog_sha256: str | None = None,
) -> EpisodeCapture:
    episode_id = _episode_id(
        spec.template_id,
        runtime_name,
        condition,
        prefix=episode_prefix,
    )
    environment = PilotEnvironment(spec, condition)
    try:
        observation = environment.reset(spec.task_id, seed)
        pre_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=run_id,
            episode_id=episode_id,
            task_id=spec.task_id,
            seed=seed,
            path=trace_path,
        )
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="harness",
            event_type="episode_started",
            state_hash_before=initial_hash,
            state_hash_after=initial_hash,
            input_digest=digest_value(
                {
                    "main_contract_sha256": default_contract().sha256,
                    "task_catalog_sha256": (
                        catalog_sha256 or pilot_catalog_audit()["catalog_sha256"]
                    ),
                    "template_id": spec.template_id,
                    "runtime": runtime_name,
                    "condition": condition,
                    "observation": observation.as_dict(),
                }
            ),
        )
        agent = PilotOracleAgent(spec)
        agent.reset(observation)
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="agent",
            event_type="policy_initialized",
            state_hash_before=initial_hash,
            state_hash_after=initial_hash,
            input_digest=agent.policy_digest,
        )
        runtime = PilotRuntime(runtime_name)
        feedback: AgentFeedback | None = None
        action_reports: list[dict[str, Any]] = []
        failure_code: str | None = None
        action_ordinal = 0

        while action_ordinal < 32:
            semantic_action = agent.next_action(feedback)
            if semantic_action is None:
                if action_ordinal < agent.action_count:
                    failure_code = agent.terminal_reason or "policy_stopped_early"
                break
            action_ordinal += 1
            state_hash = environment.state_hash()
            journal.append(
                timestamp_logical=environment.logical_time,
                actor="agent",
                event_type="agent_action_selected",
                state_hash_before=state_hash,
                state_hash_after=state_hash,
                input_digest=digest_value(semantic_action.as_dict()),
                tool_name=semantic_action.tool_name,
                schema_version=semantic_action.schema_version,
            )
            report, feedback = runtime.execute(
                environment,
                semantic_action,
                journal,
                episode_key=episode_id,
                action_ordinal=action_ordinal,
            )
            action_reports.append(report.as_dict())
            if not feedback.accepted:
                failure_code = feedback.error_code
                break
        else:  # pragma: no cover - plans contain at most four policy actions
            failure_code = "agent_step_budget_exhausted"

        completed_plan = failure_code is None and action_ordinal == agent.action_count
        post_snapshot = environment.snapshot()
        evaluation = evaluate_pilot_task(
            spec,
            condition,
            pre_snapshot,
            post_snapshot,
            journal.as_dicts(),
        )
        final_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="evaluator",
            event_type="evaluation_completed",
            state_hash_before=final_hash,
            state_hash_after=final_hash,
            output_digest=digest_value(evaluation.as_dict()),
        )
        observed_fault_ids = sorted(
            {event.fault_id for event in journal.events if event.fault_id is not None}
        )
        record = {
            "episode_id": episode_id,
            "template_id": spec.template_id,
            "task_id": spec.task_id,
            "domain": spec.domain,
            "fault_family": spec.fault_family,
            "environment_seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "expected_fault_id": spec.fault_id if condition == "recoverable_fault" else None,
            "observed_fault_ids": observed_fault_ids,
            "policy": {
                "policy_id": agent.policy_id,
                "policy_sha256": agent.policy_digest,
                "planned_action_count": agent.action_count,
                "emitted_action_count": action_ordinal,
                "terminal_reason": agent.terminal_reason,
                "model_calls": agent.model_calls,
            },
            "execution": {
                "completed_plan": completed_plan,
                "failure_code": failure_code,
                "tool_attempts": sum(item["tool_attempts"] for item in action_reports),
                "retry_count": sum(item["retry_count"] for item in action_reports),
                "confirmation_count": sum(item["confirmation_count"] for item in action_reports),
                "schema_adaptation_count": sum(
                    item["schema_adaptation_count"] for item in action_reports
                ),
                "result_normalization_count": sum(
                    item["result_normalization_count"] for item in action_reports
                ),
                "conflict_rebase_count": sum(
                    item["conflict_rebase_count"] for item in action_reports
                ),
                "compensation_action_count": sum(
                    item["compensation_action_count"] for item in action_reports
                ),
                "result_contract_violation_count": sum(
                    item["result_contract_violation_count"] for item in action_reports
                ),
                "actions": action_reports,
            },
            "evaluation": evaluation.as_dict(),
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "trace_file": trace_path.name if trace_path is not None else None,
            "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
            "trace_event_count": len(journal.events),
            "external_network_calls": 0,
        }
        return EpisodeCapture(
            record=record,
            pre_snapshot=pre_snapshot,
            post_snapshot=post_snapshot,
            trace_events=tuple(journal.as_dicts()),
        )
    finally:
        environment.close()


def run_episode(
    *,
    spec: PilotTaskSpec,
    runtime_name: str,
    condition: str,
    seed: int = ENVIRONMENT_SEED,
    trace_path: Path | None,
) -> dict[str, Any]:
    """Run one public episode record without returning raw state snapshots."""

    return execute_scripted_episode(
        spec=spec,
        runtime_name=runtime_name,
        condition=condition,
        seed=seed,
        trace_path=trace_path,
    ).record


def aggregate_scripted_episodes(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    by_runtime: dict[str, Any] = {}
    for runtime_name in RUNTIME_NAMES:
        by_condition: dict[str, Any] = {}
        for condition in CONDITIONS:
            selected = [
                item
                for item in episodes
                if item["runtime"] == runtime_name and item["condition"] == condition
            ]
            by_condition[condition] = {
                "episodes": len(selected),
                "task_successes": sum(item["evaluation"]["task_success"] for item in selected),
                "safe_successes": sum(item["evaluation"]["safe_success"] for item in selected),
                "completed_plans": sum(item["execution"]["completed_plan"] for item in selected),
                "retry_count": sum(item["execution"]["retry_count"] for item in selected),
                "confirmation_count": sum(
                    item["execution"]["confirmation_count"] for item in selected
                ),
                "schema_adaptation_count": sum(
                    item["execution"]["schema_adaptation_count"] for item in selected
                ),
                "result_normalization_count": sum(
                    item["execution"]["result_normalization_count"] for item in selected
                ),
                "conflict_rebase_count": sum(
                    item["execution"]["conflict_rebase_count"] for item in selected
                ),
                "compensation_action_count": sum(
                    item["execution"]["compensation_action_count"] for item in selected
                ),
            }
        clean_success = {
            item["template_id"]
            for item in episodes
            if item["runtime"] == runtime_name
            and item["condition"] == "clean"
            and item["evaluation"]["safe_success"]
        }
        recovered = {
            item["template_id"]
            for item in episodes
            if item["runtime"] == runtime_name
            and item["condition"] == "recoverable_fault"
            and item["evaluation"]["safe_success"]
            and item["template_id"] in clean_success
        }
        by_runtime[runtime_name] = {
            "by_condition": by_condition,
            "matched_clean_capable_tasks": len(clean_success),
            "recovered_fault_tasks": len(recovered),
            "recovery_rate": len(recovered) / len(clean_success) if clean_success else None,
        }

    by_fault_family: dict[str, Any] = {}
    for fault_family in sorted({item["fault_family"] for item in episodes}):
        by_fault_family[fault_family] = {
            runtime_name: sum(
                item["evaluation"]["safe_success"]
                for item in episodes
                if item["fault_family"] == fault_family
                and item["runtime"] == runtime_name
                and item["condition"] == "recoverable_fault"
            )
            for runtime_name in RUNTIME_NAMES
        }
    return {
        "episode_count": len(episodes),
        "task_count": len({item["template_id"] for item in episodes}),
        "runtime_count": len({item["runtime"] for item in episodes}),
        "condition_count": len({item["condition"] for item in episodes}),
        "model_calls": sum(item["policy"]["model_calls"] for item in episodes),
        "external_network_calls": sum(item["external_network_calls"] for item in episodes),
        "by_runtime": by_runtime,
        "by_fault_family": by_fault_family,
        "fault_recovery_rate_delta_r2_minus_r1": (
            by_runtime["r2_reliable"]["recovery_rate"] - by_runtime["r1_guarded"]["recovery_rate"]
        ),
    }


def _trace_payload_audit(traces_dir: Path) -> dict[str, Any]:
    forbidden = (
        b'"arguments"',
        b'"visible_task"',
        b"@synthetic.invalid",
        b"person-alex",
        b"order-main",
        b"flight-main",
    )
    files = sorted(traces_dir.glob("*.jsonl"))
    findings: dict[str, list[str]] = {}
    for path in files:
        payload = path.read_bytes().lower()
        matches = [marker.decode("utf-8") for marker in forbidden if marker.lower() in payload]
        if matches:
            findings[path.name] = matches
    return {
        "trace_count": len(files),
        "forbidden_payload_findings": findings,
        "passed": len(files) == 48 and not findings,
    }


def _validity(
    captures: list[EpisodeCapture],
    traces_dir: Path,
) -> dict[str, Any]:
    episodes = [capture.record for capture in captures]
    expected_matrix = {
        (spec.template_id, runtime_name, condition)
        for spec in PILOT_TASK_SPECS
        for runtime_name in RUNTIME_NAMES
        for condition in CONDITIONS
    }
    actual_matrix = {(item["template_id"], item["runtime"], item["condition"]) for item in episodes}
    policy_digests: dict[str, set[str]] = defaultdict(set)
    reset_hashes: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        policy_digests[item["template_id"]].add(item["policy"]["policy_sha256"])
        reset_hashes[item["template_id"]].add(item["initial_state_hash"])

    expected_fault_success = {
        "postcommit_response_loss": {"r2_reliable"},
        "retryable_invocation_error": {"r1_guarded", "r2_reliable"},
        "input_schema_drift": {"r2_reliable"},
        "output_schema_drift": {"r2_reliable"},
        "compatible_state_conflict": {"r2_reliable"},
        "bounded_compensation": {"r2_reliable"},
    }
    expected_outcomes = all(
        item["evaluation"]["safe_success"]
        == (
            item["condition"] == "clean"
            or item["runtime"] in expected_fault_success[item["fault_family"]]
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

    do_nothing = {}
    mutations = {}
    for spec in PILOT_TASK_SPECS:
        r2_capture = next(
            capture
            for capture in captures
            if capture.record["template_id"] == spec.template_id
            and capture.record["runtime"] == "r2_reliable"
            and capture.record["condition"] == "recoverable_fault"
        )
        no_op_report = evaluate_pilot_task(
            spec,
            "recoverable_fault",
            r2_capture.pre_snapshot,
            r2_capture.pre_snapshot,
            (),
        )
        do_nothing[spec.template_id] = not no_op_report.safe_success
        mutations[spec.template_id] = evaluator_mutation_audit(
            spec,
            "recoverable_fault",
            r2_capture.pre_snapshot,
            r2_capture.post_snapshot,
            r2_capture.trace_events,
        )

    model_stage_fail_closed = False
    try:
        default_contract().assert_ready("pilot")
    except RuntimeError:
        model_stage_fail_closed = True
    catalog = pilot_catalog_audit()
    trace_payloads = _trace_payload_audit(traces_dir)
    checks = {
        "exact_forty_eight_episode_matrix": (
            len(episodes) == 48 and actual_matrix == expected_matrix
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
        "r2_recovers_all_faulted_tasks": all(
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
        "six_mechanisms_exercised_exactly": mechanism_counts
        == {
            "postcommit_confirmations": 3,
            "retryable_invocation_retries": 2,
            "input_schema_adaptations": 1,
            "output_schema_normalizations": 1,
            "compatible_conflict_rebases": 1,
            "compensation_actions": 3,
        },
        "do_nothing_rejected_for_all_tasks": all(do_nothing.values()),
        "every_required_state_mutation_detected": all(
            item["passed"] for item in mutations.values()
        ),
        "pilot_model_stage_still_fails_closed": model_stage_fail_closed,
        "pilot_catalog_complete_and_balanced_by_mechanism": catalog["passed"],
        "zero_model_and_network_calls": all(
            item["policy"]["model_calls"] == 0 and item["external_network_calls"] == 0
            for item in episodes
        ),
        "digest_only_traces": trace_payloads["passed"],
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
        "trace_payloads": trace_payloads,
    }


def run_pilot_preflight(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    """Run 48 no-model episodes and refuse to reuse an evidence directory."""

    if traces_dir.exists():
        raise FileExistsError(f"Refusing to reuse traces directory: {traces_dir}")
    traces_dir.mkdir(parents=True)
    captures = [
        execute_scripted_episode(
            spec=spec,
            runtime_name=runtime_name,
            condition=condition,
            trace_path=traces_dir
            / f"{_episode_id(spec.template_id, runtime_name, condition)}.jsonl",
        )
        for spec in PILOT_TASK_SPECS
        for runtime_name in RUNTIME_NAMES
        for condition in CONDITIONS
    ]
    episodes = [capture.record for capture in captures]
    aggregate = aggregate_scripted_episodes(episodes)
    validity = _validity(captures, traces_dir)
    if aggregate["episode_count"] != 48:
        raise AssertionError("Pilot preflight execution count drifted")
    if not validity["all_selected_checks_passed"]:
        failed = [name for name, passed in validity["checks"].items() if not passed]
        raise AssertionError(f"Pilot preflight validity failed: {failed}")
    return {
        "metadata": {
            "run_id": RUN_ID,
            "package_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "environment_seed": ENVIRONMENT_SEED,
            "policy": "deterministic reactive oracle; zero model calls",
            "result_scope": "scripted pilot preflight; not the 144-episode model pilot",
        },
        "main_study_contract": default_contract().as_dict(),
        "pilot_preflight": {
            "formula": "8 tasks × 1 environment seed × 2 conditions × 3 runtimes",
            "episode_count": 48,
            "sampling_trials": 0,
            "model_configurations": 0,
        },
        "aggregate": aggregate,
        "validity": validity,
        "episodes": episodes,
        "limitations": [
            "This is a deterministic oracle preflight, not the 144-episode model pilot.",
            (
                "Five tasks migrate existing blueprints and three formerly planned "
                "blueprints gain v0.17 fixtures."
            ),
            "Each task uses one environment seed; the three-trial model stage remains fail closed.",
            (
                "The data-driven SQLite fixtures validate mechanisms but still require "
                "human task-card review before the confirmatory main study."
            ),
        ],
    }
