"""Second 432-episode DeepSeek V4 Flash slot using thinking-high inference."""

from __future__ import annotations

import hashlib
import platform
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from arl_mainmodel import experiment as frozen_single
from arl_mainmodel.experiment import aggregate_main_single_slot
from arl_mainpack.specs import (
    MAIN_SPECS_BY_TEMPLATE_ID,
    MAIN_TASK_SPECS,
    main_pack_catalog_audit,
)
from arl_mainstudy.contract import CONDITIONS, RUNTIME_NAMES
from arl_mainstudy.model import ModelBudget, SamplingConfig
from arl_modelpilot.deepseek import PROMPT_CONTRACT_VERSION
from arl_modelpilot.experiment import (
    ENVIRONMENT_SEED,
    SAMPLING_TRIALS,
    ModelPilotConfig,
    credential_audit,
)
from arl_study.scheduler import StudyJob, StudyManifest

from . import __version__
from .contract import FLASH_THINKING_HIGH_BINDING, amendment_record, dual_mode_contract
from .deepseek import REASONING_EFFORT, THINKING_MODE, DeepSeekFlashThinkingBackend

THINKING_BUDGET = ModelBudget(
    max_calls=8,
    max_input_tokens=20_000,
    max_output_tokens=8_192,
    max_monetary_cost=0.01,
)
THINKING_CONFIG = ModelPilotConfig(
    version=__version__,
    run_id="arl-deepseek-flash-thinking-high-main-v0.25.0",
    study_id="arl-deepseek-flash-thinking-high-main-v025",
    sampling=SamplingConfig(0.0, 1.0, 1_024, None),
    budget=THINKING_BUDGET,
)
CANARY_CONFIG = ModelPilotConfig(
    version=__version__,
    run_id="arl-deepseek-flash-thinking-high-canary-v0.25.0",
    study_id="arl-deepseek-flash-thinking-high-canary-v025",
    sampling=THINKING_CONFIG.sampling,
    budget=THINKING_CONFIG.budget,
)
CANARY_TEMPLATE_IDS = (
    "workspace.schedule-meeting.main-v1",
    "retail.eligible-exchange.main-v1",
    "travel.book-itinerary.main-v1",
    "workspace.clarify-attendees.main-v1",
    "retail.shipping-revision.main-v1",
    "travel.bundle-recovery.main-v1",
)


def _episode_id(
    template_id: str,
    runtime_name: str,
    condition: str,
    sampling_trial: int,
) -> str:
    return f"flash-thinking-t{sampling_trial}-{template_id}-{runtime_name}-{condition}"


def thinking_manifest(*, canary: bool = False) -> StudyManifest:
    """Return the six-job canary or complete 432-job thinking-high manifest."""

    config = CANARY_CONFIG if canary else THINKING_CONFIG
    if canary:
        dimensions = (
            (MAIN_SPECS_BY_TEMPLATE_ID[template_id], "r2_reliable", "recoverable_fault", 0)
            for template_id in CANARY_TEMPLATE_IDS
        )
    else:
        dimensions = (
            (spec, runtime_name, condition, sampling_trial)
            for spec in MAIN_TASK_SPECS
            for runtime_name in RUNTIME_NAMES
            for condition in CONDITIONS
            for sampling_trial in SAMPLING_TRIALS
        )
    jobs = tuple(
        StudyJob.from_payload(
            _episode_id(spec.template_id, runtime_name, condition, sampling_trial),
            {
                "template_id": spec.template_id,
                "runtime": runtime_name,
                "condition": condition,
                "environment_seed": ENVIRONMENT_SEED,
                "sampling_trial": sampling_trial,
                "binding": FLASH_THINKING_HIGH_BINDING.as_dict(),
                "prompt_contract_version": PROMPT_CONTRACT_VERSION,
                "experiment_config": config.as_dict(),
                "inference_mode": {
                    "thinking": THINKING_MODE,
                    "reasoning_effort": REASONING_EFFORT,
                },
                "stage": "canary" if canary else "formal",
            },
        )
        for spec, runtime_name, condition, sampling_trial in dimensions
    )
    return StudyManifest(
        study_id=config.study_id,
        experiment_version=config.version,
        jobs=jobs,
    )


