from __future__ import annotations

import json
import unittest
from collections import defaultdict
from typing import Any
from unittest.mock import patch

from arl_replication_v30.backend import (
    OpenCodeFlashV30Backend,
    OpenCodeProV30Backend,
)
from arl_replication_v30.contract import MODEL_BINDINGS
from arl_replication_v30.probe import run_protocol_probe


def response(model_id: str, index: int, *, value: str, tool: bool) -> dict[str, Any]:
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
                        "arguments": json.dumps({"value": value}),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    return {
        "id": f"response-{index}",
        "model": model_id,
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


class ReplicationV30ProbeTests(unittest.TestCase):
    def test_three_repetitions_per_model_are_digest_only(self) -> None:
        counters: defaultdict[str, int] = defaultdict(int)

        def factory(
            slot_id: str,
            *,
            api_key: str,
            timeout_seconds: float,
        ) -> OpenCodeFlashV30Backend | OpenCodeProV30Backend:
            del timeout_seconds
            repetition = counters[slot_id]
            counters[slot_id] += 1
            value = f"arl-v030-synthetic-probe-{slot_id}-r{repetition}"
            binding = MODEL_BINDINGS[slot_id]
            transport = QueueTransport(
                [
                    response(binding.model_id, 1, value=value, tool=True),
                    response(binding.model_id, 2, value=value, tool=False),
                ]
            )
            backend_type = OpenCodeFlashV30Backend if slot_id == "flash" else OpenCodeProV30Backend
            return backend_type(api_key=api_key, transport=transport)

        with patch("arl_replication_v30.probe.backend_for_slot", side_effect=factory):
            result = run_protocol_probe(
                api_key="v30-probe-secret",
                timeout_seconds=5.0,
                catalog_attestation={"passed": True, "response_sha256": "0" * 64},
            )
        self.assertTrue(result["passed"])
        self.assertEqual(result["logical_call_count"], 12)
        self.assertEqual(result["repetitions_per_model"], 3)
        self.assertEqual(counters, {"flash": 3, "pro": 3})
        self.assertTrue(all(len(item["repetitions"]) == 3 for item in result["by_model"].values()))
        serialized = json.dumps(result, sort_keys=True)
        self.assertNotIn("arl-v030-synthetic-probe", serialized)
        self.assertNotIn("v30-probe-secret", serialized)


if __name__ == "__main__":
    unittest.main()
