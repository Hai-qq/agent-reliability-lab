from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_r2.experiment import run_workspace_r2_experiment


class WorkspaceR2ValidityTests(unittest.TestCase):
    def test_paired_matrix_and_selected_r2_validity_gates(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-r2-validity-") as temporary:
            result = run_workspace_r2_experiment(Path(temporary) / "traces")
        aggregate = result["aggregate"]
        self.assertEqual(aggregate["episode_count"], 12)
        self.assertEqual(aggregate["by_runtime"]["r1_guarded"]["clean_successes"], 3)
        self.assertEqual(aggregate["by_runtime"]["r1_guarded"]["fault_successes"], 0)
        self.assertEqual(aggregate["by_runtime"]["r2_confirmed"]["clean_successes"], 3)
        self.assertEqual(aggregate["by_runtime"]["r2_confirmed"]["fault_successes"], 3)
        self.assertEqual(aggregate["paired_recovery_rate_delta_r2_minus_r1"], 1.0)
        self.assertTrue(result["validity"]["all_selected_checks_passed"])
        self.assertTrue(result["validity"]["idempotent_replay"]["passed"])
        self.assertTrue(result["validity"]["r2_confirmation_recovery"]["passed"])


if __name__ == "__main__":
    unittest.main()
