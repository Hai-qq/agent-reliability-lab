from __future__ import annotations

import unittest
from pathlib import Path

from scripts.build_evidence_explorer import build_outputs

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EvidenceExplorerValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence, cls.document = build_outputs(PROJECT_ROOT)

    def test_all_input_integrity_and_boundary_gates_pass(self) -> None:
        validity = self.evidence["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(validity["source_manifests"]["passed"])
        self.assertTrue(validity["formal_repeat_summaries"]["passed"])
        self.assertTrue(validity["formal_repeat_traces"]["passed"])
        self.assertTrue(validity["local_synthetic_boundary"]["passed"])
        self.assertTrue(validity["read_only_viewer"]["passed"])

    def test_catalog_contains_no_raw_session_or_trace_payloads(self) -> None:
        serialized = self.document
        for marker in (
            '"sessions":',
            '"episodes":',
            '"events":',
            '"selection":',
            '"arguments":',
            "synthetic-",
        ):
            self.assertNotIn(marker, serialized)


if __name__ == "__main__":
    unittest.main()
