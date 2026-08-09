"""Canary and complete 864-episode OpenCode Go two-model study."""

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
from arl_mainmodel.experiment import aggregate_main_single_slot
from arl_mainpack.specs import MAIN_SPECS_BY_TEMPLATE_ID, MAIN_TASK_SPECS, main_pack_catalog_audit
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
from .backend import OpenCodeGoBackend, backend_for_slot
from .contract import (
    MODEL_BINDINGS,
    OPENCODE_GO_CATALOG_SNAPSHOT_DATE,
    OPENCODE_GO_ENDPOINT,
    amendment_record,
    openstudy_contract,
)

MODEL_SLOT_IDS = ("flash", "mimo")
MODEL_BUDGET = ModelBudget(
    max_calls=8,
    max_input_tokens=20_000,
    max_output_tokens=8_192,
    max_monetary_cost=0.01,
)
FORMAL_CONFIG = ModelPilotConfig(
    version=__version__,
    run_id="arl-opencode-go-two-model-main-v0.27.0",
    study_id="arl-opencode-go-two-model-main-v027",
    sampling=SamplingConfig(0.0, 1.0, 1_024, None),
    budget=MODEL_BUDGET,
)
CANARY_CONFIG = ModelPilotConfig(
    version=__version__,
    run_id="arl-opencode-go-two-model-canary-v0.27.0",
    study_id="arl-opencode-go-two-model-canary-v027",
    sampling=FORMAL_CONFIG.sampling,
    budget=FORMAL_CONFIG.budget,
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
    slot_id: str,
    template_id: str,
    runtime_name: str,
    condition: str,
    sampling_trial: int,
) -> str:
    return f"opencode-{slot_id}-t{sampling_trial}-{template_id}-{runtime_name}-{condition}"


def openstudy_manifest(*, canary: bool = False) -> StudyManifest:
    config = CANARY_CONFIG if canary else FORMAL_CONFIG
    if canary:
        dimensions = (
            (MAIN_SPECS_BY_TEMPLATE_ID[template_id], "r2_reliable", "recoverable_fault", 0, slot)
            for template_id in CANARY_TEMPLATE_IDS
            for slot in MODEL_SLOT_IDS
        )
    else:
        dimensions = (
            (spec, runtime, condition, trial, slot)
            for spec in MAIN_TASK_SPECS
            for runtime in RUNTIME_NAMES
            for condition in CONDITIONS
            for trial in SAMPLING_TRIALS
            for slot in MODEL_SLOT_IDS
        )
    jobs = tuple(
        StudyJob.from_payload(
            _episode_id(slot, spec.template_id, runtime, condition, trial),
            {
                "slot_id": slot,
                "template_id": spec.template_id,
                "runtime": runtime,
                "condition": condition,
                "environment_seed": ENVIRONMENT_SEED,
                "sampling_trial": trial,
                "binding": MODEL_BINDINGS[slot].as_dict(),
                "prompt_contract_version": PROMPT_CONTRACT_VERSION,
                "experiment_config": config.as_dict(),
                "provider_contract": {
                    "endpoint": OPENCODE_GO_ENDPOINT,
                    "catalog_snapshot_date": OPENCODE_GO_CATALOG_SNAPSHOT_DATE,
                },
                "stage": "canary" if canary else "formal",
            },
        )
        for spec, runtime, condition, trial, slot in dimensions
    )
    return StudyManifest(config.study_id, config.version, jobs)


@contextmanager
def _runtime_configuration(
    *,
    config: ModelPilotConfig,
    backend: OpenCodeGoBackend,
    episode_id: str,
) -> Iterator[None]:
    names = (
        "CONFIG",
        "DEEPSEEK_FLASH_BINDING",
        "THINKING_MODE",
        "bound_pilot_contract",
        "_episode_id",
    )
    original = {name: getattr(frozen_single, name) for name in names}
    frozen_single.CONFIG = config
    frozen_single.DEEPSEEK_FLASH_BINDING = backend.binding
    frozen_single.THINKING_MODE = backend.thinking_mode
    frozen_single.bound_pilot_contract = openstudy_contract
    frozen_single._episode_id = lambda *ignored: episode_id
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(frozen_single, name, value)


