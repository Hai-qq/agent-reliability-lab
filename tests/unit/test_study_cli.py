from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from scripts.run_resilience_study import validate_run_arguments


def arguments(root: Path, **overrides: object) -> argparse.Namespace:
    values = {
        "workspace": root / "study",
        "output": root / "summary.json",
        "resume": False,
        "stop_after": 13,
        "viewer": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class StudyCliContractTests(unittest.TestCase):
    def test_interrupted_and_complete_contracts_are_distinct(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-cli-") as temporary:
            root = Path(temporary)
            validate_run_arguments(arguments(root), job_count=36)
            validate_run_arguments(
                arguments(root, stop_after=None, viewer=root / "viewer.html"),
                job_count=36,
            )
            with self.assertRaises(SystemExit):
                validate_run_arguments(arguments(root, stop_after=None), job_count=36)
            with self.assertRaises(SystemExit):
                validate_run_arguments(
                    arguments(root, viewer=root / "viewer.html"),
                    job_count=36,
                )

    def test_resume_requires_viewer_and_forbids_stop_limit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-cli-resume-") as temporary:
            root = Path(temporary)
            validate_run_arguments(
                arguments(root, resume=True, stop_after=None, viewer=root / "viewer.html"),
                job_count=36,
            )
            with self.assertRaises(SystemExit):
                validate_run_arguments(
                    arguments(root, resume=True, stop_after=None),
                    job_count=36,
                )
            with self.assertRaises(SystemExit):
                validate_run_arguments(
                    arguments(root, resume=True, viewer=root / "viewer.html"),
                    job_count=36,
                )

    def test_outputs_cannot_collide_with_workspace_or_each_other(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-cli-paths-") as temporary:
            root = Path(temporary)
            with self.assertRaises(SystemExit):
                validate_run_arguments(
                    arguments(root, output=root / "study/summary.json"),
                    job_count=36,
                )
            with self.assertRaises(SystemExit):
                validate_run_arguments(
                    arguments(
                        root,
                        stop_after=None,
                        output=root / "same.html",
                        viewer=root / "same.html",
                    ),
                    job_count=36,
                )

    def test_stop_limit_must_leave_pending_jobs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-cli-limit-") as temporary:
            root = Path(temporary)
            for invalid in (0, 36, 37):
                with self.subTest(invalid=invalid), self.assertRaises(SystemExit):
                    validate_run_arguments(arguments(root, stop_after=invalid), job_count=36)


if __name__ == "__main__":
    unittest.main()
