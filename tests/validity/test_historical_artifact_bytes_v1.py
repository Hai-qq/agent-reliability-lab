from __future__ import annotations

import hashlib
import io
import json
import subprocess
import tarfile
import unittest
from pathlib import Path


class HistoricalArtifactBytesTests(unittest.TestCase):
    def test_all_baseline_tracked_artifact_bytes_are_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[2]
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "artifacts"], cwd=root, check=True)
        archive = subprocess.check_output(
            ["git", "archive", "--format=tar", "HEAD", "artifacts"], cwd=root
        )
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as handle:
            blobs = {
                member.name: extracted.read()
                for member in handle.getmembers()
                if member.isfile() and (extracted := handle.extractfile(member)) is not None
            }
        files = {
            path: hashlib.sha256(payload).hexdigest() for path, payload in sorted(blobs.items())
        }
        payload = json.dumps(
            files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(len(blobs), 464)
        self.assertEqual(sum(len(item) for item in blobs.values()), 13_968_430)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "4f9412d42f312eeec57d77bb2e5b6da49162acc5fc20d58707d396b1eb3abe5a",
        )


if __name__ == "__main__":
    unittest.main()
