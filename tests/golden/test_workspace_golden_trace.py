from __future__ import annotations

import json
import unittest
from pathlib import Path

from arl_validity.golden import verify_golden_suite, verify_trace_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = PROJECT_ROOT / "tests/golden/workspace_multitask_v03.json"


class WorkspaceGoldenTraceTests(unittest.TestCase):
    def test_selected_v03_golden_traces_and_mutations(self) -> None:
        result = verify_golden_suite(PROJECT_ROOT, SPEC_PATH)
        self.assertTrue(result["passed"])
        self.assertEqual(result["trace_count"], 4)
        self.assertTrue(all(trace["passed"] for trace in result["traces"]))
        self.assertTrue(all(case["passed"] for case in result["mutations"].values()))

    def test_truncated_trace_is_rejected(self) -> None:
        spec = json.loads(SPEC_PATH.read_text())
        expected = spec["traces"][0]
        trace = (PROJECT_ROOT / expected["path"]).read_bytes()
        result = verify_trace_bytes(trace.splitlines(keepends=True)[0], expected)
        self.assertFalse(result["passed"])
        self.assertIn("event_count_mismatch", result["errors"])

    def test_non_object_event_is_rejected_without_crashing(self) -> None:
        spec = json.loads(SPEC_PATH.read_text())
        result = verify_trace_bytes(b"[]\n", spec["traces"][0])
        self.assertFalse(result["passed"])
        self.assertIn("event_not_object", result["errors"])


if __name__ == "__main__":
    unittest.main()
