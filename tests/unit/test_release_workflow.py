from __future__ import annotations

import unittest
from pathlib import Path


class ReleaseWorkflowTests(unittest.TestCase):
    def test_verified_wheel_is_installed_before_release_metadata_runs(self) -> None:
        root = Path(__file__).resolve().parents[2]
        workflow = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        verify = "python scripts/verify_clean_wheel.py release-assets/*.whl"
        install = "python -m pip install --no-deps release-assets/*.whl"
        metadata = "python scripts/build_release_assets.py"

        self.assertIn(verify, workflow)
        self.assertIn(install, workflow)
        self.assertIn(metadata, workflow)
        self.assertLess(workflow.index(verify), workflow.index(install))
        self.assertLess(workflow.index(install), workflow.index(metadata))


if __name__ == "__main__":
    unittest.main()
