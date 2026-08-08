from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arl_study.viewer import build_trace_viewer


class StudyViewerTests(unittest.TestCase):
    def test_viewer_is_deterministic_self_contained_and_escaped(self) -> None:
        summary = {
            "metadata": {
                "increment_version": "0.10.0",
                "study_id": "viewer-unit",
                "trace_payload_policy": "digests and typed metadata only",
                "model_calls": 0,
                "external_network_calls": 0,
            },
            "progress": {"completed_count": 1, "total_count": 1},
            "resume": {"preexisting_results_preserved": True},
            "aggregate": {"compatible_recovery_rate_delta": 1.0},
            "episodes": [
                {
                    "episode_id": "episode-1",
                    "domain": "retail",
                    "task_id": "<unsafe-task>",
                    "seed": 0,
                    "runtime": "r2_contract_guarded",
                    "condition": "compatible_conflict",
                    "initial_state_hash": "a" * 64,
                    "final_state_hash": "b" * 64,
                    "trace_file": "episode-1.jsonl",
                    "trace_sha256": "c" * 64,
                    "execution": {
                        "failure_code": None,
                        "conflict_count": 1,
                        "conflict_probe_count": 1,
                        "conflict_rebase_count": 1,
                        "conflict_abort_count": 0,
                        "compensation_contract_attempt_count": 0,
                        "compensation_contract_success_count": 0,
                    },
                    "evaluation": {"task_success": True, "safe_success": True},
                }
            ],
        }
        event = {
            "event_id": "episode-1:0001",
            "parent_event_id": None,
            "timestamp_logical": 1,
            "actor": "runtime",
            "event_type": "state_conflict_rebased",
            "tool_name": "retail.resolve_purchase_request",
            "error_code": None,
            "fault_id": None,
            "input_digest": "d" * 64,
            "output_digest": "e" * 64,
            "state_hash_before": "a" * 64,
            "state_hash_after": "b" * 64,
        }
        with tempfile.TemporaryDirectory(prefix="arl-viewer-unit-") as temporary:
            traces = Path(temporary)
            (traces / "episode-1.jsonl").write_text(
                json.dumps(event, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            first = build_trace_viewer(summary, traces)
            second = build_trace_viewer(summary, traces)
        self.assertEqual(first, second)
        self.assertIn('id="arl-data"', first)
        self.assertIn("state_conflict_rebased", first)
        self.assertIn("\\u003cunsafe-task>", first)
        self.assertNotIn("<unsafe-task>", first)
        self.assertNotIn("<script src=", first)
        self.assertNotIn("fetch(", first)
        self.assertNotIn("XMLHttpRequest", first)
        self.assertNotIn("WebSocket", first)


if __name__ == "__main__":
    unittest.main()
