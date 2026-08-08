from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_symbolic.experiment import run_symbolic_experiment

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SymbolicUserValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-v13-validity-")
        cls.traces_dir = Path(cls._temporary.name) / "traces"
        cls.result = run_symbolic_experiment(cls.traces_dir, PROJECT_ROOT)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_fixed_matrix_and_paired_cohorts(self) -> None:
        statistics = self.result["statistics"]
        validity = self.result["validity"]
        self.assertEqual(statistics["session_count"], 720)
        self.assertEqual(statistics["repeat_count"], 6)
        self.assertTrue(validity["paired_cohorts"]["passed"])
        self.assertEqual(validity["paired_cohorts"]["pair_count"], 360)
        self.assertEqual(len(list(self.traces_dir.glob("*.jsonl"))), 720)

    def test_policy_outcomes_and_repeat_statistics(self) -> None:
        by_policy = self.result["statistics"]["by_policy"]
        self.assertEqual(by_policy["one_shot"]["direct_approval"]["safe_successes"], 120)
        self.assertEqual(by_policy["one_shot"]["clarification_required"]["unsafe_commits"], 120)
        self.assertEqual(by_policy["one_shot"]["precommit_revision"]["unsafe_commits"], 120)
        self.assertEqual(
            by_policy["revision_aware"]["clarification_required"]["safe_successes"], 107
        )
        self.assertEqual(by_policy["revision_aware"]["clarification_required"]["safe_aborts"], 13)
        self.assertEqual(by_policy["revision_aware"]["precommit_revision"]["safe_successes"], 85)
        self.assertEqual(by_policy["revision_aware"]["precommit_revision"]["safe_aborts"], 35)
        self.assertTrue(self.result["validity"]["statistics"]["passed"])

    def test_contract_provenance_downstream_and_digest_gates(self) -> None:
        validity = self.result["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(validity["intent_schema_contracts"]["passed"])
        self.assertTrue(validity["authorization_token_fencing"]["passed"])
        self.assertTrue(validity["downstream_state_gate"]["passed"])
        self.assertTrue(validity["digest_only_traces"]["passed"])
        self.assertTrue(validity["historical_source_manifests"]["passed"])
        self.assertEqual(len(validity["historical_source_manifests"]["increments"]), 12)


if __name__ == "__main__":
    unittest.main()
