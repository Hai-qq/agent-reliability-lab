from __future__ import annotations

import hashlib
import json
import subprocess
import unittest
from pathlib import Path


class HistoricalArtifactBytesTests(unittest.TestCase):
    def test_all_baseline_tracked_artifact_bytes_are_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[2]
        raw = subprocess.check_output(["git", "ls-files", "-z", "artifacts"], cwd=root)
        relative_paths = [Path(item.decode("utf-8")) for item in raw.split(b"\0") if item]
        files = {
            path.as_posix(): hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in sorted(relative_paths)
        }
        payload = json.dumps(
            files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(len(relative_paths), 464)
        self.assertEqual(sum((root / path).stat().st_size for path in relative_paths), 13_968_430)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "4f9412d42f312eeec57d77bb2e5b6da49162acc5fc20d58707d396b1eb3abe5a",
        )


if __name__ == "__main__":
    unittest.main()
