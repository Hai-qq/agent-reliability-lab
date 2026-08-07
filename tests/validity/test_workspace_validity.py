from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl.envs.workspace import WORKSPACE_TASK_ID, WorkspaceEnvironment
from arl.evaluators.workspace import evaluate_workspace
from arl.experiments.workspace_paired import run_workspace_paired_experiment


class WorkspaceValidityTests(unittest.TestCase):
    def test_do_nothing_is_rejected(self) -> None:
        environment = WorkspaceEnvironment()
        try:
            environment.reset(WORKSPACE_TASK_ID, 0)
            snapshot = environment.snapshot()
            report = evaluate_workspace(snapshot, snapshot, [])
            self.assertFalse(report.task_success)
            self.assertFalse(report.safe_success)
        finally:
            environment.close()

    def test_paired_matrix_and_selected_validity_gates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-validity-") as temporary:
            result = run_workspace_paired_experiment(Path(temporary) / "traces")
        aggregate = result["aggregate"]
        self.assertEqual(aggregate["episode_count"], 12)
        self.assertEqual(aggregate["by_runtime"]["r0_raw"]["clean_successes"], 3)
        self.assertEqual(aggregate["by_runtime"]["r0_raw"]["fault_successes"], 0)
        self.assertEqual(aggregate["by_runtime"]["r1_guarded"]["clean_successes"], 3)
        self.assertEqual(aggregate["by_runtime"]["r1_guarded"]["fault_successes"], 3)
        self.assertEqual(aggregate["paired_recovery_rate_delta_r1_minus_r0"], 1.0)
        self.assertTrue(result["validity"]["all_selected_checks_passed"])
        self.assertTrue(result["validity"]["repeat_results_deterministic"])


if __name__ == "__main__":
    unittest.main()
