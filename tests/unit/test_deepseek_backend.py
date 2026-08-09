from __future__ import annotations

import json
import unittest

from arl_mainstudy.model import ModelProtocolError, ModelRequest, SamplingConfig
from arl_modelpilot.deepseek import (
    DEEPSEEK_FLASH_BINDING,
    PROMPT_CONTRACT_VERSION,
    DeepSeekBackendError,
    DeepSeekChatBackend,
)
from arl_pilot.env import PilotEnvironment
from arl_pilot.specs import SPECS_BY_TEMPLATE_ID


def provider_response(
    *,
    tool_name: str | None = None,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {"role": "assistant", "content": "done"}
    finish_reason = "stop"
    if tool_name is not None:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call-test-1",
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments or {}),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    return {
        "id": "response-test-1",
        "model": "deepseek-v4-flash",
        "system_fingerprint": "fp-test",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": message,
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 40,
            "prompt_cache_miss_tokens": 60,
            "total_tokens": 110,
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


class FakeTransport:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def __call__(
        self,
        url: str,
        payload: dict[str, object],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "url": url,
                "payload": payload,
                "api_key": api_key,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.responses.pop(0)


class DeepSeekBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = SPECS_BY_TEMPLATE_ID["workspace.schedule-meeting.main-v1"]
        environment = PilotEnvironment(self.spec, "clean")
        try:
            self.observation = environment.reset(self.spec.task_id, 0).as_dict()
        finally:
            environment.close()
        self.sampling = SamplingConfig(0.0, 1.0, 256, None)

    def request(
        self,
        turn_index: int,
        feedback: dict[str, object] | None,
    ) -> ModelRequest:
        return ModelRequest(
            prompt_contract_version=PROMPT_CONTRACT_VERSION,
            binding=DEEPSEEK_FLASH_BINDING,
            task_id=self.spec.task_id,
            turn_index=turn_index,
            observation=self.observation,
            feedback=feedback,
            tools=self.spec.model_tools,
            sampling=self.sampling,
        )

    def test_tool_call_round_trip_uses_safe_names_and_digest_only_records(self) -> None:
        transport = FakeTransport(
            [
                provider_response(
                    tool_name="calendar__create_event",
                    arguments={"event_id": "event-main", "time": "2026-09-10T10:00"},
                ),
                provider_response(),
            ]
        )
        backend = DeepSeekChatBackend(api_key="sk-private-test", transport=transport)
        first = backend.generate(self.request(0, None))
        self.assertEqual(first.kind, "tool")
        self.assertEqual(first.tool_name, "calendar.create_event")
        self.assertEqual(first.usage.input_tokens, 100)
        self.assertGreater(first.usage.monetary_cost, 0)

        second = backend.generate(
            self.request(
                1,
                {
                    "accepted": True,
                    "status": "ok",
                    "error_code": None,
                    "recovery_kind": None,
                    "value": {"event_id": "event-main", "status": "scheduled"},
                },
            )
        )
        self.assertEqual(second.kind, "finish")
        messages = transport.calls[1]["payload"]["messages"]
        self.assertEqual(
            [message["role"] for message in messages], ["system", "user", "assistant", "tool"]
        )
        tools = transport.calls[0]["payload"]["tools"]
        names = [tool["function"]["name"] for tool in tools]
        self.assertIn("calendar__create_event", names)
        create_schema = next(
            tool["function"]["parameters"]
            for tool in tools
            if tool["function"]["name"] == "messages__send_invitations"
        )
        self.assertEqual(create_schema["properties"]["recipient_count"], {"type": "integer"})
        self.assertNotIn("sk-private-test", repr(backend.call_records))
        self.assertTrue(all(record.reasoning_tokens == 0 for record in backend.call_records))

    def test_parallel_tool_calls_are_serialized_without_a_second_provider_call(self) -> None:
        response = provider_response(
            tool_name="calendar__create_event",
            arguments={"event_id": "event-main", "time": "2026-09-10T10:00"},
        )
        response["choices"][0]["message"]["tool_calls"].append(
            {
                "id": "call-test-2",
                "type": "function",
                "function": {
                    "name": "workspace__resolve_schedule_request",
                    "arguments": '{"request_id":"schedule-main"}',
                },
            }
        )
        transport = FakeTransport([response])
        backend = DeepSeekChatBackend(
            api_key="sk-private-test",
            transport=transport,
        )
        first = backend.generate(self.request(0, None))
        second = backend.generate(
            self.request(
                1,
                {
                    "accepted": True,
                    "status": "ok",
                    "error_code": None,
                    "recovery_kind": None,
                    "value": {"event_id": "event-main"},
                },
            )
        )
        self.assertEqual(first.tool_name, "calendar.create_event")
        self.assertEqual(first.provider_call_count, 1)
        self.assertEqual(second.tool_name, "workspace.resolve_schedule_request")
        self.assertEqual(second.provider_call_count, 0)
        self.assertEqual(second.usage.input_tokens, 0)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(len(backend.call_records), 1)

    def test_unknown_tool_in_parallel_batch_fails_closed(self) -> None:
        response = provider_response(
            tool_name="calendar__create_event",
            arguments={"event_id": "event-main", "time": "2026-09-10T10:00"},
        )
        response["choices"][0]["message"]["tool_calls"].append(
            {
                "id": "call-test-2",
                "type": "function",
                "function": {"name": "made_up", "arguments": "{}"},
            }
        )
        backend = DeepSeekChatBackend(
            api_key="sk-private-test",
            transport=FakeTransport([response]),
        )
        with self.assertRaises(ModelProtocolError):
            backend.generate(self.request(0, None))
        self.assertEqual(backend.call_records[0].status, "error")
        self.assertEqual(backend.call_records[0].error_code, "model_protocol_error")
        self.assertEqual(backend.call_records[0].input_tokens, 100)

    def test_provider_error_is_typed_and_records_no_content(self) -> None:
        def failing_transport(
            url: str,
            payload: dict[str, object],
            api_key: str,
            timeout_seconds: float,
        ) -> dict[str, object]:
            raise DeepSeekBackendError("provider_http_429")

        backend = DeepSeekChatBackend(
            api_key="sk-private-test",
            transport=failing_transport,
        )
        with self.assertRaisesRegex(DeepSeekBackendError, "provider_http_429"):
            backend.generate(self.request(0, None))
        record = backend.call_records[0]
        self.assertEqual(record.status, "error")
        self.assertEqual(record.error_code, "provider_http_429")
        self.assertIsNone(record.response_sha256)
        self.assertNotIn("sk-private-test", repr(record))


if __name__ == "__main__":
    unittest.main()
