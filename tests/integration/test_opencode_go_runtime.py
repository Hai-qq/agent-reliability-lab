from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from arl_mainmodel import experiment as frozen_single
from arl_mainpack.specs import MAIN_SPECS_BY_TEMPLATE_ID
from arl_openstudy.backend import OpenCodeGoMiMoBackend
from arl_openstudy.experiment import execute_openstudy_episode


def response(
    index: int,
    *,
    tool_name: str | None = None,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": "done"}
    finish_reason = "stop"
    if tool_name is not None:
        message = {
            "role": "assistant",
            "content": None,
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
        "model": "mimo-v2.5",
        "choices": [{"finish_reason": finish_reason, "index": 0, "message": message}],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 10,
            "prompt_cache_hit_tokens": 10,
            "prompt_cache_miss_tokens": 40,
            "total_tokens": 60,
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


class OpenCodeGoRuntimeTests(unittest.TestCase):
    def test_mimo_uses_frozen_runtime_and_restores_module_globals(self) -> None:
        spec = MAIN_SPECS_BY_TEMPLATE_ID["workspace.cancel-meeting.main-v1"]
        responses = [
            response(index, tool_name=action.tool_name, arguments=action.arguments)
            for index, action in enumerate(spec.semantic_actions, start=1)
        ]
        responses.append(response(len(responses) + 1))
        backend = OpenCodeGoMiMoBackend(
            api_key="opencode-go-integration-secret",
            transport=QueueTransport(responses),
        )
        original_binding = frozen_single.DEEPSEEK_FLASH_BINDING
        with tempfile.TemporaryDirectory(prefix="arl-opencode-integration-") as temporary:
            trace_path = Path(temporary) / "episode.jsonl"
            record = execute_openstudy_episode(
                spec=spec,
                slot_id="mimo",
                runtime_name="r2_reliable",
                condition="clean",
                sampling_trial=0,
                backend=backend,
                trace_path=trace_path,
            )
            self.assertTrue(record["evaluation"]["safe_success"])
            self.assertEqual(record["model_slot"], "mimo")
            self.assertTrue(record["episode_id"].startswith("opencode-mimo-"))
            self.assertEqual(record["provider"]["gateway"], "opencode-go")
            trace = trace_path.read_text().lower()
            self.assertNotIn("arguments", trace)
            self.assertNotIn("opencode-go-integration-secret", trace)
        self.assertIs(frozen_single.DEEPSEEK_FLASH_BINDING, original_binding)


if __name__ == "__main__":
    unittest.main()
