from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_release.bundles import restore_bundles, tree_manifest, verify_bundle_dir
from scripts.manage_artifact_bundles import build

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReleaseBundleRestoreTests(unittest.TestCase):
    def test_build_verify_and_lossless_restore(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-release-restore-") as temporary:
            root = Path(temporary)
            output = root / "release"
            restored = root / "restored"
            build(PROJECT_ROOT, output)
            verification = verify_bundle_dir(output)
            result = restore_bundles(output, restored)
            self.assertEqual(verification["bundle_count"], 4)
            self.assertEqual(len(result["restored_targets"]), 8)
            self.assertEqual(result["restored_file_writes"], 1880)
            for formal, repeat in (
                ("study_runtime_v10/study", "study_runtime_v10_repeat/study"),
                ("parallel_study_v11/study", "parallel_study_v11_repeat/study"),
                ("scenario_pack_v12/traces", "scenario_pack_v12_repeat/traces"),
                ("symbolic_user_v13/traces", "symbolic_user_v13_repeat/traces"),
            ):
                formal_files = tree_manifest(restored / "artifacts" / formal)
                repeat_files = tree_manifest(restored / "artifacts" / repeat)
                self.assertEqual(formal_files, repeat_files)
            with self.assertRaises(FileExistsError):
                restore_bundles(output, restored)

    def test_build_refuses_existing_output_directory(self) -> None:
        with (
            tempfile.TemporaryDirectory(prefix="arl-release-existing-") as temporary,
            self.assertRaises(SystemExit),
        ):
            build(PROJECT_ROOT, Path(temporary))


if __name__ == "__main__":
    unittest.main()
