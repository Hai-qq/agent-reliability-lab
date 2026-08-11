from __future__ import annotations

import io
import json
import unittest
import urllib.error
from typing import Any

from arl_mainstudy.model import ModelRequest, SamplingConfig
from arl_modelpilot.deepseek import PROMPT_CONTRACT_VERSION
from arl_pilot.env import PilotEnvironment
from arl_pilot.specs import SPECS_BY_TEMPLATE_ID
from arl_replication_v30.backend import (
    OpenCodeFlashV30Backend,
    OpenCodeProV30Backend,
    RetryingOpenCodeV30Transport,
)
from arl_replication_v30.contract import FLASH_BINDING, PRO_BINDING


def response(model_id: str, *, completion_tokens: int = 20) -> dict[str, Any]:
    return {
        "id": "response-v30-unit",
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
                            "id": "call-v30-unit",
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
            "completion_tokens": completion_tokens,
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 60,
            "total_tokens": 100 + completion_tokens,
        },
    }


class CaptureTransport:
    def __init__(self, model_id: str, *, completion_tokens: int = 20) -> None:
        self.model_id = model_id
        self.completion_tokens = completion_tokens
        self.payload: dict[str, Any] | None = None
        self.calls = 0

    def __call__(
        self,
        url: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.calls += 1
        self.payload = payload
        return response(self.model_id, completion_tokens=self.completion_tokens)


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


class ReplicationV30BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = SPECS_BY_TEMPLATE_ID["workspace.schedule-meeting.main-v1"]
        environment = PilotEnvironment(self.spec, "clean")
        try:
            self.observation = environment.reset(self.spec.task_id, 0).as_dict()
        finally:
            environment.close()

    def _request(
        self,
        binding: Any,
        *,
        observation: dict[str, Any] | None = None,
    ) -> ModelRequest:
        return ModelRequest(
            prompt_contract_version=PROMPT_CONTRACT_VERSION,
            binding=binding,
            task_id=self.spec.task_id,
            turn_index=0,
            observation=observation or self.observation,
            feedback=None,
            tools=self.spec.model_tools,
            sampling=SamplingConfig(0.0, 1.0, 1_024, None),
        )

    def test_both_bindings_disable_thinking_and_reserve_before_dispatch(self) -> None:
        for backend_type, binding in (
            (OpenCodeFlashV30Backend, FLASH_BINDING),
            (OpenCodeProV30Backend, PRO_BINDING),
        ):
            transport = CaptureTransport(binding.model_id)
            backend = backend_type(api_key="unit-secret", transport=transport)
            self.assertEqual(backend.generate(self._request(binding)).kind, "tool")
            assert transport.payload is not None
            self.assertEqual(transport.payload["thinking"], {"type": "disabled"})
            reservation = backend.budget_reservation_records()[0]
            self.assertTrue(reservation["allowed"])
            self.assertTrue(reservation["actual_within_reservation"])
            self.assertEqual(reservation["request_sha256"], backend.call_records[0].request_sha256)

    def test_oversized_request_is_rejected_before_transport(self) -> None:
        transport = CaptureTransport(PRO_BINDING.model_id)
        backend = OpenCodeProV30Backend(api_key="unit-secret", transport=transport)
        observation = {
            "visible_task": {
                "user_request": "Call one synthetic tool.",
                "context": {"event_id": "x" * 25_000, "time": "2026-09-10T10:00"},
            }
        }
        with self.assertRaisesRegex(RuntimeError, "model_budget_reservation_exhausted"):
            backend.generate(self._request(PRO_BINDING, observation=observation))
        self.assertEqual(transport.calls, 0)
        self.assertEqual(backend.call_records, [])
        reservation = backend.budget_reservation_records()[0]
        self.assertFalse(reservation["allowed"])
        self.assertFalse(reservation["checks"]["input_token_cap"])

    def test_provider_usage_above_reserved_response_is_detected(self) -> None:
        transport = CaptureTransport(PRO_BINDING.model_id, completion_tokens=1_025)
        backend = OpenCodeProV30Backend(api_key="unit-secret", transport=transport)
        backend.generate(self._request(PRO_BINDING))
        self.assertFalse(backend.budget_reservation_records()[0]["actual_within_reservation"])

    def test_retryable_503_uses_frozen_exponential_schedule(self) -> None:
        error = urllib.error.HTTPError(
            "https://opencode.ai/zen/go/v1/chat/completions",
            503,
            "unavailable",
            {},
            None,
        )
        urlopen = SequenceUrlOpen([error, error, response(PRO_BINDING.model_id)])
        delays: list[float] = []
        transport = RetryingOpenCodeV30Transport(urlopen=urlopen, sleeper=delays.append)
        value = transport("ignored", {"model": PRO_BINDING.model_id}, "unit-secret", 5.0)
        self.assertEqual(value["model"], PRO_BINDING.model_id)
        self.assertEqual(urlopen.calls, 3)
        self.assertEqual(delays, [0.5, 1.0])
        self.assertEqual(transport.audits[0]["attempt_count"], 3)
        self.assertEqual(
            transport.audits[0]["retry_error_codes"],
            ["provider_http_503", "provider_http_503"],
        )
        self.assertNotIn("unit-secret", repr(transport.audits))

    def test_retryable_503_stops_after_five_total_attempts(self) -> None:
        errors = [
            urllib.error.HTTPError(
                "https://opencode.ai/zen/go/v1/chat/completions",
                503,
                "unavailable",
                {},
                None,
            )
            for _ in range(5)
        ]
        urlopen = SequenceUrlOpen(errors)
        delays: list[float] = []
        transport = RetryingOpenCodeV30Transport(urlopen=urlopen, sleeper=delays.append)
        with self.assertRaisesRegex(RuntimeError, "provider_http_503"):
            transport("ignored", {"model": PRO_BINDING.model_id}, "unit-secret", 5.0)
        self.assertEqual(urlopen.calls, 5)
        self.assertEqual(delays, [0.5, 1.0, 2.0, 4.0])
        self.assertEqual(transport.audits[0]["attempt_count"], 5)
        self.assertEqual(transport.audits[0]["final_error_code"], "provider_http_503")


if __name__ == "__main__":
    unittest.main()
