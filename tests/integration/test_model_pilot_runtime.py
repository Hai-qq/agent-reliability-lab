from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from arl_modelpilot.deepseek import DeepSeekBackendError, DeepSeekChatBackend
from arl_modelpilot.experiment import _execute_episode
from arl_pilot.specs import SPECS_BY_TEMPLATE_ID


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
                        "name": tool_name,
                        "arguments": json.dumps(arguments or {}),
                    },
                }
            ],
        }
        finish_reason = "tool_calls"
    return {
        "id": f"response-{index}",
        "model": "deepseek-v4-flash",
        "system_fingerprint": "fp-integration-test",
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
        self.responses = responses

    def __call__(
        self,
        url: str,
        payload: dict[str, Any],
        api_key: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        return self.responses.pop(0)


class ModelPilotRuntimeIntegrationTests(unittest.TestCase):
    def test_digest_only_deepseek_policy_drives_clean_r2_episode(self) -> None:
        spec = SPECS_BY_TEMPLATE_ID["workspace.schedule-meeting.main-v1"]
        responses = [
            response(
                1,
                tool_name="calendar__create_event",
                arguments={"event_id": "event-main", "time": "2026-09-10T10:00"},
            ),
            response(
                2,
                tool_name="messages__send_invitations",
                arguments={"event_id": "event-main", "recipient_count": 2},
            ),
            response(
                3,
                tool_name="workspace__resolve_schedule_request",
                arguments={"request_id": "schedule-main"},
            ),
            response(4),
        ]
        backend = DeepSeekChatBackend(
            api_key="sk-integration-secret",
            transport=QueueTransport(responses),
        )
        with tempfile.TemporaryDirectory(prefix="arl-model-pilot-integration-") as temporary:
            trace_path = Path(temporary) / "episode.jsonl"
            record = _execute_episode(
                spec=spec,
                runtime_name="r2_reliable",
                condition="clean",
                sampling_trial=0,
                backend=backend,
                trace_path=trace_path,
            )
            self.assertTrue(record["evaluation"]["safe_success"])
            self.assertTrue(record["execution"]["model_declared_finished"])
            self.assertEqual(record["policy"]["model_calls"], 4)
            self.assertEqual(record["external_network_calls"], 4)
            self.assertEqual(record["policy"]["input_tokens"], 200)
            trace = trace_path.read_text(encoding="utf-8").lower()
            self.assertNotIn("arguments", trace)
            self.assertNotIn("event-main", trace)
            self.assertNotIn("sk-integration-secret", trace)

    def test_provider_failure_is_retained_as_failed_episode(self) -> None:
        spec = SPECS_BY_TEMPLATE_ID["workspace.schedule-meeting.main-v1"]

        def fail(
            url: str,
            payload: dict[str, Any],
            api_key: str,
            timeout_seconds: float,
        ) -> dict[str, Any]:
            raise DeepSeekBackendError("provider_http_503")

        backend = DeepSeekChatBackend(api_key="sk-integration-secret", transport=fail)
        with tempfile.TemporaryDirectory(prefix="arl-model-pilot-error-") as temporary:
            trace_path = Path(temporary) / "episode.jsonl"
            record = _execute_episode(
                spec=spec,
                runtime_name="r2_reliable",
                condition="clean",
                sampling_trial=0,
                backend=backend,
                trace_path=trace_path,
            )
            self.assertFalse(record["evaluation"]["safe_success"])
            self.assertEqual(record["execution"]["failure_code"], "provider_http_503")
            self.assertEqual(record["external_network_calls"], 1)
            self.assertEqual(record["provider"]["calls"][0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
