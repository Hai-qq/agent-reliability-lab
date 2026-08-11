"""DeepSeek-V4-Flash model pilot over the eight local synthetic tasks."""

from __future__ import annotations

import copy
import hashlib
import math
import platform
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from arl.core.types import digest_value
from arl.runtime.journal import EventJournal
from arl_mainstudy.contract import (
    CONDITIONS,
    RUNTIME_NAMES,
    MainStudyContract,
    ModelSlot,
    default_contract,
)
from arl_mainstudy.model import ModelAgent, ModelBudget, ModelProtocolError, SamplingConfig
from arl_mainstudy.protocol import AgentFeedback
from arl_modelpilot.deepseek import (
    DEEPSEEK_FLASH_BINDING,
    PROMPT_CONTRACT_VERSION,
    THINKING_MODE,
    DeepSeekBackendError,
    DeepSeekChatBackend,
)
from arl_pilot.env import PilotEnvironment
from arl_pilot.evaluator import evaluate_pilot_task
from arl_pilot.runtime import PilotRuntime
from arl_pilot.specs import PILOT_TASK_SPECS, SPECS_BY_TEMPLATE_ID, PilotTaskSpec
from arl_study.scheduler import StudyJob, StudyManifest

ENVIRONMENT_SEED = 0
SAMPLING_TRIALS = (0, 1, 2)


@dataclass(frozen=True)
class ModelPilotConfig:
    version: str
    run_id: str
    study_id: str
    sampling: SamplingConfig
    budget: ModelBudget

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "run_id": self.run_id,
            "study_id": self.study_id,
            "sampling": self.sampling.as_dict(),
            "budget": asdict(self.budget),
        }


COMMON_MODEL_BUDGET = ModelBudget(
    max_calls=8,
    max_input_tokens=20_000,
    max_output_tokens=2_000,
    max_monetary_cost=0.01,
)
V018_CONFIG = ModelPilotConfig(
    version="0.18.0",
    run_id="arl-deepseek-flash-model-pilot-v0.18.0",
    study_id="arl-deepseek-flash-pilot-v018",
    sampling=SamplingConfig(0.0, 1.0, 256, None),
    budget=COMMON_MODEL_BUDGET,
)
V019_CONFIG = ModelPilotConfig(
    version="0.19.0",
    run_id="arl-deepseek-flash-model-pilot-v0.19.0",
    study_id="arl-deepseek-flash-pilot-v019",
    sampling=SamplingConfig(0.0, 1.0, 512, None),
    budget=COMMON_MODEL_BUDGET,
)
ACTIVE_CONFIG = V019_CONFIG


def bound_pilot_contract() -> MainStudyContract:
    """Bind only the pilot's strong API slot without changing the v0.16 default."""

    contract = default_contract()
    first, second = contract.model_slots
    bound = ModelSlot(
        slot_id=first.slot_id,
        role=first.role,
        provider=DEEPSEEK_FLASH_BINDING.provider,
        model_id=DEEPSEEK_FLASH_BINDING.model_id,
        revision=DEEPSEEK_FLASH_BINDING.revision,
    )
    result = replace(contract, model_slots=(bound, second))
    result.assert_ready("pilot")
    return result


def _episode_id(
    template_id: str,
    runtime_name: str,
    condition: str,
    sampling_trial: int,
) -> str:
    return f"model-pilot-t{sampling_trial}-{template_id}-{runtime_name}-{condition}"


def model_pilot_manifest(
    config: ModelPilotConfig = ACTIVE_CONFIG,
) -> StudyManifest:
    """Return the frozen 144-job pilot manifest with no task payloads or credentials."""

    binding = DEEPSEEK_FLASH_BINDING.as_dict()
    jobs = tuple(
        StudyJob.from_payload(
            _episode_id(spec.template_id, runtime_name, condition, sampling_trial),
            {
                "template_id": spec.template_id,
                "runtime": runtime_name,
                "condition": condition,
                "environment_seed": ENVIRONMENT_SEED,
                "sampling_trial": sampling_trial,
                "binding": binding,
                "prompt_contract_version": PROMPT_CONTRACT_VERSION,
                "experiment_config": config.as_dict(),
            },
        )
        for spec in PILOT_TASK_SPECS
        for runtime_name in RUNTIME_NAMES
        for condition in CONDITIONS
        for sampling_trial in SAMPLING_TRIALS
    )
    return StudyManifest(
        study_id=config.study_id,
        experiment_version=config.version,
        jobs=jobs,
    )


