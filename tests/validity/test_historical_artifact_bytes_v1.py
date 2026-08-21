from __future__ import annotations

import hashlib
import io
import json
import subprocess
import unittest
from pathlib import Path


class HistoricalArtifactBytesTests(unittest.TestCase):
    def test_all_baseline_tracked_artifact_bytes_are_unchanged(self) -> None:
        root = Path(__file__).resolve().parents[2]
        subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "artifacts"], cwd=root, check=True)
        tree = subprocess.check_output(
            ["git", "ls-tree", "-r", "-z", "HEAD", "--", "artifacts"], cwd=root
        )
        entries = []
        for record in (item for item in tree.split(b"\0") if item):
            metadata, path = record.split(b"\t", 1)
            _mode, object_type, object_id = metadata.split()
            self.assertEqual(object_type, b"blob")
            entries.append((path.decode("utf-8"), object_id))
        batch = subprocess.check_output(
            ["git", "cat-file", "--batch"],
            cwd=root,
            input=b"".join(object_id + b"\n" for _path, object_id in entries),
        )
        stream = io.BytesIO(batch)
        blobs: dict[str, bytes] = {}
        for path, object_id in entries:
            response_id, object_type, size = stream.readline().rstrip(b"\n").split()
            self.assertEqual(response_id, object_id)
            self.assertEqual(object_type, b"blob")
            blobs[path] = stream.read(int(size))
            self.assertEqual(stream.read(1), b"\n")
        self.assertEqual(stream.read(), b"")
        files = {
            path: hashlib.sha256(payload).hexdigest() for path, payload in sorted(blobs.items())
        }
        payload = json.dumps(
            files, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(len(blobs), 464)
        self.assertEqual(sum(len(item) for item in blobs.values()), 13_968_008)
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "5d80a1b067fc17bc7c8a21772386037d049eb4d8253aafbb1bcee1e9176a2922",
        )


if __name__ == "__main__":
    unittest.main()
