from __future__ import annotations

import unittest

from arl_opencode_v28.contract import MODEL_BINDINGS, amendment_record, study_contract
from arl_opencode_v28.experiment import CANARY_TEMPLATE_IDS, study_manifest


class OpenCodeGoV28ContractTests(unittest.TestCase):
    def test_contract_freezes_flash_and_qwen_before_protocol_probe(self) -> None:
        contract = study_contract()
        contract.assert_ready("main")
        self.assertEqual(contract.stage("main").episode_count, 864)
        self.assertEqual(
            {binding.model_id for binding in MODEL_BINDINGS.values()},
            {"deepseek-v4-flash", "qwen3.7-plus"},
        )
        amendment = amendment_record()
        self.assertTrue(amendment["selection_frozen_before_qwen_protocol_probe"])
        self.assertFalse(amendment["v027_result_reused"])
        self.assertEqual(
            amendment["transport_retry_policy"]["maximum_retries_per_logical_call"],
            2,
        )

    def test_canary_and_formal_manifests_have_exact_arithmetic(self) -> None:
        canary = study_manifest(canary=True)
        formal = study_manifest()
        self.assertEqual(len(canary.jobs), len(CANARY_TEMPLATE_IDS) * 2)
        self.assertEqual(len(formal.jobs), 864)
        self.assertEqual(len({job.job_id for job in formal.jobs}), 864)
        self.assertEqual(
            {job.payload()["slot_id"] for job in formal.jobs},
            {"flash", "qwen"},
        )


if __name__ == "__main__":
    unittest.main()
