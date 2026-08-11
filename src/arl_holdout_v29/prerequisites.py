"""Fail-closed preflight, protocol, and canary gates for v0.29."""

from __future__ import annotations

from typing import Any

from .contract import MODEL_BINDINGS
from .preflight import RUN_ID as PREFLIGHT_RUN_ID
from .specs import holdout_catalog_audit


def _forbidden_content_keys(value: Any) -> set[str]:
    findings: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {
                "api_key",
                "authorization",
                "messages",
                "content",
                "arguments",
                "request_body",
                "response_body",
            }:
                findings.add(key)
            findings.update(_forbidden_content_keys(item))
    elif isinstance(value, list):
        for item in value:
            findings.update(_forbidden_content_keys(item))
    return findings


def validate_preflight_summary(
    artifact: dict[str, Any], *, current_source_manifest: dict[str, Any]
) -> dict[str, Any]:
    metadata = artifact.get("metadata", {})
    catalog = artifact.get("holdout_catalog", {})
    checks = {
        "preflight_run_id": metadata.get("run_id") == PREFLIGHT_RUN_ID,
        "package_version": metadata.get("package_version") == "0.29.0",
        "exact_432_zero_model_episodes": artifact.get("scripted_preflight", {}).get("episode_count")
        == 432
        and artifact.get("aggregate", {}).get("episode_count") == 432,
        "validity_passed": artifact.get("validity", {}).get("all_selected_checks_passed") is True,
        "ready_for_provider_probe": artifact.get("readiness", {}).get("ready_for_provider_probe")
        is True,
        "catalog_matches_current": catalog.get("catalog_sha256")
        == holdout_catalog_audit()["catalog_sha256"],
        "sources_match_current": metadata.get("source_manifest", {}).get("sha256")
        == current_source_manifest.get("sha256"),
        "provider_content_not_persisted": metadata.get("provider_content_persisted") is False,
    }
    return {"checks": checks, "passed": all(checks.values())}


def validate_protocol_probe(
    artifact: dict[str, Any], *, current_source_manifest: dict[str, Any]
) -> dict[str, Any]:
    metadata = artifact.get("metadata", {})
    by_model = artifact.get("by_model", {})
    checks = {
        "probe_passed": artifact.get("passed") is True,
        "exact_two_model_slots": set(by_model) == {"flash", "qwen"},
        "exact_bindings": all(
            by_model.get(slot, {}).get("binding") == MODEL_BINDINGS[slot].as_dict()
            for slot in ("flash", "qwen")
        ),
        "four_digest_only_provider_calls": artifact.get("logical_call_count") == 4
        and all(
            len(by_model.get(slot, {}).get("provider_calls", [])) == 2
            and all(
                isinstance(call.get("request_sha256"), str)
                and isinstance(call.get("response_sha256"), str)
                for call in by_model[slot]["provider_calls"]
            )
            for slot in ("flash", "qwen")
        ),
        "authenticated_catalog": artifact.get("catalog_attestation", {}).get("passed") is True,
        "provider_content_not_persisted": metadata.get("provider_content_persisted") is False,
        "no_raw_content_fields": not _forbidden_content_keys(artifact),
        "sources_match_current": metadata.get("source_manifest", {}).get("sha256")
        == current_source_manifest.get("sha256"),
        "preflight_attestation_passed": artifact.get("preflight_attestation", {}).get("passed")
        is True,
    }
    return {"checks": checks, "passed": all(checks.values())}


def validate_canary_summary(
    artifact: dict[str, Any], *, current_source_manifest: dict[str, Any]
) -> dict[str, Any]:
    metadata = artifact.get("metadata", {})
    experiment = artifact.get("experiment", {})
    validity = artifact.get("validity", {})
    checks = {
        "canary_run_id": metadata.get("run_id") == "arl-opencode-go-holdout-canary-v0.29.0",
        "package_version": metadata.get("package_version") == "0.29.0",
        "provider_content_not_persisted": metadata.get("provider_content_persisted") is False,
        "exact_36_episode_canary": experiment.get("episode_count") == 36
        and artifact.get("aggregate", {}).get("episode_count") == 36,
        "exact_model_bindings": experiment.get("bindings")
        == {slot: MODEL_BINDINGS[slot].as_dict() for slot in ("flash", "qwen")},
        "infrastructure_valid": validity.get("all_selected_checks_passed") is True,
        "credential_audit_passed": validity.get("credential_audit", {}).get("passed") is True,
        "ready_for_formal": artifact.get("readiness", {}).get("ready_for_2592_episode_holdout")
        is True,
        "sources_match_current": metadata.get("source_manifest", {}).get("sha256")
        == current_source_manifest.get("sha256"),
    }
    return {"checks": checks, "passed": all(checks.values())}
