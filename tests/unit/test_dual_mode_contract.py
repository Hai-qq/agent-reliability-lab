from __future__ import annotations

import unittest

from arl_dualmode.contract import amendment_record, dual_mode_contract
from arl_dualmode.experiment import (
    CANARY_TEMPLATE_IDS,
    THINKING_CONFIG,
    thinking_manifest,
)


class DualModeContractTests(unittest.TestCase):
    def test_contract_binds_two_modes_of_the_same_flash_model_transparently(self) -> None:
        contract = dual_mode_contract()
        contract.assert_ready("main")
        self.assertEqual(contract.stage("main").episode_count, 864)
        self.assertFalse(contract.stage("main").confirmatory)
        self.assertEqual(
            {slot.model_id for slot in contract.model_slots},
            {"deepseek-v4-flash"},
        )
        self.assertEqual(len({slot.revision for slot in contract.model_slots}), 2)
        amendment = amendment_record()
        self.assertFalse(amendment["cross_model_generalization_claimed"])
        self.assertFalse(amendment["prospectively_preregistered_two_configuration_study"])
        self.assertEqual(len(amendment["sha256"]), 64)

    def test_manifests_freeze_six_job_canary_and_432_job_formal_matrix(self) -> None:
        canary = thinking_manifest(canary=True)
        formal = thinking_manifest()
        self.assertEqual(len(canary.jobs), len(CANARY_TEMPLATE_IDS))
        self.assertEqual(len(formal.jobs), 432)
        self.assertEqual(len({job.job_id for job in formal.jobs}), 432)
        for job in (*canary.jobs, *formal.jobs):
            payload = job.payload()
            self.assertEqual(payload["binding"]["model_id"], "deepseek-v4-flash")
            self.assertEqual(payload["inference_mode"]["thinking"], "enabled")
            self.assertEqual(payload["inference_mode"]["reasoning_effort"], "high")
            self.assertEqual(
                payload["experiment_config"]["sampling"]["max_output_tokens"],
                THINKING_CONFIG.sampling.max_output_tokens,
            )


if __name__ == "__main__":
    unittest.main()
