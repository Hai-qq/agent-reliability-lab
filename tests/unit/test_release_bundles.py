from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from arl_release.bundles import (
    ZIP_MODE,
    ZIP_TIMESTAMP,
    build_zip,
    inspect_bundle,
    tree_manifest,
)


class ReleaseBundleTests(unittest.TestCase):
    def test_zip_is_deterministic_sorted_and_metadata_fixed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-release-unit-") as temporary:
            root = Path(temporary)
            (root / "nested").mkdir()
            (root / "z.jsonl").write_text("z\n", encoding="utf-8")
            (root / "nested/a.json").write_text('{"a": 1}\n', encoding="utf-8")
            files = tree_manifest(root)
            first = build_zip(root, files)
            second = build_zip(root, files)
        self.assertEqual(first, second)
        inspected = inspect_bundle(first)
        self.assertEqual(inspected["files"], files)
        with zipfile.ZipFile(io.BytesIO(first)) as archive:
            self.assertEqual(
                [item.filename for item in archive.infolist()],
                ["nested/a.json", "z.jsonl"],
            )
            self.assertTrue(all(item.date_time == ZIP_TIMESTAMP for item in archive.infolist()))
            self.assertTrue(
                all(item.external_attr >> 16 == ZIP_MODE for item in archive.infolist())
            )

    def test_empty_source_is_rejected(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="arl-release-empty-") as temporary,
            self.assertRaises(ValueError),
        ):
            tree_manifest(Path(temporary))

    def test_unsafe_member_is_rejected(self) -> None:
        output = io.BytesIO()
        with zipfile.ZipFile(output, mode="w") as archive:
            archive.writestr("../outside.json", "unsafe")
        with self.assertRaises(ValueError):
            inspect_bundle(output.getvalue())


if __name__ == "__main__":
    unittest.main()
