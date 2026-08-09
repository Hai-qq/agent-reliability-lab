from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_main_study_smoke import validate_paths


class MainStudyCliContractTests(unittest.TestCase):
    def test_outputs_must_be_new_and_separate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-main-study-cli-") as temporary:
            root = Path(temporary)
            validate_paths(root / "summary.json", root / "traces")

            existing_output = root / "existing.json"
            existing_output.write_text("existing", encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_paths(existing_output, root / "new-traces")

            existing_traces = root / "existing-traces"
            existing_traces.mkdir()
            with self.assertRaises(SystemExit):
                validate_paths(root / "new.json", existing_traces)

            with self.assertRaises(SystemExit):
                validate_paths(root / "nested/summary.json", root / "nested")


if __name__ == "__main__":
    unittest.main()
