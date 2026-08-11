"""Canary and 2,592-episode Flash + Qwen v0.29 holdout execution."""

from __future__ import annotations

import math
import platform
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from arl_mainmodel import experiment as frozen_single
from arl_mainstudy.contract import CONDITIONS, RUNTIME_NAMES
from arl_mainstudy.model import ModelBudget, SamplingConfig
from arl_modelpilot.deepseek import PROMPT_CONTRACT_VERSION
from arl_modelpilot.experiment import SAMPLING_TRIALS, ModelPilotConfig, credential_audit
from arl_opencode_v28.backend import MODEL_PRICING, OpenCodeV28Backend, backend_for_slot
from arl_study.scheduler import StudyJob, StudyManifest

from . import __version__
from .contract import (
    CATALOG_SNAPSHOT_DATE,
    MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL,
    MODEL_BINDINGS,
    OPENCODE_GO_ENDPOINT,
    RETRYABLE_TRANSPORT_ERROR_CODES,
    study_contract,
    transition_record,
)
from .specs import (
    CANARY_TEMPLATE_IDS,
    ENVIRONMENT_SEEDS,
    HOLDOUT_TEMPLATES,
    holdout_catalog_audit,
    holdout_spec,
)

MODEL_SLOT_IDS = ("flash", "qwen")
HOLDOUT_CATALOG_SHA256 = holdout_catalog_audit()["catalog_sha256"]
MODEL_BUDGET = ModelBudget(8, 20_000, 8_192, 0.01)
FORMAL_CONFIG = ModelPilotConfig(
    version=__version__,
    run_id="arl-opencode-go-holdout-main-v0.29.0",
    study_id="arl-opencode-go-holdout-main-v029",
    sampling=SamplingConfig(0.0, 1.0, 1_024, None),
    budget=MODEL_BUDGET,
)
CANARY_CONFIG = ModelPilotConfig(
    version=__version__,
    run_id="arl-opencode-go-holdout-canary-v0.29.0",
    study_id="arl-opencode-go-holdout-canary-v029",
    sampling=FORMAL_CONFIG.sampling,
    budget=FORMAL_CONFIG.budget,
)


def _episode_id(
    slot_id: str,
    template_id: str,
    environment_seed: int,
    runtime: str,
    condition: str,
    trial: int,
) -> str:
    return (
        f"opencode-v29-{slot_id}-s{environment_seed}-t{trial}-{template_id}-{runtime}-{condition}"
    )


def study_manifest(*, canary: bool = False) -> StudyManifest:
    config = CANARY_CONFIG if canary else FORMAL_CONFIG
    if canary:
        dimensions = (
            (template_id, seed, "r2_reliable", "recoverable_fault", 0, slot)
            for template_id in CANARY_TEMPLATE_IDS
            for seed in ENVIRONMENT_SEEDS
            for slot in MODEL_SLOT_IDS
        )
    else:
        dimensions = (
            (item.template_id, seed, runtime, condition, trial, slot)
            for item in HOLDOUT_TEMPLATES
            for seed in ENVIRONMENT_SEEDS
            for runtime in RUNTIME_NAMES
            for condition in CONDITIONS
            for trial in SAMPLING_TRIALS
            for slot in MODEL_SLOT_IDS
        )
    jobs = tuple(
        StudyJob.from_payload(
            _episode_id(slot, template, seed, runtime, condition, trial),
            {
                "slot_id": slot,
                "template_id": template,
                "runtime": runtime,
                "condition": condition,
                "environment_seed": seed,
                "sampling_trial": trial,
                "binding": MODEL_BINDINGS[slot].as_dict(),
                "prompt_contract_version": PROMPT_CONTRACT_VERSION,
                "experiment_config": config.as_dict(),
                "provider_contract": {
                    "endpoint": OPENCODE_GO_ENDPOINT,
                    "catalog_snapshot_date": CATALOG_SNAPSHOT_DATE,
                    "max_transport_retries_per_logical_call": (
                        MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL
                    ),
                },
                "holdout_catalog_sha256": HOLDOUT_CATALOG_SHA256,
                "stage": "canary" if canary else "formal",
            },
        )
        for template, seed, runtime, condition, trial, slot in dimensions
    )
    return StudyManifest(config.study_id, config.version, jobs)


