"""Digest-only OpenCode Go backends with bounded infrastructure retries."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
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
    MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL,
    MODEL_BINDINGS,
    OPENCODE_GO_ENDPOINT,
    OPENCODE_GO_MODELS_ENDPOINT,
    QWEN_BINDING,
    RETRYABLE_TRANSPORT_ERROR_CODES,
)

USER_AGENT = "agent-reliability-lab/0.28"
OFFICIAL_PRICING_SOURCE = "https://dev.opencode.ai/docs/go/"

FLASH_PRICING = DeepSeekPricing(
    cache_hit_input_per_million=0.0028,
    cache_miss_input_per_million=0.14,
    output_per_million=0.28,
    source=OFFICIAL_PRICING_SOURCE,
    observed_date="2026-08-09",
)
QWEN_PRICING = DeepSeekPricing(
    cache_hit_input_per_million=0.04,
    cache_miss_input_per_million=0.40,
    output_per_million=1.60,
    source=OFFICIAL_PRICING_SOURCE,
    observed_date="2026-08-09",
)
MODEL_PRICING = {"flash": FLASH_PRICING, "qwen": QWEN_PRICING}


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


class RetryingOpenCodeTransport:
    """Retry only declared infrastructure failures and retain sanitized attempt metadata."""

    def __init__(
        self,
        *,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._urlopen = urlopen
        self._sleeper = sleeper
        self.audits: list[dict[str, Any]] = []

    @staticmethod
    def _error_code(error: BaseException) -> str:
        if isinstance(error, urllib.error.HTTPError):
            return f"provider_http_{error.code}"
        if isinstance(error, urllib.error.URLError):
            return "provider_transport_error"
        return "provider_invalid_or_timed_out_response"

    def __call__(
        self,
        ignored_url: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        del ignored_url
        errors: list[str] = []
        for attempt in range(MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL + 1):
            request = urllib.request.Request(
                OPENCODE_GO_ENDPOINT,
                data=json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                headers=_headers(api_key),
                method="POST",
            )
            try:
                with self._urlopen(request, timeout=timeout_seconds) as response:
                    value = json.load(response)
                if not isinstance(value, dict):
                    raise ValueError("provider_non_object_response")
            except (
                urllib.error.HTTPError,
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
                ValueError,
            ) as error:
                code = self._error_code(error)
                errors.append(code)
                can_retry = (
                    code in RETRYABLE_TRANSPORT_ERROR_CODES
                    and attempt < MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL
                )
                if can_retry:
                    self._sleeper(0.25 * (2**attempt))
                    continue
                self.audits.append(
                    {
                        "logical_call_index": len(self.audits),
                        "attempt_count": attempt + 1,
                        "retry_error_codes": errors[:-1],
                        "final_status": "error",
                        "final_error_code": code,
                    }
                )
                raise DeepSeekBackendError(code) from error
            self.audits.append(
                {
                    "logical_call_index": len(self.audits),
                    "attempt_count": attempt + 1,
                    "retry_error_codes": errors,
                    "final_status": "ok",
                    "final_error_code": None,
                }
            )
            return value
        raise AssertionError("bounded retry loop did not return or raise")


def fetch_catalog_attestation(api_key: str, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
    """Authenticate the live catalog and retain only selected public metadata and digests."""

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


class OpenCodeV28Backend(DeepSeekChatBackend):
    """Base adapter over the frozen structured-tool parser."""

    thinking_mode = "not_applicable"
    pricing = QWEN_PRICING

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 90.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        selected_transport = transport or RetryingOpenCodeTransport()
        self._selected_transport = selected_transport
        super().__init__(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=selected_transport,
            pricing=self.pricing,
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

    def transport_audit_records(self) -> list[dict[str, Any]]:
        audits = getattr(self._selected_transport, "audits", None)
        if isinstance(audits, list) and len(audits) == len(self.call_records):
            return [dict(item) for item in audits]
        return [
            {
                "logical_call_index": index,
                "attempt_count": 1,
                "retry_error_codes": [],
                "final_status": record.status,
                "final_error_code": record.error_code,
            }
            for index, record in enumerate(self.call_records)
        ]


class OpenCodeFlashV28Backend(OpenCodeV28Backend):
    binding = FLASH_BINDING
    thinking_mode = "disabled"
    pricing = FLASH_PRICING

    def _request_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload = super()._request_payload(request)
        payload["thinking"] = {"type": "disabled"}
        return payload


class OpenCodeQwenV28Backend(OpenCodeV28Backend):
    binding = QWEN_BINDING
    pricing = QWEN_PRICING


def backend_for_slot(
    slot_id: str,
    *,
    api_key: str,
    timeout_seconds: float,
) -> OpenCodeV28Backend:
    if slot_id == "flash":
        return OpenCodeFlashV28Backend(api_key=api_key, timeout_seconds=timeout_seconds)
    if slot_id == "qwen":
        return OpenCodeQwenV28Backend(api_key=api_key, timeout_seconds=timeout_seconds)
    raise ValueError(f"Unknown OpenCode Go v0.28 model slot: {slot_id}")
