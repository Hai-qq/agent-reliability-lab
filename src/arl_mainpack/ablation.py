"""Deterministic leave-one-mechanism-out analysis for the 24-task R2 runtime."""

from __future__ import annotations

import hashlib
import platform
from collections import defaultdict
from pathlib import Path
from typing import Any

from arl.core.types import digest_value
from arl.runtime.journal import EventJournal
from arl_mainpack.specs import MAIN_TASK_SPECS, main_pack_catalog_audit
from arl_mainstudy.contract import default_contract
from arl_mainstudy.protocol import AgentFeedback
from arl_pilot.agent import PilotOracleAgent
from arl_pilot.env import PilotEnvironment
from arl_pilot.evaluator import evaluate_pilot_task
from arl_pilot.runtime import PilotRuntime

VERSION = "0.21.0"
RUN_ID = "arl-main-pack-mechanism-ablation-v0.21.0"
RUNTIME_NAME = "r2_reliable"
CONDITION = "recoverable_fault"
ENVIRONMENT_SEED = 0
ABLATION_IDS = (
    "baseline",
    "idempotency",
    "state_confirmation",
    "input_schema_adapter",
    "output_schema_normalizer",
    "conflict_rebase",
    "bounded_compensation",
)
TARGET_FAULT_FAMILY = {
    "idempotency": "postcommit_response_loss",
    "state_confirmation": "postcommit_response_loss",
    "input_schema_adapter": "input_schema_drift",
    "output_schema_normalizer": "output_schema_drift",
    "conflict_rebase": "compatible_state_conflict",
    "bounded_compensation": "bounded_compensation",
}


class _AblationEnvironment:
    """Remove one R2 capability while delegating all product-world behavior."""

    def __init__(self, base: PilotEnvironment, ablation_id: str) -> None:
        self._base = base
        self.ablation_id = ablation_id

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    def is_write(self, semantic_action: Any) -> bool:
        if self.ablation_id == "idempotency":
            return False
        return self._base.is_write(semantic_action)

    def confirmation_action(self, semantic_action: Any) -> Any:
        if self.ablation_id == "state_confirmation":
            return None
        return self._base.confirmation_action(semantic_action)

    def adapt_input_action(self, semantic_action: Any) -> Any:
        if self.ablation_id == "input_schema_adapter":
            return semantic_action
        return self._base.adapt_input_action(semantic_action)

    def normalize_result(self, semantic_action: Any, result: Any) -> Any:
        if self.ablation_id == "output_schema_normalizer":
            return result
        return self._base.normalize_result(semantic_action, result)

    def conflict_probe_action(self) -> Any:
        if self.ablation_id == "conflict_rebase":
            return None
        return self._base.conflict_probe_action()

    def compensation_actions(self, semantic_action: Any) -> tuple[Any, ...]:
        if self.ablation_id == "bounded_compensation":
            return ()
        return self._base.compensation_actions(semantic_action)


def _episode_id(ablation_id: str, template_id: str) -> str:
    return f"main-pack-ablation-{ablation_id}-{template_id}-{RUNTIME_NAME}-{CONDITION}"