def execute_openstudy_job(
    job: StudyJob,
    trace_path: Path,
    *,
    api_key: str,
    timeout_seconds: float = 90.0,
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
        "stage",
    }
    if set(payload) != expected_keys:
        raise ValueError("OpenCode Go job payload has unexpected fields")
    slot = payload["slot_id"]
    if slot not in MODEL_SLOT_IDS or payload["binding"] != MODEL_BINDINGS[slot].as_dict():
        raise ValueError("OpenCode Go model binding drifted")
    if payload["prompt_contract_version"] != PROMPT_CONTRACT_VERSION:
        raise ValueError("OpenCode Go prompt contract drifted")
    if payload["provider_contract"] != {
        "endpoint": OPENCODE_GO_ENDPOINT,
        "catalog_snapshot_date": OPENCODE_GO_CATALOG_SNAPSHOT_DATE,
    }:
        raise ValueError("OpenCode Go provider contract drifted")
    config = CANARY_CONFIG if payload["stage"] == "canary" else FORMAL_CONFIG
    if payload["stage"] not in {"canary", "formal"}:
        raise ValueError("OpenCode Go stage is invalid")
    if payload["experiment_config"] != config.as_dict():
        raise ValueError("OpenCode Go experiment configuration drifted")
    if payload["environment_seed"] != ENVIRONMENT_SEED:
        raise ValueError("OpenCode Go environment seed drifted")
    try:
        spec = MAIN_SPECS_BY_TEMPLATE_ID[payload["template_id"]]
    except KeyError as error:
        raise ValueError("OpenCode Go job references an unknown task") from error
    if payload["runtime"] not in RUNTIME_NAMES or payload["condition"] not in CONDITIONS:
        raise ValueError("OpenCode Go runtime or condition is invalid")
    if payload["sampling_trial"] not in SAMPLING_TRIALS:
        raise ValueError("OpenCode Go sampling trial is invalid")
    expected_id = _episode_id(
        slot,
        spec.template_id,
        payload["runtime"],
        payload["condition"],
        payload["sampling_trial"],
    )
    if job.job_id != expected_id:
        raise ValueError("OpenCode Go job ID does not match its payload")
    backend = backend_for_slot(slot, api_key=api_key, timeout_seconds=timeout_seconds)
    return execute_openstudy_episode(
        spec=spec,
        slot_id=slot,
        runtime_name=payload["runtime"],
        condition=payload["condition"],
        sampling_trial=payload["sampling_trial"],
        backend=backend,
        trace_path=trace_path,
        config=config,
        episode_id=expected_id,
    )


def execute_openstudy_episode(
    *,
    spec: Any,
    slot_id: str,
    runtime_name: str,
    condition: str,
    sampling_trial: int,
    backend: OpenCodeGoBackend,
    trace_path: Path,
    config: ModelPilotConfig = FORMAL_CONFIG,
    episode_id: str | None = None,
) -> dict[str, Any]:
    """Execute one episode with an injectable backend for deterministic testing."""

    if slot_id not in MODEL_SLOT_IDS or backend.binding != MODEL_BINDINGS[slot_id]:
        raise ValueError("OpenCode Go episode slot and backend binding differ")
    resolved_id = episode_id or _episode_id(
        slot_id,
        spec.template_id,
        runtime_name,
        condition,
        sampling_trial,
    )
    with _runtime_configuration(config=config, backend=backend, episode_id=resolved_id):
        record = frozen_single.execute_model_episode(
            spec=spec,
            runtime_name=runtime_name,
            condition=condition,
            sampling_trial=sampling_trial,
            backend=backend,
            trace_path=trace_path,
        )
    record["model_slot"] = slot_id
    record["provider"]["api_family"] = "OpenCode Go OpenAI-compatible Chat Completions"
    record["provider"]["gateway"] = "opencode-go"
    record["provider"]["endpoint"] = OPENCODE_GO_ENDPOINT
    return record


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
        raw = path.read_bytes().lower()
        matches = sorted(marker.decode() for marker in forbidden if marker in raw)
        if matches:
            findings[path.name] = matches
    return {
        "trace_count": len(files),
        "forbidden_payload_findings": findings,
        "passed": len(files) == expected_count and not findings,
    }


