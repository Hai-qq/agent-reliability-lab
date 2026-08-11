"""OpenCode Go backends with bounded retry and pre-dispatch budget reservation."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from arl.core.types import canonical_json, digest_value
from arl_mainstudy.model import ModelDecision, ModelProtocolError, ModelRequest
from arl_modelpilot.deepseek import (
    DeepSeekBackendError,
    DeepSeekChatBackend,
    DeepSeekPricing,
)

from .contract import (
    FLASH_BINDING,
    INPUT_TOKEN_RESERVATION_OVERHEAD,
    MAX_ACCOUNTED_OUTPUT_TOKENS_PER_RESPONSE,
    MAX_INPUT_TOKENS_PER_EPISODE,
    MAX_LOGICAL_CALLS_PER_EPISODE,
    MAX_OUTPUT_TOKENS_PER_EPISODE,
    MAX_TRANSPORT_RETRIES_PER_LOGICAL_CALL,
    MAX_USAGE_VALUE_USD_PER_EPISODE,
    MODEL_BINDINGS,
    OFFICIAL_GO_DOC_URL,
    OPENCODE_GO_ENDPOINT,
    OPENCODE_GO_MODELS_ENDPOINT,
    PRO_BINDING,
    RETRYABLE_TRANSPORT_ERROR_CODES,
    TRANSPORT_RETRY_DELAYS_SECONDS,
)

USER_AGENT = "agent-reliability-lab/0.30"

FLASH_PRICING = DeepSeekPricing(
    cache_hit_input_per_million=0.0028,
    cache_miss_input_per_million=0.14,
    output_per_million=0.28,
    source=OFFICIAL_GO_DOC_URL,
    observed_date="2026-08-10",
)
PRO_PRICING = DeepSeekPricing(
    cache_hit_input_per_million=0.003625,
    cache_miss_input_per_million=0.435,
    output_per_million=0.87,
    source=OFFICIAL_GO_DOC_URL,
    observed_date="2026-08-10",
)
MODEL_PRICING = {"flash": FLASH_PRICING, "pro": PRO_PRICING}


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
    }


class RetryingOpenCodeV30Transport:
    """Retry only frozen infrastructure failures and retain sanitized metadata."""

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
                data=canonical_json(payload).encode("utf-8"),
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
                    self._sleeper(TRANSPORT_RETRY_DELAYS_SECONDS[attempt])
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
    """Authenticate the current catalog and retain only selected public metadata."""

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


class OpenCodeV30Backend(DeepSeekChatBackend):
    """Structured-tool adapter with a conservative budget reservation audit."""

    thinking_mode = "disabled"
    pricing = FLASH_PRICING

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 90.0,
        transport: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        selected_transport = transport or RetryingOpenCodeV30Transport()
        self._selected_transport = selected_transport
        self._budget_reservations: list[dict[str, Any]] = []
        super().__init__(
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=selected_transport,
            pricing=self.pricing,
        )

    def _request_payload(self, request: ModelRequest) -> dict[str, Any]:
        payload = super()._request_payload(request)
        payload["thinking"] = {"type": "disabled"}
        return payload

    def _preview_payload(self, request: ModelRequest) -> dict[str, Any]:
        messages = list(self._messages)
        pending_tool_call_id = self._pending_tool_call_id
        provider_to_semantic = dict(self._provider_to_semantic)
        try:
            if request.turn_index == 0:
                if self._messages or request.feedback is not None:
                    raise ModelProtocolError("Initial model turn is not clean")
                self._messages = self._initial_messages(request)
            else:
                self._append_feedback(request)
            return self._request_payload(request)
        finally:
            self._messages = messages
            self._pending_tool_call_id = pending_tool_call_id
            self._provider_to_semantic = provider_to_semantic

    def _reserve(self, request: ModelRequest) -> bool:
        if request.turn_index > 0 and self._buffered_tool_decisions:
            return True
        payload = self._preview_payload(request)
        request_bytes = len(canonical_json(payload).encode("utf-8"))
        reserved_input = request_bytes + INPUT_TOKEN_RESERVATION_OVERHEAD
        reserved_output = MAX_ACCOUNTED_OUTPUT_TOKENS_PER_RESPONSE
        calls_before = len(self.call_records)
        input_before = sum(item.input_tokens for item in self.call_records)
        output_before = sum(item.output_tokens for item in self.call_records)
        cost_before = sum(item.estimated_cost_usd for item in self.call_records)
        reserved_cost = self.pricing.estimate(
            cache_hit_tokens=0,
            cache_miss_tokens=reserved_input,
            output_tokens=reserved_output,
        )
        projected = {
            "logical_calls": calls_before + 1,
            "input_tokens": input_before + reserved_input,
            "output_tokens": output_before + reserved_output,
            "usage_value_usd": cost_before + reserved_cost,
        }
        checks = {
            "logical_call_cap": projected["logical_calls"] <= MAX_LOGICAL_CALLS_PER_EPISODE,
            "input_token_cap": projected["input_tokens"] <= MAX_INPUT_TOKENS_PER_EPISODE,
            "output_token_cap": projected["output_tokens"] <= MAX_OUTPUT_TOKENS_PER_EPISODE,
            "usage_value_cap": (projected["usage_value_usd"] <= MAX_USAGE_VALUE_USD_PER_EPISODE),
        }
        allowed = all(checks.values())
        self._budget_reservations.append(
            {
                "reservation_index": len(self._budget_reservations),
                "provider_call_index": calls_before if allowed else None,
                "turn_index": request.turn_index,
                "request_sha256": digest_value(payload),
                "serialized_request_bytes": request_bytes,
                "reserved_input_tokens": reserved_input,
                "reserved_output_tokens": reserved_output,
                "reserved_usage_value_usd": reserved_cost,
                "projected_episode_totals": projected,
                "checks": checks,
                "allowed": allowed,
                "actual_input_tokens": None,
                "actual_output_tokens": None,
                "actual_usage_value_usd": None,
                "actual_within_reservation": None,
            }
        )
        return allowed

    def _complete_reservation(self, call_index: int) -> None:
        audit = next(
            (
                item
                for item in reversed(self._budget_reservations)
                if item["provider_call_index"] == call_index
            ),
            None,
        )
        if audit is None or call_index >= len(self.call_records):
            return
        call = self.call_records[call_index]
        audit.update(
            {
                "actual_input_tokens": call.input_tokens,
                "actual_output_tokens": call.output_tokens,
                "actual_usage_value_usd": call.estimated_cost_usd,
                "actual_within_reservation": (
                    call.input_tokens <= audit["reserved_input_tokens"]
                    and call.output_tokens <= audit["reserved_output_tokens"]
                    and call.estimated_cost_usd <= audit["reserved_usage_value_usd"]
                ),
            }
        )

    def generate(self, request: ModelRequest) -> ModelDecision:
        if request.binding != self.binding:
            raise ModelProtocolError("Request binding does not match v0.30 backend binding")
        buffered = request.turn_index > 0 and bool(self._buffered_tool_decisions)
        if not buffered and not self._reserve(request):
            raise DeepSeekBackendError("model_budget_reservation_exhausted")
        start = len(self.call_records)
        try:
            return super().generate(request)
        finally:
            if len(self.call_records) > start:
                self._complete_reservation(start)
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

    def budget_reservation_records(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self._budget_reservations]


class OpenCodeFlashV30Backend(OpenCodeV30Backend):
    binding = FLASH_BINDING
    pricing = FLASH_PRICING


class OpenCodeProV30Backend(OpenCodeV30Backend):
    binding = PRO_BINDING
    pricing = PRO_PRICING


def backend_for_slot(
    slot_id: str,
    *,
    api_key: str,
    timeout_seconds: float,
) -> OpenCodeV30Backend:
    if slot_id == "flash":
        return OpenCodeFlashV30Backend(api_key=api_key, timeout_seconds=timeout_seconds)
    if slot_id == "pro":
        return OpenCodeProV30Backend(api_key=api_key, timeout_seconds=timeout_seconds)
    raise ValueError(f"Unknown OpenCode Go v0.30 model slot: {slot_id}")


__all__ = [
    "FLASH_PRICING",
    "MODEL_PRICING",
    "OpenCodeFlashV30Backend",
    "OpenCodeProV30Backend",
    "OpenCodeV30Backend",
    "PRO_PRICING",
    "RetryingOpenCodeV30Transport",
    "backend_for_slot",
    "fetch_catalog_attestation",
]
