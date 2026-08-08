from __future__ import annotations

import unittest
from pathlib import Path

from arl_evidence.viewer import audit_viewer
from scripts.build_evidence_explorer import build_outputs

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EvidenceExplorerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence, cls.document = build_outputs(PROJECT_ROOT)

    def test_build_outputs_are_deterministic_and_source_linked(self) -> None:
        repeated_evidence, repeated_document = build_outputs(PROJECT_ROOT)
        self.assertEqual(self.evidence, repeated_evidence)
        self.assertEqual(self.document, repeated_document)
        self.assertEqual(
            self.evidence["metadata"]["source_manifest"]["sha256"],
            repeated_evidence["metadata"]["source_manifest"]["sha256"],
        )

    def test_document_contains_all_product_increments_and_local_links(self) -> None:
        for expected in (
            "Resumable Study Runtime",
            "Parallel Lease Coordinator",
            "Audited Scenario Pack",
            "Stateful Authorization",
        ):
            self.assertIn(expected, self.document)
        self.assertIn("../symbolic_user_v13/summary.json", self.document)
        self.assertIn("../../docs/symbolic-user-v13.md", self.document)

    def test_document_is_read_only_and_under_public_size_limit(self) -> None:
        self.assertTrue(audit_viewer(self.document)["passed"])
        self.assertLess(len(self.document.encode("utf-8")), 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
