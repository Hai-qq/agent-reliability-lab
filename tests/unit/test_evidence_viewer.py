from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_evidence.viewer import audit_viewer, build_explorer
from scripts.build_evidence_explorer import validate_output_dir


def fixture() -> dict[str, object]:
    return {
        "metadata": {
            "increment_version": "0.14.0",
            "payload_policy": "aggregate only",
            "external_network_calls": 0,
        },
        "increments": [
            {
                "version": "v0.test",
                "title": "<unsafe title>",
                "category": "runtime",
                "focus": "test focus",
                "claim": "test claim",
                "artifact_href": "../test/summary.json",
                "docs_href": "../../docs/test.md",
                "headline_rate": 1.0,
                "metrics": [{"label": "Cases", "value": "1 / 1"}],
                "integrity": {
                    "summary_sha256": "a" * 64,
                    "source_manifest": {"sha256": "b" * 64, "file_count": 1},
                    "trace_manifest": {"sha256": "c" * 64, "file_count": 1},
                    "passed": True,
                },
            }
        ],
        "validity": {
            "saved_validity": {"passed": True},
            "source_manifests": {"passed": True},
            "formal_repeat_summaries": {"passed": True},
            "formal_repeat_traces": {"file_count": 1, "passed": True},
            "local_synthetic_boundary": {"passed": True},
            "read_only_viewer": {"passed": True},
            "all_selected_checks_passed": True,
        },
        "limitations": ["test only"],
    }


class EvidenceViewerTests(unittest.TestCase):
    def test_viewer_is_deterministic_self_contained_and_escaped(self) -> None:
        first = build_explorer(fixture())
        second = build_explorer(fixture())
        self.assertEqual(first, second)
        self.assertIn("\\u003cunsafe title>", first)
        self.assertNotIn("<unsafe title>", first)
        self.assertTrue(audit_viewer(first)["passed"])

    def test_viewer_audit_rejects_network_or_mutating_markers(self) -> None:
        unsafe = build_explorer(fixture()) + "<script src='https://example.invalid/x.js'>"
        audit = audit_viewer(unsafe)
        self.assertFalse(audit["passed"])
        self.assertIn("https://", audit["forbidden_markers"])

    def test_output_directory_must_not_exist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-evidence-output-") as temporary:
            root = Path(temporary)
            validate_output_dir(root / "new")
            with self.assertRaises(SystemExit):
                validate_output_dir(root)


if __name__ == "__main__":
    unittest.main()
