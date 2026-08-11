"""Digest-only OpenCode Go adapters over the frozen structured-tool parser."""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any

from arl.core.types import digest_value
from arl_mainstudy.model import ModelDecision, ModelRequest
from arl_modelpilot.deepseek import (
    DeepSeekBackendError,
    DeepSeekChatBackend,
    DeepSeekPricing,
)

from .contract import (
    FLASH_BINDING,
    MIMO_BINDING,
    MODEL_BINDINGS,
    OPENCODE_GO_ENDPOINT,
    OPENCODE_GO_MODELS_ENDPOINT,
)

USER_AGENT = "agent-reliability-lab/0.27"
OPENCODE_GO_PRICING = DeepSeekPricing(
    cache_hit_input_per_million=0.0028,
    cache_miss_input_per_million=0.14,
    output_per_million=0.28,
    source="https://dev.opencode.ai/docs/go/",
    observed_date="2026-08-09",
)


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


def opencode_transport(
    ignored_url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    """POST to the fixed Go endpoint without persisting headers or response bodies."""

    request = urllib.request.Request(
        OPENCODE_GO_ENDPOINT,
        data=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        headers=_headers(api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            value = json.load(response)
    except urllib.error.HTTPError as error:
        raise DeepSeekBackendError(f"provider_http_{error.code}") from error
    except urllib.error.URLError as error:
        raise DeepSeekBackendError("provider_transport_error") from error
    except (TimeoutError, json.JSONDecodeError) as error:
        raise DeepSeekBackendError("provider_invalid_or_timed_out_response") from error
    if not isinstance(value, dict):
        raise DeepSeekBackendError("provider_non_object_response")
    return value


def fetch_catalog_attestation(api_key: str, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    """Authenticate the public catalog and retain only selected-model metadata/digests."""

    request = urllib.request.Request(
        OPENCODE_GO_MODELS_ENDPOINT,
        headers=_headers(api_key),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        raise DeepSeekBackendError(f"provider_catalog_http_{error.code}") from error
    except urllib.error.URLError as error:
        raise DeepSeekBackendError("provider_catalog_transport_error") from error
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise DeepSeekBackendError("provider_catalog_invalid_json") from error
    models = value.get("data", []) if isinstance(value, dict) else []
    selected = {
        item.get("id"): {
            "id": item.get("id"),
            "object": item.get("object"),
            "owned_by": item.get("owned_by"),
            "created": item.get("created"),
        }
        for item in models
        if isinstance(item, dict)
        and item.get("id") in {binding.model_id for binding in MODEL_BINDINGS.values()}
    }
    checks = {
        "http_200": status == 200,
        "both_selected_models_present": set(selected)
        == {binding.model_id for binding in MODEL_BINDINGS.values()},
        "owned_by_opencode": all(item["owned_by"] == "opencode" for item in selected.values()),
    }
    return {
        "endpoint": OPENCODE_GO_MODELS_ENDPOINT,
        "response_sha256": hashlib.sha256(raw).hexdigest(),
        "response_bytes": len(raw),
        "selected_models": selected,
        "selected_models_identity_sha256": digest_value(
            {
                model_id: {
                    "id": item["id"],
                    "object": item["object"],
                    "owned_by": item["owned_by"],
                }
                for model_id, item in sorted(selected.items())
            }
        ),
        "created_field_treated_as_transient": True,
        "checks": checks,
        "passed": all(checks.values()),
    }


class OpenCodeGoBackend(DeepSeekChatBackend):
    """Base adapter that reuses the frozen structured tool-call parser only."""

    thinking_mode = "not_applicable"

    def __init__(
        self, *, api_key: str, timeout_seconds: float = 90.0, transport=opencode_transport
    ):
        super().__init__(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=transport,
            pricing=OPENCODE_GO_PRICING,
        )

    def _request_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload = super()._request_payload(request)
        payload.pop("thinking", None)
        return payload

    def generate(self, request: ModelRequest) -> ModelDecision:
        start = len(self.call_records)
        try:
            return super().generate(request)
        finally:
            for index in range(start, len(self.call_records)):
                self.call_records[index] = replace(
                    self.call_records[index],
                    thinking_mode=self.thinking_mode,
                )


class OpenCodeGoFlashBackend(OpenCodeGoBackend):
    binding = FLASH_BINDING
    thinking_mode = "disabled"

    def _request_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload = super()._request_payload(request)
        payload["thinking"] = {"type": "disabled"}
        return payload


class OpenCodeGoMiMoBackend(OpenCodeGoBackend):
    binding = MIMO_BINDING


def backend_for_slot(
    slot_id: str,
    *,
    api_key: str,
    timeout_seconds: float,
) -> OpenCodeGoBackend:
    if slot_id == "flash":
        return OpenCodeGoFlashBackend(api_key=api_key, timeout_seconds=timeout_seconds)
    if slot_id == "mimo":
        return OpenCodeGoMiMoBackend(api_key=api_key, timeout_seconds=timeout_seconds)
    raise ValueError(f"Unknown OpenCode Go model slot: {slot_id}")