def _percentile(values: list[int], probability: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def _usage(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    calls = [call for episode in episodes for call in episode["provider"]["calls"]]
    latencies = [call["latency_ms"] for call in calls]
    return {
        "model_calls": sum(episode["policy"]["model_calls"] for episode in episodes),
        "external_network_calls": sum(episode["external_network_calls"] for episode in episodes),
        "input_tokens": sum(call["input_tokens"] for call in calls),
        "cache_hit_tokens": sum(call["cache_hit_tokens"] for call in calls),
        "cache_miss_tokens": sum(call["cache_miss_tokens"] for call in calls),
        "output_tokens": sum(call["output_tokens"] for call in calls),
        "reasoning_tokens": sum(call["reasoning_tokens"] for call in calls),
        "total_tokens": sum(call["total_tokens"] for call in calls),
        "estimated_usage_value_usd": sum(call["estimated_cost_usd"] for call in calls),
        "accepted_model_responses": sum(call["status"] == "ok" for call in calls),
        "provider_or_protocol_errors": sum(call["status"] != "ok" for call in calls),
        "latency_ms_p50": _percentile(latencies, 0.5),
        "latency_ms_p95": _percentile(latencies, 0.95),
    }


def aggregate_openstudy(episodes: list[dict[str, Any]], *, canary: bool) -> dict[str, Any]:
    by_model: dict[str, Any] = {}
    for slot in MODEL_SLOT_IDS:
        selected = [episode for episode in episodes if episode["model_slot"] == slot]
        by_model[slot] = (
            {
                "episode_count": len(selected),
                "safe_successes": sum(item["evaluation"]["safe_success"] for item in selected),
                "model_usage": _usage(selected),
            }
            if canary
            else aggregate_main_single_slot(selected)
        )
    return {
        "episode_count": len(episodes),
        "model_count": len({episode["model_slot"] for episode in episodes}),
        "by_model": by_model,
        "combined_usage": _usage(episodes),
    }


def _validity(
    episodes: list[dict[str, Any]],
    *,
    workspace: Path,
    api_key: str,
    catalog_attestation: dict[str, Any],
    canary: bool,
) -> dict[str, Any]:
    manifest = openstudy_manifest(canary=canary)
    expected_matrix = {
        (
            payload["slot_id"],
            payload["template_id"],
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
            item["runtime"],
            item["condition"],
            item["sampling_trial"],
        )
        for item in episodes
    }
    calls = [call for episode in episodes for call in episode["provider"]["calls"]]
    policy_digests: dict[tuple[str, str], set[str]] = defaultdict(set)
    reset_hashes: dict[str, set[str]] = defaultdict(set)
    for episode in episodes:
        policy_digests[(episode["model_slot"], episode["template_id"])].add(
            episode["policy"]["policy_sha256"]
        )
        reset_hashes[episode["template_id"]].add(episode["initial_state_hash"])
    usage_matches = all(
        episode["policy"]["input_tokens"]
        == sum(
            call["input_tokens"] for call in episode["provider"]["calls"] if call["status"] == "ok"
        )
        and episode["policy"]["output_tokens"]
        == sum(
            call["output_tokens"] for call in episode["provider"]["calls"] if call["status"] == "ok"
        )
        and episode["external_network_calls"] == len(episode["provider"]["calls"])
        for episode in episodes
    )
    config = CANARY_CONFIG if canary else FORMAL_CONFIG
    checks = {
        "two_exact_model_bindings_ready": _contract_ready(),
        "authenticated_catalog_attestation": catalog_attestation.get("passed") is True,
        "exact_selected_matrix": len(episodes) == len(manifest.jobs)
        and actual_matrix == expected_matrix,
        "complete_24_task_pack": main_pack_catalog_audit()["passed"],
        "same_policy_contract_across_pairs_and_trials": all(
            len(values) == 1 for values in policy_digests.values()
        ),
        "same_reset_state_across_models_pairs_and_trials": all(
            len(values) == 1 for values in reset_hashes.values()
        ),
        "exact_model_bindings": all(
            episode["policy"]["binding"] == MODEL_BINDINGS[episode["model_slot"]].as_dict()
            for episode in episodes
        ),
        "provider_returned_requested_model": all(
            call["response_model"] == MODEL_BINDINGS[episode["model_slot"]].model_id
            for episode in episodes
            for call in episode["provider"]["calls"]
            if call["status"] == "ok"
        ),
        "inference_controls_match_contract": all(
            call["thinking_mode"]
            == ("disabled" if episode["model_slot"] == "flash" else "not_applicable")
            for episode in episodes
            for call in episode["provider"]["calls"]
        ),
        "zero_provider_transport_or_parse_errors": bool(calls)
        and all(call["status"] == "ok" for call in calls),
        "zero_local_model_protocol_errors": all(
            episode["execution"]["failure_code"] != "model_protocol_error" for episode in episodes
        ),
        "usage_totals_match_provider_records": usage_matches,
        "per_episode_model_budgets_respected": all(
            episode["external_network_calls"] <= config.budget.max_calls
            and sum(call["input_tokens"] for call in episode["provider"]["calls"])
            <= config.budget.max_input_tokens
            and sum(call["output_tokens"] for call in episode["provider"]["calls"])
            <= config.budget.max_output_tokens
            and sum(call["estimated_cost_usd"] for call in episode["provider"]["calls"])
            <= config.budget.max_monetary_cost
            for episode in episodes
        ),
        "digest_only_traces": _trace_audit(workspace, len(manifest.jobs))["passed"],
        "credential_absent_from_persisted_evidence": credential_audit(workspace, api_key)["passed"],
    }
    return {
        "checks": checks,
        "all_selected_checks_passed": all(checks.values()),
        "policy_digests": {
            f"{slot}/{template}": sorted(values)
            for (slot, template), values in sorted(policy_digests.items())
        },
        "reset_hashes": {key: sorted(value) for key, value in sorted(reset_hashes.items())},
        "trace_payloads": _trace_audit(workspace, len(manifest.jobs)),
        "credential_audit": credential_audit(workspace, api_key),
    }


def _contract_ready() -> bool:
    try:
        openstudy_contract().assert_ready("main")
    except RuntimeError:
        return False
    return True


def build_openstudy_summary(
    episodes: list[dict[str, Any]],
    *,
    workspace: Path,
    project_root: Path,
    api_key: str,
    catalog_attestation: dict[str, Any],
    canary: bool,
) -> dict[str, Any]:
    aggregate = aggregate_openstudy(episodes, canary=canary)
    validity = _validity(
        episodes,
        workspace=workspace,
        api_key=api_key,
        catalog_attestation=catalog_attestation,
        canary=canary,
    )
    if canary:
        readiness: dict[str, Any] = {
            "canary_valid": validity["all_selected_checks_passed"],
            "ready_for_864_episode_main": validity["all_selected_checks_passed"],
        }
    else:
        quality = {
            slot: {
                "minimum_75_percent_clean_safe_pass_at_3_per_runtime": all(
                    aggregate["by_model"][slot]["by_runtime"][runtime]["by_condition"]["clean"][
                        "safe_pass_at_3_rate"
                    ]
                    >= 0.75
                    for runtime in RUNTIME_NAMES
                ),
                "r2_clean_noninferiority_margin_minus_0_05": aggregate["by_model"][slot][
                    "primary_effects"
                ]["clean_safe_pass_at_3_delta_r2_minus_r1"]
                >= -0.05,
            }
            for slot in MODEL_SLOT_IDS
        }
        readiness = {
            "model_quality_checks": quality,
            "ready_for_confirmatory_analysis": validity["all_selected_checks_passed"]
            and all(all(checks.values()) for checks in quality.values()),
        }
    return {
        "metadata": {
            "run_id": CANARY_CONFIG.run_id if canary else FORMAL_CONFIG.run_id,
            "package_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "result_scope": (
                "12-episode OpenCode Go two-model canary"
                if canary
                else "864-episode OpenCode Go two-model main"
            ),
            "provider_content_persisted": False,
        },
        "contract_amendment": amendment_record(),
        "main_study_contract": openstudy_contract().as_dict(),
        "provider_catalog_attestation": catalog_attestation,
        "experiment": {
            "formula": (
                "6 selected fault tasks × R2 × fault × 1 trial × 2 models"
                if canary
                else "24 tasks × 1 seed × 2 conditions × 3 runtimes × 3 trials × 2 models"
            ),
            "episode_count": len(episodes),
            "bindings": {slot: MODEL_BINDINGS[slot].as_dict() for slot in MODEL_SLOT_IDS},
            "sampling": (CANARY_CONFIG if canary else FORMAL_CONFIG).sampling.as_dict(),
            "budget_per_episode": asdict((CANARY_CONFIG if canary else FORMAL_CONFIG).budget),
        },
        "aggregate": aggregate,
        "validity": validity,
        "readiness": readiness,
        "episodes": episodes,
        "limitations": [
            "Both models share the OpenCode Go gateway, so this is not cross-provider evidence.",
            "OpenCode Go does not return a system_fingerprint for these compatibility probes.",
            "Catalog timestamps identify listings, not immutable serving-weight hashes.",
            "Usage-value estimates are not incremental subscription charges.",
        ],
    }
