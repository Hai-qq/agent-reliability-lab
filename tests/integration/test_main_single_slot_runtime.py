from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from arl_mainmodel.experiment import execute_model_episode
from arl_mainpack.specs import MAIN_SPECS_BY_TEMPLATE_ID
from arl_modelpilot.deepseek import DeepSeekChatBackend


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
        "model": "deepseek-v4-flash",
        "system_fingerprint": "fp-main-single-integration-test",
        "choices": [{"finish_reason": finish_reason, "index": 0, "message": message}],
        "usage": {
            "prompt_tokens": 50,
            "completion_tokens": 5,
            "prompt_cache_hit_tokens": 10,
            "prompt_cache_miss_tokens": 40,
            "total_tokens": 55,
            "completion_tokens_details": {"reasoning_tokens": 0},
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


class MainSingleSlotRuntimeTests(unittest.TestCase):
    def test_deepseek_contract_drives_a_new_main_pack_fixture(self) -> None:
        spec = MAIN_SPECS_BY_TEMPLATE_ID["workspace.cancel-meeting.main-v1"]
        responses = [
            response(index, tool_name=action.tool_name, arguments=action.arguments)
            for index, action in enumerate(spec.semantic_actions, start=1)
        ]
        responses.append(response(len(responses) + 1))
        backend = DeepSeekChatBackend(
            api_key="sk-main-single-integration-secret",
            transport=QueueTransport(responses),
        )
        with tempfile.TemporaryDirectory(prefix="arl-main-single-integration-") as temporary:
            trace_path = Path(temporary) / "episode.jsonl"
            record = execute_model_episode(
                spec=spec,
                runtime_name="r2_reliable",
                condition="clean",
                sampling_trial=0,
                backend=backend,
                trace_path=trace_path,
            )
            self.assertTrue(record["evaluation"]["safe_success"])
            self.assertTrue(record["execution"]["model_declared_finished"])
            self.assertEqual(record["policy"]["model_calls"], len(responses))
            self.assertEqual(record["external_network_calls"], len(responses))
            trace = trace_path.read_text(encoding="utf-8").lower()
            self.assertNotIn("arguments", trace)
            self.assertNotIn("event-cancel", trace)
            self.assertNotIn("sk-main-single-integration-secret", trace)


if __name__ == "__main__":
    unittest.main()