@contextmanager
def _runtime_configuration(
    *,
    config: ModelPilotConfig,
    backend: OpenCodeV28Backend,
    episode_id: str,
    environment_seed: int,
) -> Iterator[None]:
    names = (
        "CONFIG",
        "DEEPSEEK_FLASH_BINDING",
        "THINKING_MODE",
        "bound_pilot_contract",
        "main_pack_catalog_audit",
        "ENVIRONMENT_SEED",
        "_episode_id",
    )
    original = {name: getattr(frozen_single, name) for name in names}
    frozen_single.CONFIG = config
    frozen_single.DEEPSEEK_FLASH_BINDING = backend.binding
    frozen_single.THINKING_MODE = backend.thinking_mode
    frozen_single.bound_pilot_contract = study_contract
    frozen_single.main_pack_catalog_audit = holdout_catalog_audit
    frozen_single.ENVIRONMENT_SEED = environment_seed
    frozen_single._episode_id = lambda *ignored: episode_id
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(frozen_single, name, value)


def execute_job(
    job: StudyJob,
    trace_path: Path,
    *,
    api_key: str,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    payload = job.payload()
    expected_keys = {
        "slot_id",
        "template_id",
        "runtime",
        "condition",
        "environment_seed",
        "sampling_trial",
        "binding",
        "prompt_contract_version",
        "experiment_config",
        "provider_contract",
        "holdout_catalog_sha256",
        "stage",
    }
    if set(payload) != expected_keys:
        raise ValueError("OpenCode Go v0.29 job payload has unexpected fields")
    slot = payload["slot_id"]
    if slot not in MODEL_SLOT_IDS or payload["binding"] != MODEL_BINDINGS[slot].as_dict():
        raise ValueError("OpenCode Go v0.29 model binding drifted")
    if payload["prompt_contract_version"] != PROMPT_CONTRACT_VERSION:
        raise ValueError("OpenCode Go v0.29 prompt contract drifted")
    if payload["provider_contract"] != {
        "endpoint": OPENCODE_GO_ENDPOINT,
        "catalog_snapshot_date": CATALOG_SNAPSHOT_DATE,
        "max_transport_retries_per_logical_call": MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL,
    }:
        raise ValueError("OpenCode Go v0.29 provider contract drifted")
    if payload["holdout_catalog_sha256"] != HOLDOUT_CATALOG_SHA256:
        raise ValueError("OpenCode Go v0.29 holdout catalog drifted")
    if payload["stage"] not in {"canary", "formal"}:
        raise ValueError("OpenCode Go v0.29 stage is invalid")
    config = CANARY_CONFIG if payload["stage"] == "canary" else FORMAL_CONFIG
    if payload["experiment_config"] != config.as_dict():
        raise ValueError("OpenCode Go v0.29 experiment configuration drifted")
    if payload["environment_seed"] not in ENVIRONMENT_SEEDS:
        raise ValueError("OpenCode Go v0.29 environment seed drifted")
    try:
        spec = holdout_spec(payload["template_id"], payload["environment_seed"])
    except (KeyError, ValueError) as error:
        raise ValueError("OpenCode Go v0.29 job references an unknown task cell") from error
    if payload["runtime"] not in RUNTIME_NAMES or payload["condition"] not in CONDITIONS:
        raise ValueError("OpenCode Go v0.29 runtime or condition is invalid")
    if payload["sampling_trial"] not in SAMPLING_TRIALS:
        raise ValueError("OpenCode Go v0.29 sampling trial is invalid")
    expected_id = _episode_id(
        slot,
        spec.template_id,
        spec.environment_seed,
        payload["runtime"],
        payload["condition"],
        payload["sampling_trial"],
    )
    if job.job_id != expected_id:
        raise ValueError("OpenCode Go v0.29 job ID does not match its payload")
    return execute_episode(
        spec=spec,
        slot_id=slot,
        runtime_name=payload["runtime"],
        condition=payload["condition"],
        sampling_trial=payload["sampling_trial"],
        backend=backend_for_slot(slot, api_key=api_key, timeout_seconds=timeout_seconds),
        trace_path=trace_path,
        config=config,
        episode_id=expected_id,
    )


def execute_episode(
    *,
    spec: Any,
    slot_id: str,
    runtime_name: str,
    condition: str,
    sampling_trial: int,
    backend: OpenCodeV28Backend,
    trace_path: Path,
    config: ModelPilotConfig = FORMAL_CONFIG,
    episode_id: str | None = None,
) -> dict[str, Any]:
    if slot_id not in MODEL_SLOT_IDS or backend.binding != MODEL_BINDINGS[slot_id]:
        raise ValueError("OpenCode Go v0.29 episode slot and backend binding differ")
    resolved_id = episode_id or _episode_id(
        slot_id,
        spec.template_id,
        spec.environment_seed,
        runtime_name,
        condition,
        sampling_trial,
    )
    with _runtime_configuration(
        config=config,
        backend=backend,
        episode_id=resolved_id,
        environment_seed=spec.environment_seed,
    ):
        record = frozen_single.execute_model_episode(
            spec=spec,
            runtime_name=runtime_name,
            condition=condition,
            sampling_trial=sampling_trial,
            backend=backend,
            trace_path=trace_path,
        )
    transport_audit = backend.transport_audit_records()
    record["model_slot"] = slot_id
    record["provider"].update(
        {
            "api_family": "OpenCode Go OpenAI-compatible Chat Completions",
            "gateway": "opencode-go",
            "endpoint": OPENCODE_GO_ENDPOINT,
            "logical_call_count": len(record["provider"]["calls"]),
            "transport_attempt_count": sum(item["attempt_count"] for item in transport_audit),
            "transport_retry_count": sum(item["attempt_count"] - 1 for item in transport_audit),
            "transport_audit": transport_audit,
        }
    )
    record["external_network_calls"] = record["provider"]["transport_attempt_count"]
    return record


def _safe_pass_cells(
    episodes: list[dict[str, Any]], *, runtime: str, condition: str
) -> set[tuple[str, int]]:
    passed: set[tuple[str, int]] = set()
    for item in HOLDOUT_TEMPLATES:
        for seed in ENVIRONMENT_SEEDS:
            selected = [
                episode
                for episode in episodes
                if episode["template_id"] == item.template_id
                and episode["environment_seed"] == seed
                and episode["runtime"] == runtime
                and episode["condition"] == condition
            ]
            if len(selected) == 3 and all(
                episode["evaluation"]["safe_success"] for episode in selected
            ):
                passed.add((item.template_id, seed))
    return passed


def _percentile(values: list[int], probability: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def _usage(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [call for episode in episodes for call in episode["provider"]["calls"]]
    latencies = [call["latency_ms"] for call in calls]
    return {
        "logical_model_calls": sum(episode["policy"]["model_calls"] for episode in episodes),
        "external_network_attempts": sum(episode["external_network_calls"] for episode in episodes),
        "transport_retries": sum(
            episode["provider"]["transport_retry_count"] for episode in episodes
        ),
        "input_tokens": sum(call["input_tokens"] for call in calls),
        "cache_hit_tokens": sum(call["cache_hit_tokens"] for call in calls),
        "cache_miss_tokens": sum(call["cache_miss_tokens"] for call in calls),
        "output_tokens": sum(call["output_tokens"] for call in calls),
        "reasoning_tokens": sum(call["reasoning_tokens"] for call in calls),
        "total_tokens": sum(call["total_tokens"] for call in calls),
        "estimated_usage_value_usd": sum(call["estimated_cost_usd"] for call in calls),
        "accepted_model_responses": sum(call["status"] == "ok" for call in calls),
        "unrecovered_provider_or_protocol_errors": sum(call["status"] != "ok" for call in calls),
        "latency_ms_p50": _percentile(latencies, 0.5),
        "latency_ms_p95": _percentile(latencies, 0.95),
    }


def _aggregate_model(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    by_runtime: dict[str, Any] = {}
    for runtime in RUNTIME_NAMES:
        by_condition: dict[str, Any] = {}
        for condition in CONDITIONS:
            selected = [
                item
                for item in episodes
                if item["runtime"] == runtime and item["condition"] == condition
            ]
            safe_pass = _safe_pass_cells(episodes, runtime=runtime, condition=condition)
            by_seed = {
                str(seed): {
                    "safe_pass_at_3_tasks": sum(cell[1] == seed for cell in safe_pass),
                    "safe_pass_at_3_rate": sum(cell[1] == seed for cell in safe_pass) / 24,
                }
                for seed in ENVIRONMENT_SEEDS
            }
            by_condition[condition] = {
                "episodes": len(selected),
                "safe_successes": sum(item["evaluation"]["safe_success"] for item in selected),
                "safe_pass_at_3_task_seed_cells": len(safe_pass),
                "safe_pass_at_3_rate": len(safe_pass) / 72,
                "by_seed": by_seed,
                "provider_or_protocol_failures": sum(
                    bool(item["execution"]["failure_code"])
                    and (
                        str(item["execution"]["failure_code"]).startswith("provider_")
                        or item["execution"]["failure_code"] == "model_protocol_error"
                    )
                    for item in selected
                ),
            }
        clean = _safe_pass_cells(episodes, runtime=runtime, condition="clean")
        fault = _safe_pass_cells(episodes, runtime=runtime, condition="recoverable_fault")
        by_runtime[runtime] = {
            "by_condition": by_condition,
            "clean_capable_task_seed_cells_at_3": len(clean),
            "recovered_fault_task_seed_cells_at_3": len(clean & fault),
            "recovery_rate_at_3": len(clean & fault) / len(clean) if clean else None,
            "by_seed": {
                str(seed): {
                    "clean_capable_tasks_at_3": sum(cell[1] == seed for cell in clean),
                    "recovered_fault_tasks_at_3": sum(cell[1] == seed for cell in clean & fault),
                    "recovery_rate_at_3": (
                        sum(cell[1] == seed for cell in clean & fault)
                        / sum(cell[1] == seed for cell in clean)
                        if sum(cell[1] == seed for cell in clean)
                        else None
                    ),
                }
                for seed in ENVIRONMENT_SEEDS
            },
        }
    r1 = by_runtime["r1_guarded"]
    r2 = by_runtime["r2_reliable"]
    return {
        "episode_count": len(episodes),
        "task_count": len({item["template_id"] for item in episodes}),
        "environment_seed_count": len({item["environment_seed"] for item in episodes}),
        "sampling_trial_count": len({item["sampling_trial"] for item in episodes}),
        "by_runtime": by_runtime,
        "model_usage": _usage(episodes),
        "primary_effects": {
            "fault_recovery_rate_at_3_delta_r2_minus_r1": (
                r2["recovery_rate_at_3"] - r1["recovery_rate_at_3"]
            ),
            "clean_safe_pass_at_3_delta_r2_minus_r1": (
                r2["by_condition"]["clean"]["safe_pass_at_3_rate"]
                - r1["by_condition"]["clean"]["safe_pass_at_3_rate"]
            ),
            "by_seed": {
                str(seed): {
                    "fault_recovery_rate_at_3_delta_r2_minus_r1": (
                        r2["by_seed"][str(seed)]["recovery_rate_at_3"]
                        - r1["by_seed"][str(seed)]["recovery_rate_at_3"]
                    ),
                    "clean_safe_pass_at_3_delta_r2_minus_r1": (
                        r2["by_condition"]["clean"]["by_seed"][str(seed)]["safe_pass_at_3_rate"]
                        - r1["by_condition"]["clean"]["by_seed"][str(seed)]["safe_pass_at_3_rate"]
                    ),
                }
                for seed in ENVIRONMENT_SEEDS
            },
        },
    }


def aggregate_study(episodes: list[dict[str, Any]], *, canary: bool) -> dict[str, Any]:
    by_model = {}
    for slot in MODEL_SLOT_IDS:
        selected = [item for item in episodes if item["model_slot"] == slot]
        by_model[slot] = (
            {
                "episode_count": len(selected),
                "safe_successes": sum(item["evaluation"]["safe_success"] for item in selected),
                "model_usage": _usage(selected),
            }
            if canary
            else _aggregate_model(selected)
        )
    return {
        "episode_count": len(episodes),
        "model_count": len({item["model_slot"] for item in episodes}),
        "by_model": by_model,
        "combined_usage": _usage(episodes),
    }


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
    for item in HOLDOUT_TEMPLATES:
        for seed in ENVIRONMENT_SEEDS:
            visible_task = holdout_spec(item.template_id, seed).visible_task
            forbidden.update(_payload_markers(visible_task["context"]))
            forbidden.update(_payload_markers(visible_task["user_request"]))
    files = sorted((workspace / "traces").glob("*.jsonl"))
    findings: dict[str, list[str]] = {}
    for path in files:
        raw = path.read_bytes().lower()
        matches = sorted(marker.decode("utf-8") for marker in forbidden if marker in raw)
        if matches:
            findings[path.name] = matches
    return {
        "trace_count": len(files),
        "forbidden_payload_findings": findings,
        "passed": len(files) == expected_count and not findings,
    }


def _transport_audit_valid(episode: dict[str, Any]) -> bool:
    calls = episode["provider"]["calls"]
    audits = episode["provider"]["transport_audit"]
    allowed = set(RETRYABLE_TRANSPORT_ERROR_CODES)
    return (
        len(calls) == len(audits)
        and episode["provider"]["logical_call_count"] == len(calls)
        and episode["provider"]["transport_attempt_count"]
        == sum(item["attempt_count"] for item in audits)
        and episode["provider"]["transport_retry_count"]
        == sum(item["attempt_count"] - 1 for item in audits)
        and all(
            item["logical_call_index"] == index
            and 1 <= item["attempt_count"] <= MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL + 1
            and set(item["retry_error_codes"]).issubset(allowed)
            and (
                (
                    item["final_status"] == "error"
                    and call["status"] == "error"
                    and item["final_error_code"] == call["error_code"]
                )
                or (
                    item["final_status"] == "ok"
                    and item["final_error_code"] is None
                    and (
                        call["status"] == "ok"
                        or call["error_code"]
                        in {"model_protocol_error", "provider_usage_parse_error"}
                    )
                )
            )
            for index, (item, call) in enumerate(zip(audits, calls, strict=True))
        )
    )


def _validity(
    episodes: list[dict[str, Any]],
    *,
    workspace: Path,
    api_key: str,
    catalog_attestation: dict[str, Any],
    prerequisite_attestations: dict[str, Any],
    canary: bool,
) -> dict[str, Any]:
    manifest = study_manifest(canary=canary)
    expected_matrix = {
        (
            payload["slot_id"],
            payload["template_id"],
            payload["environment_seed"],
            payload["runtime"],
            payload["condition"],
            payload["sampling_trial"],
        )
        for payload in (job.payload() for job in manifest.jobs)
    }
    actual_matrix = {
        (
            item["model_slot"],
            item["template_id"],
            item["environment_seed"],
            item["runtime"],
            item["condition"],
            item["sampling_trial"],
        )
        for item in episodes
    }
    calls = [call for item in episodes for call in item["provider"]["calls"]]
    policy_digests: dict[tuple[str, str, int], set[str]] = defaultdict(set)
    reset_hashes: dict[tuple[str, int], set[str]] = defaultdict(set)
    reset_hashes_by_template: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        policy_digests[(item["model_slot"], item["template_id"], item["environment_seed"])].add(
            item["policy"]["policy_sha256"]
        )
        reset_hashes[(item["template_id"], item["environment_seed"])].add(
            item["initial_state_hash"]
        )
        reset_hashes_by_template[item["template_id"]].add(item["initial_state_hash"])
    config = CANARY_CONFIG if canary else FORMAL_CONFIG
    checks = {
        "two_exact_model_bindings_ready": _contract_ready(),
        "authenticated_catalog_attestation": catalog_attestation.get("passed") is True,
        "passed_zero_model_preflight": prerequisite_attestations.get("preflight", {}).get("passed")
        is True,
        "passed_two_model_protocol_probe": prerequisite_attestations.get("protocol_probe", {}).get(
            "passed"
        )
        is True,
        "exact_selected_matrix": len(episodes) == len(manifest.jobs)
        and actual_matrix == expected_matrix,
        "complete_holdout_catalog": holdout_catalog_audit()["passed"],
        "same_policy_contract_across_pairs_and_trials": all(
            len(values) == 1 for values in policy_digests.values()
        ),
        "same_reset_state_within_each_task_seed_cell": all(
            len(values) == 1 for values in reset_hashes.values()
        ),
        "three_distinct_reset_states_per_template": (
            canary or all(len(values) == 3 for values in reset_hashes_by_template.values())
        ),
        "exact_model_bindings": all(
            item["policy"]["binding"] == MODEL_BINDINGS[item["model_slot"]].as_dict()
            for item in episodes
        ),
        "provider_returned_requested_model": all(
            call["response_model"] == MODEL_BINDINGS[item["model_slot"]].model_id
            for item in episodes
            for call in item["provider"]["calls"]
            if call["status"] == "ok"
        ),
        "inference_controls_match_contract": all(
            call["thinking_mode"]
            == ("disabled" if item["model_slot"] == "flash" else "not_applicable")
            for item in episodes
            for call in item["provider"]["calls"]
        ),
        "bounded_transport_retry_policy_respected": all(
            _transport_audit_valid(item) for item in episodes
        ),
        "zero_unrecovered_provider_transport_or_parse_errors": bool(calls)
        and all(
            call["status"] == "ok" or call["error_code"] == "model_protocol_error" for call in calls
        ),
        "zero_local_model_protocol_errors": all(
            item["execution"]["failure_code"] != "model_protocol_error" for item in episodes
        ),
        "usage_totals_match_provider_records": all(
            item["policy"]["input_tokens"]
            == sum(call["input_tokens"] for call in item["provider"]["calls"])
            and item["policy"]["output_tokens"]
            == sum(call["output_tokens"] for call in item["provider"]["calls"])
            and item["policy"]["model_calls"] == len(item["provider"]["calls"])
            and item["external_network_calls"] == item["provider"]["transport_attempt_count"]
            for item in episodes
        ),
        "per_episode_model_budgets_respected": all(
            item["policy"]["model_calls"] <= config.budget.max_calls
            and item["external_network_calls"]
            <= config.budget.max_calls * (MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL + 1)
            and sum(call["input_tokens"] for call in item["provider"]["calls"])
            <= config.budget.max_input_tokens
            and sum(call["output_tokens"] for call in item["provider"]["calls"])
            <= config.budget.max_output_tokens
            and sum(call["estimated_cost_usd"] for call in item["provider"]["calls"])
            <= config.budget.max_monetary_cost
            for item in episodes
        ),
        "digest_only_traces": _trace_audit(workspace, len(manifest.jobs))["passed"],
        "credential_absent_from_persisted_evidence": credential_audit(workspace, api_key)["passed"],
    }
    if not canary:
        checks["passed_36_episode_canary"] = (
            prerequisite_attestations.get("canary", {}).get("passed") is True
        )
    return {
        "checks": checks,
        "all_selected_checks_passed": all(checks.values()),
        "policy_digests": {
            f"{slot}/{template}/seed-{seed}": sorted(values)
            for (slot, template, seed), values in sorted(policy_digests.items())
        },
        "reset_hashes": {
            f"{template}/seed-{seed}": sorted(values)
            for (template, seed), values in sorted(reset_hashes.items())
        },
        "trace_payloads": _trace_audit(workspace, len(manifest.jobs)),
        "credential_audit": credential_audit(workspace, api_key),
    }


def _contract_ready() -> bool:
    try:
        study_contract().assert_ready("full_three_seed")
    except RuntimeError:
        return False
    return True


def _quality(aggregate: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for slot in MODEL_SLOT_IDS:
        model = aggregate["by_model"][slot]
        per_seed = {}
        for seed in ENVIRONMENT_SEEDS:
            seed_key = str(seed)
            clean_rates = {
                runtime: model["by_runtime"][runtime]["by_condition"]["clean"]["by_seed"][seed_key][
                    "safe_pass_at_3_rate"
                ]
                for runtime in RUNTIME_NAMES
            }
            clean_delta = model["primary_effects"]["by_seed"][seed_key][
                "clean_safe_pass_at_3_delta_r2_minus_r1"
            ]
            per_seed[seed_key] = {
                "clean_safe_pass_at_3_rates": clean_rates,
                "minimum_75_percent_clean_safe_pass_at_3_per_runtime": all(
                    value >= 0.75 for value in clean_rates.values()
                ),
                "r2_clean_noninferiority_margin_minus_0_05": clean_delta >= -0.05,
            }
        result[slot] = {
            "by_seed": per_seed,
            "all_three_seeds_pass_clean_readiness": all(
                item["minimum_75_percent_clean_safe_pass_at_3_per_runtime"]
                and item["r2_clean_noninferiority_margin_minus_0_05"]
                for item in per_seed.values()
            ),
        }
    return result


def build_summary(
    episodes: list[dict[str, Any]],
    *,
    workspace: Path,
    project_root: Path,
    api_key: str,
    catalog_attestation: dict[str, Any],
    prerequisite_attestations: dict[str, Any],
    canary: bool,
) -> dict[str, Any]:
    aggregate = aggregate_study(episodes, canary=canary)
    validity = _validity(
        episodes,
        workspace=workspace,
        api_key=api_key,
        catalog_attestation=catalog_attestation,
        prerequisite_attestations=prerequisite_attestations,
        canary=canary,
    )
    if canary:
        readiness: dict[str, Any] = {
            "canary_infrastructure_valid": validity["all_selected_checks_passed"],
            "safe_success_is_descriptive_not_a_selection_gate": True,
            "ready_for_2592_episode_holdout": validity["all_selected_checks_passed"],
        }
    else:
        quality = _quality(aggregate)
        readiness = {
            "model_quality_checks": quality,
            "ready_for_replication_analysis": validity["all_selected_checks_passed"]
            and all(item["all_three_seeds_pass_clean_readiness"] for item in quality.values()),
        }
    return {
        "metadata": {
            "run_id": CANARY_CONFIG.run_id if canary else FORMAL_CONFIG.run_id,
            "package_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "result_scope": (
                "36-episode OpenCode Go holdout canary"
                if canary
                else "2,592-episode prospective three-seed holdout replication"
            ),
            "provider_content_persisted": False,
        },
        "transition": transition_record(),
        "main_study_contract": study_contract().as_dict(),
        "holdout_catalog": holdout_catalog_audit(),
        "provider_catalog_attestation": catalog_attestation,
        "prerequisite_attestations": prerequisite_attestations,
        "experiment": {
            "formula": (
                "6 fault tasks × 3 seeds × R2 × fault × 1 trial × 2 models"
                if canary
                else "24 tasks × 3 seeds × 2 conditions × 3 runtimes × 3 trials × 2 models"
            ),
            "episode_count": len(episodes),
            "bindings": {slot: MODEL_BINDINGS[slot].as_dict() for slot in MODEL_SLOT_IDS},
            "environment_seeds": list(ENVIRONMENT_SEEDS),
            "sampling": (CANARY_CONFIG if canary else FORMAL_CONFIG).sampling.as_dict(),
            "budget_per_episode": {
                **asdict((CANARY_CONFIG if canary else FORMAL_CONFIG).budget),
                "max_calls_interpretation": "logical model calls",
                "max_transport_attempts_per_logical_call": (
                    MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL + 1
                ),
            },
        },
        "aggregate": aggregate,
        "validity": validity,
        "readiness": readiness,
        "episodes": episodes,
        "limitations": [
            "v0.29 was designed after observing v0.28 and is a prospective replication holdout.",
            "The six runtime mechanism archetypes and public tool schemas are reused.",
            "Both models share OpenCode Go, so provider effects are not identified.",
            "OpenCode Go does not return an immutable serving-weight fingerprint or seed.",
            "Usage-value estimates are not incremental subscription charges.",
        ],
    }


__all__ = [
    "CANARY_CONFIG",
    "FORMAL_CONFIG",
    "MODEL_PRICING",
    "aggregate_study",
    "build_summary",
    "execute_episode",
    "execute_job",
    "study_manifest",
]
