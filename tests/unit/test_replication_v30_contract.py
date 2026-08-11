from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_replication_v30.contract import (
    MAX_USAGE_VALUE_USD_PER_EPISODE,
    budget_calibration_record,
    study_contract,
    transition_record,
)
from arl_replication_v30.experiment import study_manifest
from arl_replication_v30.preflight import run_replication_preflight
from arl_replication_v30.specs import (
    ENVIRONMENT_SEEDS,
    REPLICATION_TEMPLATES,
    all_seeded_specs,
    replication_catalog_audit,
)


class ReplicationV30ContractTests(unittest.TestCase):
    def test_catalog_is_new_balanced_and_seeded(self) -> None:
        catalog = replication_catalog_audit()
        self.assertTrue(catalog["passed"])
        self.assertEqual(len(REPLICATION_TEMPLATES), 24)
        self.assertEqual(len(all_seeded_specs()), 72)
        self.assertEqual(len(ENVIRONMENT_SEEDS), 3)
        self.assertTrue(catalog["checks"]["disjoint_from_v028_and_v029_template_ids"])
        self.assertTrue(catalog["checks"]["contexts_disjoint_from_v029"])
        self.assertTrue(catalog["checks"]["environment_seeds_disjoint_from_v029"])

    def test_contract_and_manifests_freeze_exact_episode_arithmetic(self) -> None:
        contract = study_contract()
        self.assertTrue(contract.stage("full_three_seed").confirmatory)
        self.assertEqual(contract.stage("full_three_seed").episode_count, 2592)
        canary = study_manifest(canary=True)
        formal = study_manifest(canary=False)
        self.assertEqual(len(canary.jobs), 36)
        self.assertEqual(len(formal.jobs), 2592)
        self.assertEqual(len({job.job_id for job in formal.jobs}), 2592)
        transition = transition_record()
        self.assertTrue(transition["v029_disposition_remains_infrastructure_invalid"])
        self.assertEqual({item.slot_id for item in contract.model_slots}, {"flash", "pro"})
        self.assertEqual(MAX_USAGE_VALUE_USD_PER_EPISODE, 0.015)
        self.assertEqual(
            budget_calibration_record()["source_full_summary_sha256"],
            "ae59041b7314ea765da00cc40008d98751d856deece478378eeef99e0c5e2800",
        )

    def test_zero_model_preflight_passes_all_432_cells(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-v30-preflight-test-") as temporary:
            summary = run_replication_preflight(Path(temporary) / "traces", Path.cwd())
        self.assertEqual(summary["aggregate"]["episode_count"], 432)
        self.assertTrue(summary["validity"]["all_selected_checks_passed"])
        self.assertTrue(summary["readiness"]["ready_for_provider_probe"])


if __name__ == "__main__":
    unittest.main()
