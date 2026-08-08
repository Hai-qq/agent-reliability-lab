from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from arl_parallel.experiment import LEAVE_LEASES, STOP_AFTER
from scripts.run_parallel_study import validate_run_arguments


def arguments(root: Path, **overrides: object) -> argparse.Namespace:
    values = {
        "workspace": root / "study",
        "output": root / "summary.json",
        "resume": False,
        "stop_after": STOP_AFTER,
        "leave_leases": LEAVE_LEASES,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class ParallelStudyCliContractTests(unittest.TestCase):
    def test_formal_initial_phase_requires_exact_checkpoint_shape(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-cli-") as temporary:
            root = Path(temporary)
            validate_run_arguments(arguments(root))
            for overrides in (
                {"stop_after": None},
                {"stop_after": STOP_AFTER - 1},
                {"leave_leases": LEAVE_LEASES - 1},
            ):
                with self.subTest(overrides=overrides), self.assertRaises(SystemExit):
                    validate_run_arguments(arguments(root, **overrides))

    def test_resume_forbids_stop_and_leave_options(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-cli-resume-") as temporary:
            root = Path(temporary)
            validate_run_arguments(arguments(root, resume=True, stop_after=None, leave_leases=0))
            with self.assertRaises(SystemExit):
                validate_run_arguments(arguments(root, resume=True, leave_leases=0))
            with self.assertRaises(SystemExit):
                validate_run_arguments(
                    arguments(root, resume=True, stop_after=None, leave_leases=1)
                )

    def test_output_must_be_new_and_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-cli-path-") as temporary:
            root = Path(temporary)
            with self.assertRaises(SystemExit):
                validate_run_arguments(arguments(root, output=root / "study/summary.json"))
            output = root / "summary.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_run_arguments(arguments(root, output=output))


if __name__ == "__main__":
    unittest.main()
