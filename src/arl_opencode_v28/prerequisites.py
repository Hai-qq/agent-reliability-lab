"""Fail-closed prerequisite gates for the v0.28 canary and formal matrix."""

from __future__ import annotations

from typing import Any

from .contract import MODEL_BINDINGS, QWEN_BINDING

PROBE_SOURCE_PATHS = (
    "scripts/probe_opencode_go_v28.py",
    "src/arl_opencode_v28/backend.py",
    "src/arl_opencode_v28/contract.py",
    "src/arl_opencode_v28/probe.py",
)


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


def validate_protocol_probe(
    artifact: dict[str, Any],
    *,
    current_source_manifest: dict[str, Any],
) -> dict[str, Any]:
    metadata = artifact.get("metadata", {})
    probe_sources = metadata.get("source_manifest", {}).get("files", {})
    current_sources = current_source_manifest.get("files", {})
    calls = artifact.get("provider_calls", [])
    checks = {
        "probe_passed": artifact.get("passed") is True,
        "exact_qwen_binding": artifact.get("binding") == QWEN_BINDING.as_dict(),
        "authenticated_catalog": artifact.get("catalog_attestation", {}).get("passed") is True,
        "provider_content_not_persisted": metadata.get("provider_content_persisted") is False,
        "two_digest_only_provider_calls": isinstance(calls, list)
        and len(calls) == 2
        and all(
            isinstance(call, dict)
            and isinstance(call.get("request_sha256"), str)
            and isinstance(call.get("response_sha256"), str)
            for call in calls
        ),
        "no_raw_content_fields": not _forbidden_content_keys(artifact),
        "probe_sources_match_current": all(
            isinstance(probe_sources, dict) and probe_sources.get(path) == current_sources.get(path)
            for path in PROBE_SOURCE_PATHS
        ),
    }
    return {"checks": checks, "passed": all(checks.values())}


def validate_canary_summary(
    artifact: dict[str, Any],
    *,
    current_source_manifest: dict[str, Any],
) -> dict[str, Any]:
    metadata = artifact.get("metadata", {})
    experiment = artifact.get("experiment", {})
    validity = artifact.get("validity", {})
    readiness = artifact.get("readiness", {})
    checks = {
        "canary_run_id": metadata.get("run_id") == "arl-opencode-go-flash-qwen-canary-v0.28.0",
        "package_version": metadata.get("package_version") == "0.28.0",
        "provider_content_not_persisted": metadata.get("provider_content_persisted") is False,
        "exact_12_episode_canary": experiment.get("episode_count") == 12
        and artifact.get("aggregate", {}).get("episode_count") == 12,
        "exact_model_bindings": experiment.get("bindings")
        == {slot: MODEL_BINDINGS[slot].as_dict() for slot in ("flash", "qwen")},
        "infrastructure_valid": validity.get("all_selected_checks_passed") is True,
        "credential_audit_passed": validity.get("credential_audit", {}).get("passed") is True,
        "ready_for_formal": readiness.get("ready_for_864_episode_main") is True,
        "canary_sources_match_current": metadata.get("source_manifest", {}).get("sha256")
        == current_source_manifest.get("sha256"),
    }
    return {"checks": checks, "passed": all(checks.values())}
