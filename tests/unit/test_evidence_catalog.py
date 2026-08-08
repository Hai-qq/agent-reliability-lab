from __future__ import annotations

import unittest
from pathlib import Path

from arl_evidence.catalog import collect_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class EvidenceCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.evidence = collect_evidence(PROJECT_ROOT)

    def test_catalog_has_four_ordered_verified_increments(self) -> None:
        self.assertEqual(
            [item["version"] for item in self.evidence["increments"]],
            ["v0.10", "v0.11", "v0.12", "v0.13"],
        )
        self.assertTrue(self.evidence["validity"]["all_selected_checks_passed"])

    def test_catalog_rechecks_all_saved_trace_pairs(self) -> None:
        self.assertEqual(
            self.evidence["validity"]["formal_repeat_traces"]["file_count"],
            864,
        )
        self.assertTrue(
            all(
                item["integrity"]["trace_manifest"]["formal_repeat_identical"]
                for item in self.evidence["increments"]
            )
        )

    def test_headline_metrics_remain_increment_specific(self) -> None:
        by_version = {item["version"]: item for item in self.evidence["increments"]}
        self.assertEqual(by_version["v0.10"]["headline_rate"], 1.0)
        self.assertEqual(by_version["v0.11"]["headline_rate"], 1.0)
        self.assertEqual(by_version["v0.12"]["headline_rate"], 1.0)
        self.assertEqual(by_version["v0.13"]["headline_rate"], 0.8)
        self.assertIn(
            {"label": "Unsafe commits", "value": "0"},
            by_version["v0.13"]["metrics"],
        )


if __name__ == "__main__":
    unittest.main()
