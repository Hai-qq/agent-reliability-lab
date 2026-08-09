from __future__ import annotations

import json
import unittest
from typing import Any

from arl_opencode_v28.backend import OpenCodeQwenV28Backend
from arl_opencode_v28.probe import PROBE_VALUE, run_qwen_protocol_probe


def response(index: int, *, tool: bool) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": "complete"}
    finish_reason = "stop"
    if tool:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": f"call-{index}",
                    "type": "function",
                    "function": {
                        "name": "probe__echo",
                        "arguments": json.dumps({"value": PROBE_VALUE}),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    return {
        "id": f"response-{index}",
        "model": "qwen3.7-plus",
        "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 100,
            "total_tokens": 120,
        },
    }


class QueueTransport:
    def __init__(self) -> None:
        self.responses = [response(1, tool=True), response(2, tool=False)]

    def __call__(
        self,
        url: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        return self.responses.pop(0)


class OpenCodeGoV28ProbeTests(unittest.TestCase):
    def test_two_turn_probe_persists_only_digests_and_typed_metadata(self) -> None:
        backend = OpenCodeQwenV28Backend(api_key="unit-secret", transport=QueueTransport())
        result = run_qwen_protocol_probe(
            backend,
            catalog_attestation={"passed": True, "response_sha256": "0" * 64},
        )
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["provider_calls"]), 2)
        self.assertEqual(result["decisions"]["first_tool_name"], "probe.echo")
        self.assertEqual(result["decisions"]["second_kind"], "finish")
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn(PROBE_VALUE, serialized)
        self.assertNotIn("unit-secret", serialized)


if __name__ == "__main__":
    unittest.main()
