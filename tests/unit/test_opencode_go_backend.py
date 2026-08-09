from __future__ import annotations

import json
import unittest
from typing import Any

from arl_mainstudy.model import ModelRequest, SamplingConfig
from arl_modelpilot.deepseek import PROMPT_CONTRACT_VERSION
from arl_openstudy.backend import OpenCodeGoFlashBackend, OpenCodeGoMiMoBackend
from arl_openstudy.contract import FLASH_BINDING, MIMO_BINDING
from arl_pilot.env import PilotEnvironment
from arl_pilot.specs import SPECS_BY_TEMPLATE_ID


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
        return {
            "id": "response-opencode-unit",
            "model": self.model_id,
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-opencode-unit",
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
                "completion_tokens": 20,
                "prompt_cache_hit_tokens": 40,
                "prompt_cache_miss_tokens": 60,
                "total_tokens": 120,
            },
        }


class OpenCodeGoBackendTests(unittest.TestCase):
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

    def test_flash_disables_thinking_and_mimo_omits_deepseek_control(self) -> None:
        flash_transport = CaptureTransport("deepseek-v4-flash")
        flash = OpenCodeGoFlashBackend(
            api_key="opencode-go-unit-secret",
            transport=flash_transport,
        )
        flash_decision = flash.generate(self._request(FLASH_BINDING))
        self.assertEqual(flash_decision.kind, "tool")
        assert flash_transport.payload is not None
        self.assertEqual(flash_transport.payload["thinking"], {"type": "disabled"})
        self.assertEqual(flash.call_records[0].thinking_mode, "disabled")

        mimo_transport = CaptureTransport("mimo-v2.5")
        mimo = OpenCodeGoMiMoBackend(
            api_key="opencode-go-unit-secret",
            transport=mimo_transport,
        )
        mimo_decision = mimo.generate(self._request(MIMO_BINDING))
        self.assertEqual(mimo_decision.kind, "tool")
        assert mimo_transport.payload is not None
        self.assertNotIn("thinking", mimo_transport.payload)
        self.assertEqual(mimo.call_records[0].thinking_mode, "not_applicable")
        self.assertNotIn("opencode-go-unit-secret", repr(mimo.call_records))


if __name__ == "__main__":
    unittest.main()
