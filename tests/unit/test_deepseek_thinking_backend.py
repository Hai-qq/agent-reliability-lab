from __future__ import annotations

import json
import unittest
from typing import Any

from arl_dualmode.contract import FLASH_THINKING_HIGH_BINDING
from arl_dualmode.deepseek import DeepSeekFlashThinkingBackend
from arl_mainstudy.model import ModelRequest, SamplingConfig
from arl_modelpilot.deepseek import PROMPT_CONTRACT_VERSION
from arl_pilot.env import PilotEnvironment
from arl_pilot.specs import SPECS_BY_TEMPLATE_ID


class CaptureTransport:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.payload: dict[str, Any] | None = None

    def __call__(
        self,
        url: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.payload = payload
        return self.response


class DeepSeekThinkingBackendTests(unittest.TestCase):
    def test_request_enables_thinking_high_and_records_reasoning_tokens(self) -> None:
        spec = SPECS_BY_TEMPLATE_ID["workspace.schedule-meeting.main-v1"]
        environment = PilotEnvironment(spec, "clean")
        try:
            observation = environment.reset(spec.task_id, 0).as_dict()
        finally:
            environment.close()
        response = {
            "id": "response-thinking-test",
            "model": "deepseek-v4-flash",
            "system_fingerprint": "fp-thinking-test",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "reasoning_content": "not persisted by the adapter",
                        "tool_calls": [
                            {
                                "id": "call-thinking-test",
                                "type": "function",
                                "function": {
                                    "name": "calendar__create_event",
                                    "arguments": json.dumps(
                                        {
                                            "event_id": "event-main",
                                            "time": "2026-09-10T10:00",
                                        }
                                    ),
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 70,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 60,
                "total_tokens": 170,
                "completion_tokens_details": {"reasoning_tokens": 60},
            },
        }
        transport = CaptureTransport(response)
        backend = DeepSeekFlashThinkingBackend(
            api_key="sk-thinking-unit-test",
            transport=transport,
        )
        decision = backend.generate(
            ModelRequest(
                prompt_contract_version=PROMPT_CONTRACT_VERSION,
                binding=FLASH_THINKING_HIGH_BINDING,
                task_id=spec.task_id,
                turn_index=0,
                observation=observation,
                feedback=None,
                tools=spec.model_tools,
                sampling=SamplingConfig(0.0, 1.0, 1_024, None),
            )
        )
        self.assertEqual(decision.kind, "tool")
        assert transport.payload is not None
        self.assertEqual(transport.payload["thinking"], {"type": "enabled"})
        self.assertEqual(transport.payload["reasoning_effort"], "high")
        self.assertEqual(backend.call_records[0].thinking_mode, "enabled")
        self.assertEqual(backend.call_records[0].reasoning_tokens, 60)
        self.assertNotIn("reasoning_content", repr(backend.call_records))


if __name__ == "__main__":
    unittest.main()