def _execute_episode(spec: Any, ablation_id: str, trace_path: Path) -> dict[str, Any]:
    episode_id = _episode_id(ablation_id, spec.template_id)
    base = PilotEnvironment(spec, CONDITION)
    environment = _AblationEnvironment(base, ablation_id)
    try:
        observation = environment.reset(spec.task_id, ENVIRONMENT_SEED)
        pre_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=RUN_ID,
            episode_id=episode_id,
            task_id=spec.task_id,
            seed=ENVIRONMENT_SEED,
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
                    "task_catalog_sha256": main_pack_catalog_audit()["catalog_sha256"],
                    "template_id": spec.template_id,
                    "ablation_id": ablation_id,
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
        runtime = PilotRuntime(RUNTIME_NAME)
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
        post_snapshot = environment.snapshot()
        evaluation = evaluate_pilot_task(
            spec,
            CONDITION,
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
        return {
            "episode_id": episode_id,
            "ablation_id": ablation_id,
            "disabled_runtime_mechanism": None if ablation_id == "baseline" else ablation_id,
            "template_id": spec.template_id,
            "task_id": spec.task_id,
            "domain": spec.domain,
            "fault_family": spec.fault_family,
            "environment_seed": ENVIRONMENT_SEED,
            "runtime": RUNTIME_NAME,
            "condition": CONDITION,
            "expected_fault_id": spec.fault_id,
            "observed_fault_ids": observed_fault_ids,
            "policy": {
                "policy_id": agent.policy_id,
                "policy_sha256": agent.policy_digest,
                "planned_action_count": agent.action_count,
                "emitted_action_count": action_ordinal,
                "terminal_reason": agent.terminal_reason,
                "model_calls": 0,
            },
            "execution": {
                "completed_plan": failure_code is None and action_ordinal == agent.action_count,
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
            },
            "evaluation": evaluation.as_dict(),
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "trace_file": trace_path.name,
            "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
            "trace_event_count": len(journal.events),
            "external_network_calls": 0,
        }
    finally:
        base.close()


def _payload_markers(value: Any) -> set[bytes]:
    if isinstance(value, dict):
        return {marker for item in value.values() for marker in _payload_markers(item)}
    if isinstance(value, (list, tuple)):
        return {marker for item in value for marker in _payload_markers(item)}
    if isinstance(value, str) and len(value) >= 7:
        return {value.lower().encode("utf-8")}
    return set()


def _trace_audit(traces_dir: Path) -> dict[str, Any]:
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
        "forbidden_payload_findings": findings,
        "passed": len(files) == 168 and not findings,
    }


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    by_ablation: dict[str, Any] = {}
    for ablation_id in ABLATION_IDS:
        selected = [item for item in episodes if item["ablation_id"] == ablation_id]
        by_ablation[ablation_id] = {
            "episodes": len(selected),
            "safe_successes": sum(item["evaluation"]["safe_success"] for item in selected),
            "safe_success_rate": sum(item["evaluation"]["safe_success"] for item in selected)
            / len(selected),
            "by_fault_family": {
                family: sum(
                    item["evaluation"]["safe_success"]
                    for item in selected
                    if item["fault_family"] == family
                )
                for family in sorted({item["fault_family"] for item in selected})
            },
            "retry_count": sum(item["execution"]["retry_count"] for item in selected),
            "confirmation_count": sum(item["execution"]["confirmation_count"] for item in selected),
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
    baseline = by_ablation["baseline"]["safe_success_rate"]
    for value in by_ablation.values():
        value["safe_success_rate_delta_vs_baseline"] = value["safe_success_rate"] - baseline
    return {
        "episode_count": len(episodes),
        "task_count": len({item["template_id"] for item in episodes}),
        "ablation_count_including_baseline": len(ABLATION_IDS),
        "by_ablation": by_ablation,
    }


def _validity(episodes: list[dict[str, Any]], traces_dir: Path) -> dict[str, Any]:
    expected_matrix = {
        (ablation_id, spec.template_id) for ablation_id in ABLATION_IDS for spec in MAIN_TASK_SPECS
    }
    actual_matrix = {(item["ablation_id"], item["template_id"]) for item in episodes}
    policy_digests: dict[str, set[str]] = defaultdict(set)
    reset_hashes: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        policy_digests[item["template_id"]].add(item["policy"]["policy_sha256"])
        reset_hashes[item["template_id"]].add(item["initial_state_hash"])
    expected_outcomes = all(
        item["evaluation"]["safe_success"]
        == (
            item["ablation_id"] == "baseline"
            or item["fault_family"] != TARGET_FAULT_FAMILY[item["ablation_id"]]
        )
        for item in episodes
    )
    traces = _trace_audit(traces_dir)
    checks = {
        "exact_168_episode_ablation_matrix": (
            len(episodes) == 168 and actual_matrix == expected_matrix
        ),
        "same_agent_policy_for_every_ablation": all(
            len(values) == 1 for values in policy_digests.values()
        ),
        "same_fault_reset_for_every_ablation": all(
            len(values) == 1 for values in reset_hashes.values()
        ),
        "all_baseline_r2_fault_tasks_safe_success": all(
            item["evaluation"]["safe_success"]
            for item in episodes
            if item["ablation_id"] == "baseline"
        ),
        "each_ablation_affects_only_its_registered_fault_family": expected_outcomes,
        "single_registered_fault_per_episode": all(
            item["observed_fault_ids"] == [item["expected_fault_id"]] for item in episodes
        ),
        "zero_model_and_network_calls": all(
            item["policy"]["model_calls"] == 0 and item["external_network_calls"] == 0
            for item in episodes
        ),
        "digest_only_traces": traces["passed"],
    }
    return {
        "checks": checks,
        "all_selected_checks_passed": all(checks.values()),
        "policy_digests": {key: sorted(value) for key, value in sorted(policy_digests.items())},
        "reset_hashes": {key: sorted(value) for key, value in sorted(reset_hashes.items())},
        "trace_payloads": traces,
    }


def run_main_pack_ablation(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    """Run baseline plus six leave-one-mechanism-out R2 fault matrices."""

    if traces_dir.exists():
        raise FileExistsError(f"Refusing to reuse traces directory: {traces_dir}")
    traces_dir.mkdir(parents=True)
    episodes = [
        _execute_episode(
            spec,
            ablation_id,
            traces_dir / f"{_episode_id(ablation_id, spec.template_id)}.jsonl",
        )
        for ablation_id in ABLATION_IDS
        for spec in MAIN_TASK_SPECS
    ]
    aggregate = _aggregate(episodes)
    validity = _validity(episodes, traces_dir)
    if not validity["all_selected_checks_passed"]:
        failed = [name for name, passed in validity["checks"].items() if not passed]
        raise AssertionError(f"Main-pack ablation validity failed: {failed}")
    return {
        "metadata": {
            "run_id": RUN_ID,
            "package_version": VERSION,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "result_scope": "scripted R2 mechanism ablation; not an LLM-agent result",
        },
        "design": {
            "formula": "24 faulted tasks × (R2 baseline + 6 leave-one-out mechanisms)",
            "episode_count": 168,
            "runtime": RUNTIME_NAME,
            "condition": CONDITION,
            "ablation_ids": list(ABLATION_IDS),
            "target_fault_family": TARGET_FAULT_FAMILY,
            "catalog_sha256": main_pack_catalog_audit()["catalog_sha256"],
        },
        "aggregate": aggregate,
        "validity": validity,
        "episodes": episodes,
        "limitations": [
            (
                "The oracle policy isolates runtime mechanics but does not estimate model "
                "interaction effects."
            ),
            (
                "Idempotency and confirmation are tested separately even though both "
                "protect ambiguous commits."
            ),
            "The confirmatory main must repeat registered ablations with frozen model bindings.",
        ],
    }