def _append_model_events(
    backend: DeepSeekChatBackend,
    journal: EventJournal,
    environment: PilotEnvironment,
    start_index: int,
) -> int:
    for record in backend.call_records[start_index:]:
        state_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="model",
            event_type="model_response" if record.status == "ok" else "model_error",
            state_hash_before=state_hash,
            state_hash_after=state_hash,
            input_digest=record.request_sha256,
            output_digest=record.response_sha256,
            error_code=record.error_code,
        )
    return len(backend.call_records)


def _execute_episode(
    *,
    spec: PilotTaskSpec,
    runtime_name: str,
    condition: str,
    sampling_trial: int,
    backend: DeepSeekChatBackend,
    trace_path: Path,
    config: ModelPilotConfig = ACTIVE_CONFIG,
) -> dict[str, Any]:
    episode_id = _episode_id(spec.template_id, runtime_name, condition, sampling_trial)
    environment = PilotEnvironment(spec, condition)
    try:
        observation = environment.reset(spec.task_id, ENVIRONMENT_SEED)
        pre_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=config.run_id,
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
                    "bound_contract_sha256": bound_pilot_contract().sha256,
                    "template_id": spec.template_id,
                    "sampling_trial": sampling_trial,
                    "observation": observation.as_dict(),
                }
            ),
        )
        agent = ModelAgent(
            backend=backend,
            tools=spec.model_tools,
            sampling=config.sampling,
            budget=config.budget,
            prompt_contract_version=PROMPT_CONTRACT_VERSION,
        )
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
        runtime_rejection_count = 0
        last_runtime_error: str | None = None
        action_ordinal = 0
        audited_call_count = 0

        while action_ordinal < 32:
            try:
                semantic_action = agent.next_action(feedback)
            except DeepSeekBackendError as error:
                audited_call_count = _append_model_events(
                    backend, journal, environment, audited_call_count
                )
                failure_code = error.error_code
                break
            except ModelProtocolError:
                audited_call_count = _append_model_events(
                    backend, journal, environment, audited_call_count
                )
                failure_code = "model_protocol_error"
                state_hash = environment.state_hash()
                journal.append(
                    timestamp_logical=environment.logical_time,
                    actor="harness",
                    event_type="model_decision_rejected",
                    state_hash_before=state_hash,
                    state_hash_after=state_hash,
                    error_code=failure_code,
                )
                break

            audited_call_count = _append_model_events(
                backend, journal, environment, audited_call_count
            )
            if semantic_action is None:
                if agent.terminal_reason != "model_finished":
                    failure_code = agent.terminal_reason or "model_stopped_without_reason"
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
                runtime_rejection_count += 1
                last_runtime_error = feedback.error_code or "runtime_rejected_action"
        else:  # pragma: no cover - model call budget stops first
            failure_code = "agent_step_budget_exhausted"

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
        usage = agent.usage_summary()
        calls = [record.as_dict() for record in backend.call_records]
        record = {
            "episode_id": episode_id,
            "template_id": spec.template_id,
            "task_id": spec.task_id,
            "domain": spec.domain,
            "fault_family": spec.fault_family,
            "environment_seed": ENVIRONMENT_SEED,
            "sampling_trial": sampling_trial,
            "runtime": runtime_name,
            "condition": condition,
            "expected_fault_id": spec.fault_id if condition == "recoverable_fault" else None,
            "observed_fault_ids": observed_fault_ids,
            "policy": {
                "policy_id": agent.policy_id,
                "policy_sha256": agent.policy_digest,
                "prompt_contract_version": PROMPT_CONTRACT_VERSION,
                "binding": DEEPSEEK_FLASH_BINDING.as_dict(),
                "sampling": config.sampling.as_dict(),
                "budget": asdict(config.budget),
                "emitted_action_count": action_ordinal,
                **usage,
            },
            "provider": {
                "api_family": "DeepSeek OpenAI-compatible Chat Completions",
                "thinking_mode": THINKING_MODE,
                "sampling_seed_supported": False,
                "calls": calls,
            },
            "execution": {
                "model_declared_finished": agent.terminal_reason == "model_finished",
                "failure_code": failure_code,
                "runtime_rejection_count": runtime_rejection_count,
                "last_runtime_error": last_runtime_error,
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
            "trace_file": f"{episode_id}.jsonl",
            "trace_event_count": len(journal.events),
            "external_network_calls": len(calls),
        }
        record["trace_sha256"] = hashlib.sha256(journal.jsonl_bytes()).hexdigest()
        return record
    finally:
        environment.close()


def execute_model_pilot_job(
    job: StudyJob,
    trace_path: Path,
    *,
    api_key: str,
    timeout_seconds: float = 60.0,
    config: ModelPilotConfig = ACTIVE_CONFIG,
) -> dict[str, Any]:
    """Execute one manifest job; provider/model failures remain episode outcomes."""

    payload = job.payload()
    expected_keys = {
        "template_id",
        "runtime",
        "condition",
        "environment_seed",
        "sampling_trial",
        "binding",
        "prompt_contract_version",
        "experiment_config",
    }
    if set(payload) != expected_keys:
        raise ValueError("Model-pilot job payload has unexpected fields")
    if payload["binding"] != DEEPSEEK_FLASH_BINDING.as_dict():
        raise ValueError("Model-pilot job binding drifted")
    if payload["prompt_contract_version"] != PROMPT_CONTRACT_VERSION:
        raise ValueError("Model-pilot prompt contract drifted")
    if payload["experiment_config"] != config.as_dict():
        raise ValueError("Model-pilot experiment configuration drifted")
    if payload["environment_seed"] != ENVIRONMENT_SEED:
        raise ValueError("Model-pilot environment seed drifted")
    try:
        spec = SPECS_BY_TEMPLATE_ID[payload["template_id"]]
    except KeyError as error:
        raise ValueError("Model-pilot job references an unknown task") from error
    if payload["runtime"] not in RUNTIME_NAMES or payload["condition"] not in CONDITIONS:
        raise ValueError("Model-pilot runtime or condition is invalid")
    if payload["sampling_trial"] not in SAMPLING_TRIALS:
        raise ValueError("Model-pilot sampling trial is invalid")
    expected_job_id = _episode_id(
        spec.template_id,
        payload["runtime"],
        payload["condition"],
        payload["sampling_trial"],
    )
    if job.job_id != expected_job_id:
        raise ValueError("Model-pilot job ID does not match its payload")
    backend = DeepSeekChatBackend(
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    return _execute_episode(
        spec=spec,
        runtime_name=payload["runtime"],
        condition=payload["condition"],
        sampling_trial=payload["sampling_trial"],
        backend=backend,
        trace_path=trace_path,
        config=config,
    )


def _safe_pass_at_three(
    episodes: list[dict[str, Any]],
    *,
    runtime_name: str,
    condition: str,
) -> set[str]:
    passed: set[str] = set()
    for spec in PILOT_TASK_SPECS:
        selected = [
            item
            for item in episodes
            if item["template_id"] == spec.template_id
            and item["runtime"] == runtime_name
            and item["condition"] == condition
        ]
        if len(selected) == len(SAMPLING_TRIALS) and all(
            item["evaluation"]["safe_success"] for item in selected
        ):
            passed.add(spec.template_id)
    return passed


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def aggregate_model_pilot(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    by_runtime: dict[str, Any] = {}
    for runtime_name in RUNTIME_NAMES:
        conditions: dict[str, Any] = {}
        for condition in CONDITIONS:
            selected = [
                item
                for item in episodes
                if item["runtime"] == runtime_name and item["condition"] == condition
            ]
            safe_pass = _safe_pass_at_three(
                episodes,
                runtime_name=runtime_name,
                condition=condition,
            )
            conditions[condition] = {
                "episodes": len(selected),
                "safe_successes": sum(item["evaluation"]["safe_success"] for item in selected),
                "safe_success_rate": (
                    sum(item["evaluation"]["safe_success"] for item in selected) / len(selected)
                    if selected
                    else None
                ),
                "safe_pass_at_3_tasks": len(safe_pass),
                "safe_pass_at_3_rate": len(safe_pass) / len(PILOT_TASK_SPECS),
                "provider_or_protocol_failures": sum(
                    bool(item["execution"]["failure_code"])
                    and (
                        str(item["execution"]["failure_code"]).startswith("provider_")
                        or item["execution"]["failure_code"] == "model_protocol_error"
                    )
                    for item in selected
                ),
            }
        clean_pass = _safe_pass_at_three(
            episodes,
            runtime_name=runtime_name,
            condition="clean",
        )
        fault_pass = _safe_pass_at_three(
            episodes,
            runtime_name=runtime_name,
            condition="recoverable_fault",
        )
        recovered = clean_pass & fault_pass
        by_runtime[runtime_name] = {
            "by_condition": conditions,
            "clean_capable_tasks_at_3": len(clean_pass),
            "recovered_fault_tasks_at_3": len(recovered),
            "recovery_rate_at_3": len(recovered) / len(clean_pass) if clean_pass else None,
        }

    calls = [call for item in episodes for call in item["provider"]["calls"]]
    successful_calls = [call for call in calls if call["status"] == "ok"]
    latencies = [call["latency_ms"] for call in calls]
    protocol_error_calls = [call for call in calls if call["error_code"] == "model_protocol_error"]
    provider_error_calls = [
        call
        for call in calls
        if call["status"] != "ok" and call["error_code"] != "model_protocol_error"
    ]
    totals = {
        "model_calls": sum(item["policy"]["model_calls"] for item in episodes),
        "external_network_calls": sum(item["external_network_calls"] for item in episodes),
        "input_tokens": sum(call["input_tokens"] for call in calls),
        "cache_hit_tokens": sum(call["cache_hit_tokens"] for call in calls),
        "cache_miss_tokens": sum(call["cache_miss_tokens"] for call in calls),
        "output_tokens": sum(call["output_tokens"] for call in calls),
        "reasoning_tokens": sum(call["reasoning_tokens"] for call in calls),
        "total_tokens": sum(call["total_tokens"] for call in calls),
        "estimated_cost_usd": sum(call["estimated_cost_usd"] for call in calls),
        "accepted_model_responses": len(successful_calls),
        "model_protocol_error_calls": len(protocol_error_calls),
        "provider_error_calls": len(provider_error_calls),
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
    }
    r1_clean = by_runtime["r1_guarded"]["by_condition"]["clean"]["safe_pass_at_3_rate"]
    r2_clean = by_runtime["r2_reliable"]["by_condition"]["clean"]["safe_pass_at_3_rate"]
    r1_recovery = by_runtime["r1_guarded"]["recovery_rate_at_3"]
    r2_recovery = by_runtime["r2_reliable"]["recovery_rate_at_3"]
    return {
        "episode_count": len(episodes),
        "task_count": len({item["template_id"] for item in episodes}),
        "sampling_trial_count": len({item["sampling_trial"] for item in episodes}),
        "runtime_count": len({item["runtime"] for item in episodes}),
        "condition_count": len({item["condition"] for item in episodes}),
        "by_runtime": by_runtime,
        "model_usage": totals,
        "system_fingerprints": sorted(
            {call["system_fingerprint"] for call in calls if call["system_fingerprint"] is not None}
        ),
        "primary_effects": {
            "fault_recovery_rate_at_3_delta_r2_minus_r1": (
                r2_recovery - r1_recovery
                if r2_recovery is not None and r1_recovery is not None
                else None
            ),
            "clean_safe_pass_at_3_delta_r2_minus_r1": r2_clean - r1_clean,
        },
    }


def _trace_payload_audit(workspace: Path) -> dict[str, Any]:
    forbidden = (
        b'"arguments"',
        b'"visible_task"',
        b"person-alex",
        b"order-main",
        b"flight-main",
        b"2 revised avenue",
        b"synthetic_task_json",
    )
    files = sorted((workspace / "traces").glob("*.jsonl"))
    findings: dict[str, list[str]] = {}
    for path in files:
        payload = path.read_bytes().lower()
        matches = [marker.decode("utf-8") for marker in forbidden if marker in payload]
        if matches:
            findings[path.name] = matches
    return {
        "trace_count": len(files),
        "forbidden_payload_findings": findings,
        "passed": len(files) == 144 and not findings,
    }


def credential_audit(workspace: Path, api_key: str) -> dict[str, Any]:
    """Prove that the exact in-memory credential is absent from persisted evidence."""

    key = api_key.encode("utf-8")
    checked = 0
    matches: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        checked += 1
        if key and key in path.read_bytes():
            matches.append(str(path.relative_to(workspace)))
    return {
        "checked_file_count": checked,
        "exact_credential_match_files": matches,
        "passed": bool(key) and not matches,
    }


def _validity(
    episodes: list[dict[str, Any]],
    workspace: Path,
    api_key: str,
    config: ModelPilotConfig,
) -> dict[str, Any]:
    expected_matrix = {
        (spec.template_id, runtime_name, condition, sampling_trial)
        for spec in PILOT_TASK_SPECS
        for runtime_name in RUNTIME_NAMES
        for condition in CONDITIONS
        for sampling_trial in SAMPLING_TRIALS
    }
    actual_matrix = {
        (
            item["template_id"],
            item["runtime"],
            item["condition"],
            item["sampling_trial"],
        )
        for item in episodes
    }
    policy_digests: dict[str, set[str]] = defaultdict(set)
    reset_hashes: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        policy_digests[item["template_id"]].add(item["policy"]["policy_sha256"])
        reset_hashes[item["template_id"]].add(item["initial_state_hash"])
    calls = [call for item in episodes for call in item["provider"]["calls"]]
    trace_payloads = _trace_payload_audit(workspace)
    credentials = credential_audit(workspace, api_key)

    usage_matches = all(
        item["policy"]["input_tokens"]
        == sum(call["input_tokens"] for call in item["provider"]["calls"] if call["status"] == "ok")
        and item["policy"]["output_tokens"]
        == sum(
            call["output_tokens"] for call in item["provider"]["calls"] if call["status"] == "ok"
        )
        and item["external_network_calls"] == len(item["provider"]["calls"])
        for item in episodes
    )
    budgets_respected = all(
        item["external_network_calls"] <= config.budget.max_calls
        and sum(call["input_tokens"] for call in item["provider"]["calls"])
        <= config.budget.max_input_tokens
        and sum(call["output_tokens"] for call in item["provider"]["calls"])
        <= config.budget.max_output_tokens
        and sum(call["estimated_cost_usd"] for call in item["provider"]["calls"])
        <= config.budget.max_monetary_cost
        for item in episodes
    )
    contract = bound_pilot_contract()
    main_still_gated = False
    try:
        contract.assert_ready("main")
    except RuntimeError:
        main_still_gated = True
    checks = {
        "bound_contract_allows_pilot_only": main_still_gated,
        "exact_144_episode_matrix": len(episodes) == 144 and actual_matrix == expected_matrix,
        "same_policy_contract_across_pairs_and_trials": all(
            len(values) == 1 for values in policy_digests.values()
        ),
        "clean_fault_reset_hash_match": all(len(values) == 1 for values in reset_hashes.values()),
        "exact_deepseek_flash_binding": all(
            item["policy"]["binding"] == DEEPSEEK_FLASH_BINDING.as_dict() for item in episodes
        ),
        "non_thinking_mode_has_zero_reasoning_tokens": all(
            call["thinking_mode"] == "disabled" and call["reasoning_tokens"] == 0
            for call in calls
            if call["status"] == "ok"
        ),
        "provider_returned_bound_model_and_fingerprint": all(
            call["response_model"] == DEEPSEEK_FLASH_BINDING.model_id
            and bool(call["system_fingerprint"])
            for call in calls
            if call["status"] == "ok"
        ),
        "zero_provider_transport_or_parse_errors": all(call["status"] == "ok" for call in calls),
        "zero_local_model_protocol_errors": all(
            item["execution"]["failure_code"] != "model_protocol_error" for item in episodes
        ),
        "usage_totals_match_provider_records": usage_matches,
        "per_episode_model_budgets_respected": budgets_respected,
        "digest_only_traces": trace_payloads["passed"],
        "credential_absent_from_persisted_evidence": credentials["passed"],
    }
    return {
        "checks": checks,
        "all_selected_checks_passed": all(checks.values()),
        "policy_digests": {key: sorted(value) for key, value in sorted(policy_digests.items())},
        "reset_hashes": {key: sorted(value) for key, value in sorted(reset_hashes.items())},
        "trace_payloads": trace_payloads,
        "credential_audit": credentials,
    }


def _readiness(aggregate: dict[str, Any], validity: dict[str, Any]) -> dict[str, Any]:
    by_runtime = aggregate["by_runtime"]
    minimum_clean = all(
        by_runtime[runtime]["by_condition"]["clean"]["safe_pass_at_3_rate"] >= 0.75
        for runtime in RUNTIME_NAMES
    )
    clean_delta = aggregate["primary_effects"]["clean_safe_pass_at_3_delta_r2_minus_r1"]
    checks = {
        "infrastructure_valid": validity["all_selected_checks_passed"],
        "minimum_75_percent_clean_safe_pass_at_3_per_runtime": minimum_clean,
        "r2_clean_noninferiority_margin_minus_0_05": clean_delta >= -0.05,
    }
    return {
        "preregistered_checks": checks,
        "ready_for_confirmatory_main_on_model_quality": all(checks.values()),
        "note": (
            "This gate does not require a positive R2 treatment effect; that remains an outcome. "
            "Main also requires 16 more task fixtures and a second exact model binding."
        ),
    }


def build_model_pilot_summary(
    episodes: list[dict[str, Any]],
    *,
    workspace: Path,
    project_root: Path,
    api_key: str,
    config: ModelPilotConfig = ACTIVE_CONFIG,
) -> dict[str, Any]:
    """Build the outcome-neutral 144-episode summary from completed job records."""

    aggregate = aggregate_model_pilot(episodes)
    validity = _validity(episodes, workspace, api_key, config)
    return {
        "metadata": {
            "run_id": config.run_id,
            "package_version": config.version,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "result_scope": "144-episode DeepSeek-V4-Flash model pilot",
            "provider_content_persisted": False,
        },
        "main_study_contract": bound_pilot_contract().as_dict(),
        "model_pilot": {
            "formula": (
                "8 tasks × 1 environment seed × 2 conditions × 3 runtimes × 1 model × 3 trials"
            ),
            "episode_count": 144,
            "environment_seed": ENVIRONMENT_SEED,
            "sampling_trials": list(SAMPLING_TRIALS),
            "binding": DEEPSEEK_FLASH_BINDING.as_dict(),
            "thinking_mode": THINKING_MODE,
            "sampling": config.sampling.as_dict(),
            "budget_per_episode": asdict(config.budget),
        },
        "aggregate": aggregate,
        "validity": validity,
        "readiness": _readiness(aggregate, validity),
        "episodes": episodes,
        "limitations": [
            (
                "DeepSeek's API model ID is service-bound; no immutable serving-weight "
                "hash is exposed."
            ),
            (
                "The API does not expose a sampling seed; the three trials are repeated "
                "calls at temperature 0."
            ),
            "The pilot has eight synthetic task templates and one environment seed.",
            "Provider responses are digest-only and cannot be replayed from public artifacts.",
            (
                "The 24-task confirmatory catalog still lacks 16 runnable fixtures and a "
                "second model binding."
            ),
        ],
    }


def compact_model_pilot_summary(
    summary: dict[str, Any],
    *,
    full_summary_sha256: str | None = None,
) -> dict[str, Any]:
    """Remove per-episode records while preserving a verifiable public evidence link."""

    episodes = summary.get("episodes")
    metadata = summary.get("metadata")
    if not isinstance(episodes, list) or not isinstance(metadata, dict):
        raise ValueError("Full model-pilot summary is missing metadata or episode records")
    compact = copy.deepcopy(summary)
    compact.pop("episodes")
    compact["metadata"]["result_scope"] = (
        f"public compact aggregate for {metadata.get('result_scope', 'model pilot')}"
    )
    compact["episode_evidence"] = {
        "episode_count": len(episodes),
        "episodes_sha256": digest_value(episodes),
        "full_summary_sha256": full_summary_sha256,
        "full_summary_publicly_committed": False,
        "full_episode_records": "local ignored full-summary.json and study/results",
        "provider_content_persisted": False,
    }
    return compact
