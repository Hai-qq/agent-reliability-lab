from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_holdout_v29.contract import study_contract, transition_record
from arl_holdout_v29.experiment import study_manifest
from arl_holdout_v29.preflight import run_holdout_preflight
from arl_holdout_v29.specs import (
    ENVIRONMENT_SEEDS,
    HOLDOUT_TEMPLATES,
    all_seeded_specs,
    holdout_catalog_audit,
)


class HoldoutV29ContractTests(unittest.TestCase):
    def test_catalog_is_new_balanced_and_seeded(self) -> None:
        catalog = holdout_catalog_audit()
        self.assertTrue(catalog["passed"])
        self.assertEqual(len(HOLDOUT_TEMPLATES), 24)
        self.assertEqual(len(all_seeded_specs()), 72)
        self.assertEqual(len(ENVIRONMENT_SEEDS), 3)
        self.assertTrue(catalog["checks"]["disjoint_from_v028_template_ids"])

    def test_contract_and_manifests_freeze_exact_episode_arithmetic(self) -> None:
        contract = study_contract()
        self.assertTrue(contract.stage("full_three_seed").confirmatory)
        self.assertEqual(contract.stage("full_three_seed").episode_count, 2592)
        canary = study_manifest(canary=True)
        formal = study_manifest(canary=False)
        self.assertEqual(len(canary.jobs), 36)
        self.assertEqual(len(formal.jobs), 2592)
        self.assertEqual(len({job.job_id for job in formal.jobs}), 2592)
        self.assertTrue(transition_record()["v028_confirmatory_failure_remains_unchanged"])

    def test_zero_model_preflight_passes_all_432_cells(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-v29-preflight-test-") as temporary:
            summary = run_holdout_preflight(Path(temporary) / "traces", Path.cwd())
        self.assertEqual(summary["aggregate"]["episode_count"], 432)
        self.assertTrue(summary["validity"]["all_selected_checks_passed"])
        self.assertTrue(summary["readiness"]["ready_for_provider_probe"])


if __name__ == "__main__":
    unittest.main()
