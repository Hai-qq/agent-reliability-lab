from __future__ import annotations

import unittest

from arl_openstudy.contract import MODEL_BINDINGS, amendment_record, openstudy_contract
from arl_openstudy.experiment import CANARY_TEMPLATE_IDS, openstudy_manifest


class OpenCodeGoContractTests(unittest.TestCase):
    def test_contract_binds_two_distinct_models_on_one_gateway(self) -> None:
        contract = openstudy_contract()
        contract.assert_ready("main")
        self.assertEqual(contract.stage("main").episode_count, 864)
        self.assertTrue(contract.stage("main").confirmatory)
        self.assertEqual({binding.provider for binding in MODEL_BINDINGS.values()}, {"opencode-go"})
        self.assertEqual(
            {binding.model_id for binding in MODEL_BINDINGS.values()},
            {"deepseek-v4-flash", "mimo-v2.5"},
        )
        amendment = amendment_record()
        self.assertTrue(amendment["cross_model_consistency_claim_allowed"])
        self.assertFalse(amendment["cross_provider_generalization_claimed"])
        self.assertFalse(amendment["prior_result_included_in_new_864_matrix"])

    def test_canary_and_formal_manifests_have_exact_two_model_arithmetic(self) -> None:
        canary = openstudy_manifest(canary=True)
        formal = openstudy_manifest()
        self.assertEqual(len(canary.jobs), len(CANARY_TEMPLATE_IDS) * 2)
        self.assertEqual(len(formal.jobs), 864)
        self.assertEqual(len({job.job_id for job in formal.jobs}), 864)
        self.assertEqual(
            {job.payload()["slot_id"] for job in formal.jobs},
            {"flash", "mimo"},
        )


if __name__ == "__main__":
    unittest.main()
