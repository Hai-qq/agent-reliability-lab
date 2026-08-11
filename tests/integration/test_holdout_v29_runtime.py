from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from arl_holdout_v29.experiment import _trace_audit, _transport_audit_valid, execute_episode
from arl_holdout_v29.specs import ENVIRONMENT_SEEDS, holdout_spec
from arl_mainmodel import experiment as frozen_single
from arl_opencode_v28.backend import OpenCodeQwenV28Backend


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


class HoldoutV29RuntimeTests(unittest.TestCase):
    def test_seeded_holdout_uses_frozen_runtime_and_restores_globals(self) -> None:
        seed = ENVIRONMENT_SEEDS[0]
        spec = holdout_spec("workspace.withdraw-training-session.holdout-v1", seed)
        responses = [
            response(index, tool_name=action.tool_name, arguments=action.arguments)
            for index, action in enumerate(spec.semantic_actions, start=1)
        ]
        responses.append(response(len(responses) + 1))
        backend = OpenCodeQwenV28Backend(
            api_key="v29-integration-secret",
            transport=QueueTransport(responses),
        )
        original_seed = frozen_single.ENVIRONMENT_SEED
        original_catalog = frozen_single.main_pack_catalog_audit
        with tempfile.TemporaryDirectory(prefix="arl-v29-runtime-") as temporary:
            traces_dir = Path(temporary) / "traces"
            traces_dir.mkdir()
            trace_path = traces_dir / "episode.jsonl"
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
            self.assertEqual(record["environment_seed"], seed)
            self.assertTrue(record["episode_id"].startswith("opencode-v29-qwen-"))
            self.assertTrue(_transport_audit_valid(record))
            trace = trace_path.read_text().lower()
            self.assertNotIn("arguments", trace)
            self.assertNotIn("v29-integration-secret", trace)
            self.assertIn(spec.template_id, trace)
            self.assertTrue(_trace_audit(Path(temporary), 1)["passed"])
            with trace_path.open("a", encoding="utf-8") as handle:
                handle.write(spec.visible_task["user_request"])
            self.assertFalse(_trace_audit(Path(temporary), 1)["passed"])
        self.assertEqual(frozen_single.ENVIRONMENT_SEED, original_seed)
        self.assertIs(frozen_single.main_pack_catalog_audit, original_catalog)


if __name__ == "__main__":
    unittest.main()
