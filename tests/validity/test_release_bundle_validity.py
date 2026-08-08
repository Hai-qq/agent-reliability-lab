from __future__ import annotations

import unittest
from pathlib import Path

from arl_release.bundles import build_bundle_catalog, inspect_bundle

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReleaseBundleValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest, cls.payloads = build_bundle_catalog(PROJECT_ROOT)

    def test_all_formal_repeat_trees_are_identical(self) -> None:
        self.assertTrue(self.manifest["validity"]["all_selected_checks_passed"])
        self.assertEqual(
            self.manifest["validity"]["formal_repeat_trees"]["file_count"],
            940,
        )
        self.assertTrue(all(item["formal_repeat_identical"] for item in self.manifest["bundles"]))

    def test_four_bundles_are_lossless_and_below_public_size_limit(self) -> None:
        self.assertEqual(len(self.payloads), 4)
        for record in self.manifest["bundles"]:
            payload = self.payloads[record["bundle_file"]]
            inspected = inspect_bundle(payload)
            self.assertEqual(inspected["files"], record["files"])
            self.assertLess(len(payload), 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
