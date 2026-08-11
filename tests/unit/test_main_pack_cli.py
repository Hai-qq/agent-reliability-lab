from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_main_pack_preflight import validate_paths


class MainPackCliTests(unittest.TestCase):
    def test_outputs_must_be_new_and_separate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-main-pack-cli-") as temporary:
            root = Path(temporary)
            validate_paths(root / "summary.json", root / "traces")

            output = root / "existing.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_paths(output, root / "new-traces")

            traces = root / "existing-traces"
            traces.mkdir()
            with self.assertRaises(SystemExit):
                validate_paths(root / "new.json", traces)

            with self.assertRaises(SystemExit):
                validate_paths(root / "nested/summary.json", root / "nested")


if __name__ == "__main__":
    unittest.main()
