from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from arl_dualmode.deepseek import DeepSeekFlashThinkingBackend
from arl_dualmode.experiment import execute_thinking_episode
from arl_mainmodel import experiment as frozen_single
from arl_mainpack.specs import MAIN_SPECS_BY_TEMPLATE_ID


def response(
    index: int,
    *,
    tool_name: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": "done",
        "reasoning_content": "synthetic reasoning",
    }
    finish_reason = "stop"
    if tool_name is not None:
        message = {
            "role": "assistant",
            "content": None,
            "reasoning_content": "synthetic reasoning",
            "tool_calls": [
                {
                    "id": f"call-{index}",
                    "type": "function",
                    "function": {
                        "name": tool_name.replace(".", "__"),
                        "arguments": json.dumps(arguments or {}),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    return {
        "id": f"response-{index}",
        "model": "deepseek-v4-flash",
        "system_fingerprint": "fp-dual-mode-integration-test",
        "choices": [{"finish_reason": finish_reason, "index": 0, "message": message}],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "prompt_cache_hit_tokens": 10,
            "prompt_cache_miss_tokens": 40,
            "total_tokens": 75,
            "completion_tokens_details": {"reasoning_tokens": 20},
        },
    }


class QueueTransport:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)

    def __call__(
        self,
        url: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        return self.responses.pop(0)


class DualModeRuntimeTests(unittest.TestCase):
    def test_thinking_mode_uses_same_runtime_and_restores_frozen_globals(self) -> None:
        spec = MAIN_SPECS_BY_TEMPLATE_ID["workspace.cancel-meeting.main-v1"]
        responses = [
            response(index, tool_name=action.tool_name, arguments=action.arguments)
            for index, action in enumerate(spec.semantic_actions, start=1)
        ]
        responses.append(response(len(responses) + 1))
        backend = DeepSeekFlashThinkingBackend(
            api_key="sk-dual-mode-integration-test",
            transport=QueueTransport(responses),
        )
        original_binding = frozen_single.DEEPSEEK_FLASH_BINDING
        original_mode = frozen_single.THINKING_MODE
        with tempfile.TemporaryDirectory(prefix="arl-dual-mode-integration-") as temporary:
            trace_path = Path(temporary) / "episode.jsonl"
            record = execute_thinking_episode(
                spec=spec,
                runtime_name="r2_reliable",
                condition="clean",
                sampling_trial=0,
                backend=backend,
                trace_path=trace_path,
            )
            self.assertTrue(record["evaluation"]["safe_success"])
            self.assertTrue(record["episode_id"].startswith("flash-thinking-"))
            self.assertEqual(record["provider"]["thinking_mode"], "enabled")
            self.assertTrue(
                all(call["thinking_mode"] == "enabled" for call in record["provider"]["calls"])
            )
            trace = trace_path.read_text(encoding="utf-8").lower()
            self.assertNotIn("arguments", trace)
            self.assertNotIn("synthetic reasoning", trace)
        self.assertIs(frozen_single.DEEPSEEK_FLASH_BINDING, original_binding)
        self.assertEqual(frozen_single.THINKING_MODE, original_mode)


if __name__ == "__main__":
    unittest.main()
