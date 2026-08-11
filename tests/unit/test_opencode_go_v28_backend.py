from __future__ import annotations

import io
import json
import unittest
import urllib.error
from typing import Any

from arl_mainstudy.model import ModelRequest, SamplingConfig
from arl_modelpilot.deepseek import PROMPT_CONTRACT_VERSION
from arl_opencode_v28.backend import (
    OpenCodeFlashV28Backend,
    OpenCodeQwenV28Backend,
    RetryingOpenCodeTransport,
)
from arl_opencode_v28.contract import FLASH_BINDING, QWEN_BINDING
from arl_pilot.env import PilotEnvironment
from arl_pilot.specs import SPECS_BY_TEMPLATE_ID


def response(model_id: str) -> dict[str, Any]:
    return {
        "id": "response-v28-unit",
        "model": model_id,
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call-v28-unit",
                            "type": "function",
                            "function": {
                                "name": "calendar__create_event",
                                "arguments": json.dumps(
                                    {"event_id": "event-main", "time": "2026-09-10T10:00"}
                                ),
                            },
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 60,
            "total_tokens": 120,
        },
    }


class CaptureTransport:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        self.payload: dict[str, Any] | None = None

    def __call__(
        self,
        url: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.payload = payload
        return response(self.model_id)


class FakeHTTPResponse:
    status = 200

    def __init__(self, value: dict[str, Any]) -> None:
        self._body = io.BytesIO(json.dumps(value).encode())

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *ignored: object) -> None:
        return None

    def read(self, amount: int = -1) -> bytes:
        return self._body.read(amount)


class SequenceUrlOpen:
    def __init__(self, values: list[Any]) -> None:
        self.values = list(values)
        self.calls = 0

    def __call__(self, request: Any, timeout: float) -> FakeHTTPResponse:
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        return FakeHTTPResponse(value)


class OpenCodeGoV28BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = SPECS_BY_TEMPLATE_ID["workspace.schedule-meeting.main-v1"]
        environment = PilotEnvironment(self.spec, "clean")
        try:
            self.observation = environment.reset(self.spec.task_id, 0).as_dict()
        finally:
            environment.close()

    def _request(self, binding: Any) -> ModelRequest:
        return ModelRequest(
            prompt_contract_version=PROMPT_CONTRACT_VERSION,
            binding=binding,
            task_id=self.spec.task_id,
            turn_index=0,
            observation=self.observation,
            feedback=None,
            tools=self.spec.model_tools,
            sampling=SamplingConfig(0.0, 1.0, 1_024, None),
        )

    def test_flash_disables_thinking_and_qwen_omits_it(self) -> None:
        flash_transport = CaptureTransport("deepseek-v4-flash")
        flash = OpenCodeFlashV28Backend(api_key="unit-secret", transport=flash_transport)
        self.assertEqual(flash.generate(self._request(FLASH_BINDING)).kind, "tool")
        assert flash_transport.payload is not None
        self.assertEqual(flash_transport.payload["thinking"], {"type": "disabled"})

        qwen_transport = CaptureTransport("qwen3.7-plus")
        qwen = OpenCodeQwenV28Backend(api_key="unit-secret", transport=qwen_transport)
        self.assertEqual(qwen.generate(self._request(QWEN_BINDING)).kind, "tool")
        assert qwen_transport.payload is not None
        self.assertNotIn("thinking", qwen_transport.payload)
        self.assertEqual(qwen.call_records[0].thinking_mode, "not_applicable")

    def test_retryable_503_is_retried_and_sanitized(self) -> None:
        error = urllib.error.HTTPError(
            "https://opencode.ai/zen/go/v1/chat/completions",
            503,
            "unavailable",
            {},
            None,
        )
        urlopen = SequenceUrlOpen([error, response("qwen3.7-plus")])
        delays: list[float] = []
        transport = RetryingOpenCodeTransport(urlopen=urlopen, sleeper=delays.append)
        value = transport("ignored", {"model": "qwen3.7-plus"}, "unit-secret", 5.0)
        self.assertEqual(value["model"], "qwen3.7-plus")
        self.assertEqual(urlopen.calls, 2)
        self.assertEqual(delays, [0.25])
        self.assertEqual(
            transport.audits,
            [
                {
                    "logical_call_index": 0,
                    "attempt_count": 2,
                    "retry_error_codes": ["provider_http_503"],
                    "final_status": "ok",
                    "final_error_code": None,
                }
            ],
        )
        self.assertNotIn("unit-secret", repr(transport.audits))

    def test_nonretryable_401_fails_after_one_attempt(self) -> None:
        error = urllib.error.HTTPError(
            "https://opencode.ai/zen/go/v1/chat/completions",
            401,
            "unauthorized",
            {},
            None,
        )
        urlopen = SequenceUrlOpen([error])
        transport = RetryingOpenCodeTransport(urlopen=urlopen, sleeper=lambda ignored: None)
        with self.assertRaisesRegex(RuntimeError, "provider_http_401"):
            transport("ignored", {"model": "qwen3.7-plus"}, "unit-secret", 5.0)
        self.assertEqual(urlopen.calls, 1)
        self.assertEqual(transport.audits[0]["attempt_count"], 1)
        self.assertEqual(transport.audits[0]["final_error_code"], "provider_http_401")


if __name__ == "__main__":
    unittest.main()