@contextmanager
def _frozen_runtime_configuration(config: ModelPilotConfig) -> Iterator[None]:
    """Parameterize the frozen v0.24 executor while restoring every module global."""

    names = (
        "CONFIG",
        "DEEPSEEK_FLASH_BINDING",
        "THINKING_MODE",
        "bound_pilot_contract",
        "_episode_id",
    )
    original = {name: getattr(frozen_single, name) for name in names}
    frozen_single.CONFIG = config
    frozen_single.DEEPSEEK_FLASH_BINDING = FLASH_THINKING_HIGH_BINDING
    frozen_single.THINKING_MODE = THINKING_MODE
    frozen_single.bound_pilot_contract = dual_mode_contract
    frozen_single._episode_id = _episode_id
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(frozen_single, name, value)


def execute_thinking_job(
    job: StudyJob,
    trace_path: Path,
    *,
    api_key: str,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Execute one strictly validated local synthetic job against thinking-high."""

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
        "inference_mode",
        "stage",
    }
    if set(payload) != expected_keys:
        raise ValueError("Thinking-high job payload has unexpected fields")
    if payload["binding"] != FLASH_THINKING_HIGH_BINDING.as_dict():
        raise ValueError("Thinking-high binding drifted")
    if payload["prompt_contract_version"] != PROMPT_CONTRACT_VERSION:
        raise ValueError("Thinking-high prompt contract drifted")
    if payload["inference_mode"] != {
        "thinking": THINKING_MODE,
        "reasoning_effort": REASONING_EFFORT,
    }:
        raise ValueError("Thinking-high inference controls drifted")
    config = CANARY_CONFIG if payload["stage"] == "canary" else THINKING_CONFIG
    if payload["stage"] not in {"canary", "formal"}:
        raise ValueError("Thinking-high stage is invalid")
    if payload["experiment_config"] != config.as_dict():
        raise ValueError("Thinking-high experiment configuration drifted")
    if payload["environment_seed"] != ENVIRONMENT_SEED:
        raise ValueError("Thinking-high environment seed drifted")
    try:
        spec = MAIN_SPECS_BY_TEMPLATE_ID[payload["template_id"]]
    except KeyError as error:
        raise ValueError("Thinking-high job references an unknown task") from error
    if payload["runtime"] not in RUNTIME_NAMES or payload["condition"] not in CONDITIONS:
        raise ValueError("Thinking-high runtime or condition is invalid")
    if payload["sampling_trial"] not in SAMPLING_TRIALS:
        raise ValueError("Thinking-high sampling trial is invalid")
    expected_id = _episode_id(
        spec.template_id,
        payload["runtime"],
        payload["condition"],
        payload["sampling_trial"],
    )
    if job.job_id != expected_id:
        raise ValueError("Thinking-high job ID does not match its payload")
    backend = DeepSeekFlashThinkingBackend(
        api_key=api_key,
        timeout_seconds=timeout_seconds,
    )
    return execute_thinking_episode(
        spec=spec,
        runtime_name=payload["runtime"],
        condition=payload["condition"],
        sampling_trial=payload["sampling_trial"],
        backend=backend,
        trace_path=trace_path,
        config=config,
    )


def execute_thinking_episode(
    *,
    spec: Any,
    runtime_name: str,
    condition: str,
    sampling_trial: int,
    backend: DeepSeekFlashThinkingBackend,
    trace_path: Path,
    config: ModelPilotConfig = THINKING_CONFIG,
) -> dict[str, Any]:
    """Execute one episode through the frozen runtime under temporary mode controls."""

    with _frozen_runtime_configuration(config):
        return frozen_single.execute_model_episode(
            spec=spec,
            runtime_name=runtime_name,
            condition=condition,
            sampling_trial=sampling_trial,
            backend=backend,
            trace_path=trace_path,
        )


def _payload_markers(value: Any) -> set[bytes]:
    if isinstance(value, dict):
        return {marker for item in value.values() for marker in _payload_markers(item)}
    if isinstance(value, (list, tuple)):
        return {marker for item in value for marker in _payload_markers(item)}
    if isinstance(value, str) and len(value) >= 7:
        return {value.lower().encode("utf-8")}
    return set()


def _trace_audit(workspace: Path, expected_count: int) -> dict[str, Any]:
    forbidden = {b'"arguments"', b'"visible_task"'}
    for spec in MAIN_TASK_SPECS:
        forbidden.update(_payload_markers(spec.visible_task["context"]))
    files = sorted((workspace / "traces").glob("*.jsonl"))
    findings: dict[str, list[str]] = {}
    for path in files:
        payload = path.read_bytes().lower()
        matches = sorted(marker.decode("utf-8") for marker in forbidden if marker in payload)
        if matches:
            findings[path.name] = matches
    return {
        "trace_count": len(files),
        "forbidden_payload_findings": findings,
        "passed": len(files) == expected_count and not findings,
    }


def _validity(
    episodes: list[dict[str, Any]],
    *,
    workspace: Path,
    api_key: str,
    canary: bool,
) -> dict[str, Any]:
    manifest = thinking_manifest(canary=canary)
    expected_matrix = {
        (
            payload["template_id"],
            payload["runtime"],
            payload["condition"],
            payload["sampling_trial"],
        )
        for payload in (job.payload() for job in manifest.jobs)
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
    config = CANARY_CONFIG if canary else THINKING_CONFIG
    trace_payloads = _trace_audit(workspace, len(manifest.jobs))
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
    checks = {
        "dual_mode_contract_ready_for_864_matrix": _contract_is_ready(),
        "exact_selected_matrix": len(episodes) == len(manifest.jobs)
        and actual_matrix == expected_matrix,
        "complete_24_task_pack": main_pack_catalog_audit()["passed"],
        "same_policy_contract_across_pairs_and_trials": all(
            len(values) == 1 for values in policy_digests.values()
        ),
        "clean_fault_reset_hash_match": canary
        or all(len(values) == 1 for values in reset_hashes.values()),
        "exact_deepseek_flash_thinking_high_binding": all(
            item["policy"]["binding"] == FLASH_THINKING_HIGH_BINDING.as_dict() for item in episodes
        ),
        "thinking_high_enabled_with_reasoning_evidence": bool(calls)
        and all(call["thinking_mode"] == THINKING_MODE for call in calls)
        and sum(call["reasoning_tokens"] for call in calls) > 0,
        "provider_returned_bound_model_and_fingerprint": bool(calls)
        and all(
            call["response_model"] == FLASH_THINKING_HIGH_BINDING.model_id
            and bool(call["system_fingerprint"])
            for call in calls
            if call["status"] == "ok"
        ),
        "zero_provider_transport_or_parse_errors": bool(calls)
        and all(call["status"] == "ok" for call in calls),
        "zero_local_model_protocol_errors": all(
            item["execution"]["failure_code"] != "model_protocol_error" for item in episodes
        ),
        "usage_totals_match_provider_records": usage_matches,
        "per_episode_model_budgets_respected": all(
            item["external_network_calls"] <= config.budget.max_calls
            and sum(call["input_tokens"] for call in item["provider"]["calls"])
            <= config.budget.max_input_tokens
            and sum(call["output_tokens"] for call in item["provider"]["calls"])
            <= config.budget.max_output_tokens
            and sum(call["estimated_cost_usd"] for call in item["provider"]["calls"])
            <= config.budget.max_monetary_cost
            for item in episodes
        ),
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


def _contract_is_ready() -> bool:
    try:
        dual_mode_contract().assert_ready("main")
    except RuntimeError:
        return False
    return True


def _percentile(values: list[int], probability: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(probability * len(ordered) + 0.999999) - 1))
    return ordered[index]


def _aggregate_canary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [call for item in episodes for call in item["provider"]["calls"]]
    latencies = [call["latency_ms"] for call in calls]
    return {
        "episode_count": len(episodes),
        "task_count": len({item["template_id"] for item in episodes}),
        "safe_successes": sum(item["evaluation"]["safe_success"] for item in episodes),
        "model_usage": {
            "model_calls": sum(item["policy"]["model_calls"] for item in episodes),
            "external_network_calls": sum(item["external_network_calls"] for item in episodes),
            "input_tokens": sum(call["input_tokens"] for call in calls),
            "cache_hit_tokens": sum(call["cache_hit_tokens"] for call in calls),
            "cache_miss_tokens": sum(call["cache_miss_tokens"] for call in calls),
            "output_tokens": sum(call["output_tokens"] for call in calls),
            "reasoning_tokens": sum(call["reasoning_tokens"] for call in calls),
            "total_tokens": sum(call["total_tokens"] for call in calls),
            "estimated_cost_usd": sum(call["estimated_cost_usd"] for call in calls),
            "accepted_model_responses": sum(call["status"] == "ok" for call in calls),
            "model_protocol_error_calls": sum(
                call["error_code"] == "model_protocol_error" for call in calls
            ),
            "provider_error_calls": sum(
                call["status"] != "ok" and call["error_code"] != "model_protocol_error"
                for call in calls
            ),
            "latency_ms_p50": _percentile(latencies, 0.5),
            "latency_ms_p95": _percentile(latencies, 0.95),
        },
        "system_fingerprints": sorted(
            {call["system_fingerprint"] for call in calls if call["system_fingerprint"]}
        ),
    }


def build_thinking_summary(
    episodes: list[dict[str, Any]],
    *,
    workspace: Path,
    project_root: Path,
    api_key: str,
    canary: bool = False,
) -> dict[str, Any]:
    aggregate = _aggregate_canary(episodes) if canary else aggregate_main_single_slot(episodes)
    validity = _validity(
        episodes,
        workspace=workspace,
        api_key=api_key,
        canary=canary,
    )
    readiness: dict[str, Any]
    if canary:
        readiness = {
            "canary_valid": validity["all_selected_checks_passed"],
            "ready_for_formal_432_episode_run": validity["all_selected_checks_passed"],
        }
    else:
        by_runtime = aggregate["by_runtime"]
        clean_quality = all(
            by_runtime[runtime]["by_condition"]["clean"]["safe_pass_at_3_rate"] >= 0.75
            for runtime in RUNTIME_NAMES
        )
        clean_delta = aggregate["primary_effects"]["clean_safe_pass_at_3_delta_r2_minus_r1"]
        checks = {
            "infrastructure_valid": validity["all_selected_checks_passed"],
            "minimum_75_percent_clean_safe_pass_at_3_per_runtime": clean_quality,
            "r2_clean_noninferiority_margin_minus_0_05": clean_delta >= -0.05,
        }
        readiness = {
            "model_quality_checks": checks,
            "ready_for_dual_mode_864_aggregate": all(checks.values()),
        }
    return {
        "metadata": {
            "run_id": CANARY_CONFIG.run_id if canary else THINKING_CONFIG.run_id,
            "package_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "result_scope": (
                "6-episode DeepSeek V4 Flash thinking-high canary"
                if canary
                else "432-episode DeepSeek V4 Flash thinking-high slot"
            ),
            "provider_content_persisted": False,
        },
        "contract_amendment": amendment_record(),
        "main_study_contract": dual_mode_contract().as_dict(),
        "inference_configuration": {
            "slot_id": "flash_thinking_high",
            "formula": (
                "6 selected fault tasks × R2 × recoverable fault × 1 trial"
                if canary
                else "24 tasks × 1 seed × 2 conditions × 3 runtimes × 1 mode × 3 trials"
            ),
            "episode_count": len(episodes),
            "binding": FLASH_THINKING_HIGH_BINDING.as_dict(),
            "thinking_mode": THINKING_MODE,
            "reasoning_effort": REASONING_EFFORT,
            "sampling": (CANARY_CONFIG if canary else THINKING_CONFIG).sampling.as_dict(),
            "budget_per_episode": asdict((CANARY_CONFIG if canary else THINKING_CONFIG).budget),
            "confirmatory": False,
        },
        "aggregate": aggregate,
        "validity": validity,
        "readiness": readiness,
        "episodes": episodes,
        "limitations": [
            "This is a second inference configuration of the same provider model ID.",
            "It cannot support cross-model or cross-provider generalization claims.",
            "The API exposes neither an immutable serving-weight hash nor a sampling seed.",
            "The two-mode amendment followed the already observed non-thinking slot result.",
        ],
    }


def trace_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
