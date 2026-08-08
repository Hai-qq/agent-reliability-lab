from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_scenarios.experiment import run_scenario_pack

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ScenarioPackValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-v12-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_scenario_pack(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_matrix_and_all_four_template_recovery_delta(self) -> None:
        aggregate = self.result["aggregate"]
        baseline = aggregate["by_runtime"]["r2_confirmed"]
        guarded = aggregate["by_runtime"]["r2_template_guarded"]
        self.assertEqual(aggregate["episode_count"], 72)
        self.assertEqual(aggregate["template_count"], 4)
        self.assertEqual(baseline["by_condition"]["compatible_conflict"]["safe_successes"], 0)
        self.assertEqual(guarded["by_condition"]["compatible_conflict"]["safe_successes"], 12)
        self.assertEqual(aggregate["compatible_recovery_rate_delta"], 1.0)

    def test_workflow_and_fail_closed_gates(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(validity["all_template_compatible_recovery"]["passed"])
        self.assertTrue(validity["all_template_incompatible_fail_closed"]["passed"])
        workflow = validity["compensation_workflow_audit"]
        self.assertEqual(workflow["attempts"], 9)
        self.assertEqual(workflow["successes"], 6)
        self.assertEqual(workflow["failures"], 3)
        self.assertEqual(workflow["terminal_probes"], 36)

    def test_provenance_and_digest_only_gates(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["task_template_catalog"]["passed"])
        self.assertTrue(validity["workflow_contract_mutations"]["passed"])
        self.assertTrue(validity["reset_snapshot_and_baselines"]["passed"])
        self.assertTrue(validity["historical_source_manifests"]["passed"])
        self.assertEqual(len(validity["historical_source_manifests"]["increments"]), 11)
        self.assertTrue(validity["digest_only_traces"]["passed"])
        self.assertEqual(len(list(self.traces_dir.glob("*.jsonl"))), 72)


if __name__ == "__main__":
    unittest.main()
