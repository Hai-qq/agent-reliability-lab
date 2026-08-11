"""DeepSeek Chat Completions adapter with digest-only audit records."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

from arl.core.types import canonical_json, digest_value
from arl_mainstudy.model import (
    ExactModelBinding,
    ModelDecision,
    ModelProtocolError,
    ModelRequest,
    ModelUsage,
    ToolDefinition,
)

DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_FLASH_BINDING = ExactModelBinding(
    provider="deepseek-api",
    model_id="deepseek-v4-flash",
    revision="DeepSeek-V4-Flash/non-thinking",
)
THINKING_MODE = "disabled"
PROMPT_CONTRACT_VERSION = "arl-deepseek-tool-policy-v1"

SYSTEM_PROMPT = """You are the policy component in a local synthetic reliability benchmark.
Execute only the supplied synthetic task. Use the visible request and context values exactly.
On each turn, either call exactly one supplied function or, only after the whole task is complete,
return a short final message without a function call. Never invent tools, arguments, identifiers,
or values. Do not add idempotency keys, state versions, retries, confirmations, schema repairs,
compensation, or other reliability behavior: the benchmark runtime owns those mechanisms.
Treat tool feedback as authoritative. Do not discuss the benchmark or explain your plan."""


class DeepSeekBackendError(RuntimeError):
    """A typed provider failure that never embeds request headers or response bodies."""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


@dataclass(frozen=True)
class DeepSeekPricing:
    """Frozen USD prices used only for local cost estimation."""

    cache_hit_input_per_million: float = 0.0028
    cache_miss_input_per_million: float = 0.14
    output_per_million: float = 0.28
    source: str = "https://api-docs.deepseek.com/quick_start/pricing"
    observed_date: str = "2026-08-08"

    def estimate(
        self,
        *,
        cache_hit_tokens: int,
        cache_miss_tokens: int,
        output_tokens: int,
    ) -> float:
        return (
            cache_hit_tokens * self.cache_hit_input_per_million
            + cache_miss_tokens * self.cache_miss_input_per_million
            + output_tokens * self.output_per_million
        ) / 1_000_000

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_DEEPSEEK_PRICING = DeepSeekPricing()


@dataclass(frozen=True)
class ModelCallRecord:
    """Non-content provider evidence safe to persist in public artifacts."""

    call_index: int
    status: str
    error_code: str | None
    request_sha256: str
    response_sha256: str | None
    response_id_sha256: str | None
    requested_model: str
    response_model: str | None
    system_fingerprint: str | None
    thinking_mode: str
    finish_reason: str | None
    input_tokens: int
    cache_hit_tokens: int
    cache_miss_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    latency_ms: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


Transport = Callable[[str, dict[str, Any], str, float], dict[str, Any]]


def _default_transport(
    url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=canonical_json(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
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


def _json_type_schema(value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, list):
        item_schema = _json_type_schema(value[0]) if value else {"type": "string"}
        return {"type": "array", "items": item_schema}
    return {"type": "string"}


def _argument_schema(argument: str, context: dict[str, Any]) -> dict[str, Any]:
    if argument in context:
        return _json_type_schema(context[argument])
    if argument.endswith("_ids") or argument in {"handles"}:
        return {"type": "array", "items": {"type": "string"}}
    if argument.endswith("_count") or argument in {"quantity"}:
        return {"type": "integer"}
    return {"type": "string"}


def _provider_tool_name(tool_name: str) -> str:
    return tool_name.replace(".", "__")


def _tool_payload(tool: ToolDefinition, context: dict[str, Any]) -> dict[str, Any]:
    names = (*tool.required_arguments, *tool.optional_arguments)
    return {
        "type": "function",
        "function": {
            "name": _provider_tool_name(tool.tool_name),
            "description": (
                f"Invoke the synthetic benchmark tool {tool.tool_name} "
                f"using schema version {tool.schema_version}."
            ),
            "parameters": {
                "type": "object",
                "properties": {name: _argument_schema(name, context) for name in names},
                "required": list(tool.required_arguments),
                "additionalProperties": False,
            },
        },
    }


class DeepSeekChatBackend:
    """One-episode stateful backend for DeepSeek's OpenAI-compatible API."""

    binding = DEEPSEEK_FLASH_BINDING

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 60.0,
        transport: Transport = _default_transport,
        pricing: DeepSeekPricing = DEFAULT_DEEPSEEK_PRICING,
    ) -> None:
        if not api_key.strip():
            raise ValueError("A non-empty DeepSeek API key is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self.pricing = pricing
        self.call_records: list[ModelCallRecord] = []
        self._messages: list[dict[str, Any]] = []
        self._pending_tool_call_id: str | None = None
        self._provider_to_semantic: dict[str, str] = {}
        self._buffered_tool_decisions: list[tuple[str, str, dict[str, Any], str]] = []

    @staticmethod
    def _initial_messages(request: ModelRequest) -> list[dict[str, Any]]:
        visible_task = request.observation.get("visible_task")
        if not isinstance(visible_task, dict):
            raise ModelProtocolError("Model observation has no visible_task object")
        task_payload = {
            "task_id": request.task_id,
            "user_request": visible_task.get("user_request"),
            "context": visible_task.get("context"),
        }
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": "SYNTHETIC_TASK_JSON\n" + canonical_json(task_payload),
            },
        ]

    def _append_feedback(self, request: ModelRequest) -> None:
        if self._pending_tool_call_id is None:
            raise ModelProtocolError("Model turn has feedback without a pending tool call")
        if request.feedback is None:
            raise ModelProtocolError("Model turn is missing runtime feedback")
        self._messages.append(
            {
                "role": "tool",
                "tool_call_id": self._pending_tool_call_id,
                "content": canonical_json(request.feedback),
            }
        )
        self._pending_tool_call_id = None

    def _request_payload(self, request: ModelRequest) -> dict[str, Any]:
        visible_task = request.observation.get("visible_task", {})
        context = visible_task.get("context", {}) if isinstance(visible_task, dict) else {}
        if not isinstance(context, dict):
            raise ModelProtocolError("Model-visible task context must be an object")
        provider_names = [_provider_tool_name(tool.tool_name) for tool in request.tools]
        if len(provider_names) != len(set(provider_names)):
            raise ModelProtocolError("Provider-safe tool names collide")
        self._provider_to_semantic = {
            _provider_tool_name(tool.tool_name): tool.tool_name for tool in request.tools
        }
        return {
            "model": request.binding.model_id,
            "messages": self._messages,
            "tools": [_tool_payload(tool, context) for tool in request.tools],
            "tool_choice": "auto",
            "thinking": {"type": THINKING_MODE},
            "temperature": request.sampling.temperature,
            "top_p": request.sampling.top_p,
            "max_tokens": request.sampling.max_output_tokens,
            "stream": False,
        }

    @staticmethod
    def _usage(
        response: dict[str, Any], pricing: DeepSeekPricing
    ) -> tuple[ModelUsage, dict[str, int]]:
        raw = response.get("usage", {})
        if not isinstance(raw, dict):
            raise ModelProtocolError("Provider usage must be an object")
        input_tokens = int(raw.get("prompt_tokens", 0))
        output_tokens = int(raw.get("completion_tokens", 0))
        cache_hit = int(raw.get("prompt_cache_hit_tokens", 0))
        cache_miss = int(raw.get("prompt_cache_miss_tokens", input_tokens - cache_hit))
        details = raw.get("completion_tokens_details", {})
        reasoning_tokens = (
            int(details.get("reasoning_tokens", 0)) if isinstance(details, dict) else 0
        )
        values = (input_tokens, output_tokens, cache_hit, cache_miss, reasoning_tokens)
        if any(value < 0 for value in values) or cache_hit + cache_miss != input_tokens:
            raise ModelProtocolError("Provider returned inconsistent token usage")
        cost = pricing.estimate(
            cache_hit_tokens=cache_hit,
            cache_miss_tokens=cache_miss,
            output_tokens=output_tokens,
        )
        return ModelUsage(input_tokens, output_tokens, cost), {
            "cache_hit_tokens": cache_hit,
            "cache_miss_tokens": cache_miss,
            "reasoning_tokens": reasoning_tokens,
            "total_tokens": int(raw.get("total_tokens", input_tokens + output_tokens)),
        }

    @staticmethod
    def _choice(response: dict[str, Any]) -> tuple[dict[str, Any], str]:
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ModelProtocolError("Provider response must contain exactly one choice")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ModelProtocolError("Provider choice has no assistant message")
        finish_reason = choice.get("finish_reason")
        if not isinstance(finish_reason, str):
            raise ModelProtocolError("Provider choice has no finish reason")
        return choice["message"], finish_reason

    def _record_failure(
        self,
        *,
        request_sha256: str,
        latency_ms: int,
        error_code: str,
    ) -> None:
        self.call_records.append(
            ModelCallRecord(
                call_index=len(self.call_records),
                status="error",
                error_code=error_code,
                request_sha256=request_sha256,
                response_sha256=None,
                response_id_sha256=None,
                requested_model=self.binding.model_id,
                response_model=None,
                system_fingerprint=None,
                thinking_mode=THINKING_MODE,
                finish_reason=None,
                input_tokens=0,
                cache_hit_tokens=0,
                cache_miss_tokens=0,
                output_tokens=0,
                reasoning_tokens=0,
                total_tokens=0,
                estimated_cost_usd=0.0,
                latency_ms=latency_ms,
            )
        )

    def _take_buffered_tool_decision(self) -> ModelDecision:
        call_id, semantic_name, arguments, response_sha256 = self._buffered_tool_decisions.pop(0)
        self._pending_tool_call_id = call_id
        return ModelDecision(
            kind="tool",
            tool_name=semantic_name,
            arguments=arguments,
            usage=ModelUsage(0, 0, 0.0),
            provider_call_count=0,
            response_digest=response_sha256,
        )

    def generate(self, request: ModelRequest) -> ModelDecision:
        if request.binding != self.binding:
            raise ModelProtocolError("Request binding does not match DeepSeek backend binding")
        if request.prompt_contract_version != PROMPT_CONTRACT_VERSION:
            raise ModelProtocolError("Unexpected DeepSeek prompt contract version")
        if request.turn_index == 0:
            if self._messages or request.feedback is not None:
                raise ModelProtocolError("Initial model turn is not clean")
            self._messages = self._initial_messages(request)
        else:
            self._append_feedback(request)
            if self._buffered_tool_decisions:
                return self._take_buffered_tool_decision()

        payload = self._request_payload(request)
        request_sha256 = digest_value(payload)
        started = time.monotonic()
        try:
            response = self._transport(
                DEEPSEEK_API_URL,
                payload,
                self._api_key,
                self._timeout_seconds,
            )
        except DeepSeekBackendError as error:
            latency_ms = max(0, round((time.monotonic() - started) * 1000))
            self._record_failure(
                request_sha256=request_sha256,
                latency_ms=latency_ms,
                error_code=error.error_code,
            )
            raise
        latency_ms = max(0, round((time.monotonic() - started) * 1000))
        response_sha256 = digest_value(response)

        usage = ModelUsage(0, 0, 0.0)
        details = {
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
            "reasoning_tokens": 0,
            "total_tokens": 0,
        }
        finish_reason: str | None = None
        try:
            response_model = response.get("model")
            if response_model != self.binding.model_id:
                raise ModelProtocolError("Provider returned a different model ID")
            message, finish_reason = self._choice(response)
            usage, details = self._usage(response, self.pricing)
            raw_id = response.get("id")
            response_id_sha256 = digest_value(raw_id) if isinstance(raw_id, str) else None
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list):
                raise ModelProtocolError("Provider tool_calls must be a list")
            if tool_calls:
                parsed: list[tuple[str, str, dict[str, Any], str]] = []
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict) or not isinstance(
                        tool_call.get("function"), dict
                    ):
                        raise ModelProtocolError("Provider tool call has invalid shape")
                    call_id = tool_call.get("id")
                    provider_name = tool_call["function"].get("name")
                    raw_arguments = tool_call["function"].get("arguments")
                    if not all(
                        isinstance(value, str) for value in (call_id, provider_name, raw_arguments)
                    ):
                        raise ModelProtocolError("Provider tool call fields must be strings")
                    try:
                        semantic_name = self._provider_to_semantic[provider_name]
                    except KeyError as error:
                        raise ModelProtocolError("Provider selected an unknown tool") from error
                    try:
                        arguments = json.loads(raw_arguments)
                    except json.JSONDecodeError as error:
                        raise ModelProtocolError(
                            "Provider tool arguments are not valid JSON"
                        ) from error
                    if not isinstance(arguments, dict):
                        raise ModelProtocolError("Provider tool arguments must be an object")
                    parsed.append((call_id, semantic_name, arguments, response_sha256))
                if len({item[0] for item in parsed}) != len(parsed):
                    raise ModelProtocolError("Provider tool call IDs must be unique")
                assistant_message = {
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": tool_calls,
                }
                self._messages.append(assistant_message)
                self._buffered_tool_decisions = parsed
                decision = self._take_buffered_tool_decision()
                decision = ModelDecision(
                    kind=decision.kind,
                    tool_name=decision.tool_name,
                    arguments=decision.arguments,
                    usage=usage,
                    provider_call_count=1,
                    response_digest=decision.response_digest,
                )
            else:
                decision = ModelDecision(
                    kind="finish",
                    usage=usage,
                    response_digest=response_sha256,
                )
        except (ModelProtocolError, ValueError, TypeError) as error:
            error_code = (
                "model_protocol_error"
                if isinstance(error, ModelProtocolError)
                else "provider_usage_parse_error"
            )
            self.call_records.append(
                ModelCallRecord(
                    call_index=len(self.call_records),
                    status="error",
                    error_code=error_code,
                    request_sha256=request_sha256,
                    response_sha256=response_sha256,
                    response_id_sha256=None,
                    requested_model=self.binding.model_id,
                    response_model=response.get("model")
                    if isinstance(response.get("model"), str)
                    else None,
                    system_fingerprint=response.get("system_fingerprint")
                    if isinstance(response.get("system_fingerprint"), str)
                    else None,
                    thinking_mode=THINKING_MODE,
                    finish_reason=finish_reason,
                    input_tokens=usage.input_tokens,
                    cache_hit_tokens=details["cache_hit_tokens"],
                    cache_miss_tokens=details["cache_miss_tokens"],
                    output_tokens=usage.output_tokens,
                    reasoning_tokens=details["reasoning_tokens"],
                    total_tokens=details["total_tokens"],
                    estimated_cost_usd=usage.monetary_cost,
                    latency_ms=latency_ms,
                )
            )
            if isinstance(error, ModelProtocolError):
                raise
            raise ModelProtocolError("Provider token usage could not be parsed") from error

        self.call_records.append(
            ModelCallRecord(
                call_index=len(self.call_records),
                status="ok",
                error_code=None,
                request_sha256=request_sha256,
                response_sha256=response_sha256,
                response_id_sha256=response_id_sha256,
                requested_model=self.binding.model_id,
                response_model=response_model,
                system_fingerprint=response.get("system_fingerprint")
                if isinstance(response.get("system_fingerprint"), str)
                else None,
                thinking_mode=THINKING_MODE,
                finish_reason=finish_reason,
                input_tokens=usage.input_tokens,
                cache_hit_tokens=details["cache_hit_tokens"],
                cache_miss_tokens=details["cache_miss_tokens"],
                output_tokens=usage.output_tokens,
                reasoning_tokens=details["reasoning_tokens"],
                total_tokens=details["total_tokens"],
                estimated_cost_usd=usage.monetary_cost,
                latency_ms=latency_ms,
            )
        )
        return decision
