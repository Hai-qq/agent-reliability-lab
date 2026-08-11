from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from arl_mainmodel import experiment as frozen_single
from arl_mainpack.specs import MAIN_SPECS_BY_TEMPLATE_ID
from arl_opencode_v28.backend import OpenCodeQwenV28Backend
from arl_opencode_v28.experiment import _transport_audit_valid, execute_episode


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
        "model": "qwen3.7-plus",
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
        self.audits: list[dict[str, Any]] = []

    def __call__(
        self,
        url: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        self.audits.append(
            {
                "logical_call_index": len(self.audits),
                "attempt_count": 1,
                "retry_error_codes": [],
                "final_status": "ok",
                "final_error_code": None,
            }
        )
        return self.responses.pop(0)


class OpenCodeGoV28RuntimeTests(unittest.TestCase):
    def test_qwen_uses_frozen_runtime_and_restores_module_globals(self) -> None:
        spec = MAIN_SPECS_BY_TEMPLATE_ID["workspace.cancel-meeting.main-v1"]
        responses = [
            response(index, tool_name=action.tool_name, arguments=action.arguments)
            for index, action in enumerate(spec.semantic_actions, start=1)
        ]
        responses.append(response(len(responses) + 1))
        backend = OpenCodeQwenV28Backend(
            api_key="opencode-go-v28-integration-secret",
            transport=QueueTransport(responses),
        )
        original_binding = frozen_single.DEEPSEEK_FLASH_BINDING
        with tempfile.TemporaryDirectory(prefix="arl-opencode-v28-integration-") as temporary:
            trace_path = Path(temporary) / "episode.jsonl"
            record = execute_episode(
                spec=spec,
                slot_id="qwen",
                runtime_name="r2_reliable",
                condition="clean",
                sampling_trial=0,
                backend=backend,
                trace_path=trace_path,
            )
            self.assertTrue(record["evaluation"]["safe_success"])
            self.assertEqual(record["model_slot"], "qwen")
            self.assertTrue(record["episode_id"].startswith("opencode-v28-qwen-"))
            self.assertEqual(record["provider"]["logical_call_count"], len(responses))
            self.assertEqual(record["provider"]["transport_retry_count"], 0)
            self.assertEqual(record["external_network_calls"], len(responses))
            trace = trace_path.read_text().lower()
            self.assertNotIn("arguments", trace)
            self.assertNotIn("opencode-go-v28-integration-secret", trace)
        self.assertIs(frozen_single.DEEPSEEK_FLASH_BINDING, original_binding)

    def test_local_protocol_error_does_not_corrupt_transport_audit(self) -> None:
        spec = MAIN_SPECS_BY_TEMPLATE_ID["workspace.cancel-meeting.main-v1"]
        backend = OpenCodeQwenV28Backend(
            api_key="opencode-go-v28-integration-secret",
            transport=QueueTransport(
                [response(1, tool_name="unknown.tool", arguments={"value": "synthetic"})]
            ),
        )
        with tempfile.TemporaryDirectory(prefix="arl-opencode-v28-protocol-") as temporary:
            record = execute_episode(
                spec=spec,
                slot_id="qwen",
                runtime_name="r2_reliable",
                condition="clean",
                sampling_trial=0,
                backend=backend,
                trace_path=Path(temporary) / "episode.jsonl",
            )
        self.assertEqual(record["execution"]["failure_code"], "model_protocol_error")
        self.assertEqual(record["provider"]["calls"][0]["error_code"], "model_protocol_error")
        self.assertEqual(record["provider"]["transport_audit"][0]["final_status"], "ok")
        self.assertTrue(_transport_audit_valid(record))


if __name__ == "__main__":
    unittest.main()
