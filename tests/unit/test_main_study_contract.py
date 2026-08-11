from __future__ import annotations

import unittest
from dataclasses import replace

from arl_mainstudy.catalog import TASK_BLUEPRINTS, catalog_audit
from arl_mainstudy.contract import ModelSlot, default_contract


class MainStudyContractTests(unittest.TestCase):
    def test_episode_arithmetic_is_explicit_and_consistent(self) -> None:
        contract = default_contract()
        self.assertEqual(contract.task_template_count, 24)
        self.assertEqual(contract.stage("scripted_smoke").episode_count, 12)
        self.assertEqual(contract.stage("pilot").episode_count, 144)
        self.assertEqual(contract.stage("main").episode_count, 864)
        self.assertEqual(contract.stage("full_three_seed").episode_count, 2592)
        self.assertEqual(contract.clean_noninferiority_margin, -0.05)
        self.assertEqual(contract.bootstrap_cluster, "task_template")

    def test_model_stages_fail_closed_until_exact_bindings_exist(self) -> None:
        contract = default_contract()
        contract.assert_ready("scripted_smoke")
        with self.assertRaises(RuntimeError):
            contract.assert_ready("pilot")
        with self.assertRaises(RuntimeError):
            contract.assert_ready("main")

        one_bound = replace(
            contract,
            model_slots=(
                ModelSlot(
                    slot_id="strong_api",
                    role="strong tool-capable API model",
                    provider="example-provider",
                    model_id="exact-model-id",
                    revision="2026-08-08",
                ),
                contract.model_slots[1],
            ),
        )
        one_bound.assert_ready("pilot")
        with self.assertRaises(RuntimeError):
            one_bound.assert_ready("main")

    def test_partial_model_binding_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ModelSlot(
                slot_id="invalid",
                role="invalid",
                provider="provider-only",
            )

    def test_blueprint_is_balanced_without_claiming_planned_tasks_are_runnable(self) -> None:
        audit = catalog_audit()
        self.assertTrue(audit["passed"])
        self.assertEqual(len(TASK_BLUEPRINTS), 24)
        self.assertEqual(audit["domain_counts"], {"retail": 8, "travel": 8, "workspace": 8})
        self.assertEqual(
            audit["implementation_status_counts"],
            {"existing_core": 6, "planned": 18},
        )


if __name__ == "__main__":
    unittest.main()
