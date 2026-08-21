from __future__ import annotations

import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.build_evidence_explorer_v2 import ZIP_TIMESTAMP, _bundle_zip
from scripts.build_release_assets import evidence_zip


class DeterministicZipTests(unittest.TestCase):
    def test_archive_order_and_metadata_are_platform_independent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-deterministic-zip-") as temporary:
            root = Path(temporary)
            (root / "aggregate.json").write_bytes(b"{}\n")
            (root / "README.md").write_bytes(b"evidence\n")

            for build_zip in (_bundle_zip, evidence_zip):
                payload = build_zip(root)
                self.assertEqual(payload, build_zip(root))
                with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                    self.assertEqual(archive.namelist(), ["README.md", "aggregate.json"])
                    for member in archive.infolist():
                        self.assertEqual(member.compress_type, zipfile.ZIP_STORED)
                        self.assertEqual(member.create_system, 3)
                        self.assertEqual(member.date_time, ZIP_TIMESTAMP)
                        self.assertEqual(member.external_attr, 0o100644 << 16)


if __name__ == "__main__":
    unittest.main()
