from __future__ import annotations

import copy
import unittest
from decimal import Decimal

from arl.studies.budget import (
    MonetaryReportingPolicy,
    ProviderPricing,
    TokenBudget,
    reconcile_usage,
    reserve_before_call,
    v029_budget_diagnostic,
    validate_budget_feasibility,
)
from arl.studies.schedule import blocked_randomized_schedule
from arl.studies.v030 import FaultContract, catalog_diagnostics, design_contract, scripted_oracle


class BudgetTests(unittest.TestCase):
    def test_v029_frozen_cap_is_feasible_for_flash_not_qwen(self) -> None:
        diagnostic = v029_budget_diagnostic()
        self.assertTrue(diagnostic["reports"]["flash"]["feasible"])
        self.assertFalse(diagnostic["reports"]["qwen"]["feasible"])
        self.assertEqual(diagnostic["reports"]["flash"]["worst_case_call_cost"], "0.00509376")
        self.assertEqual(diagnostic["reports"]["qwen"]["worst_case_call_cost"], "0.0211072")
        self.assertFalse(diagnostic["contract_modified"])

    def test_decimal_cache_boundaries_and_model_specific_cap(self) -> None:
        pricing = ProviderPricing(
            model_binding="fixture",
            cache_hit_input_per_million=Decimal("0.10"),
            cache_miss_input_per_million=Decimal("0.20"),
            output_per_million=Decimal("0.30"),
            source="fixture",
            observed_date="2026-08-21",
        )
        self.assertEqual(
            pricing.estimate(
                cache_hit_input_tokens=1_000_000,
                cache_miss_input_tokens=0,
                output_tokens=0,
            ),
            Decimal("0.10"),
        )
        self.assertEqual(
            pricing.estimate(
                cache_hit_input_tokens=0,
                cache_miss_input_tokens=1_000_000,
                output_tokens=0,
            ),
            Decimal("0.20"),
        )
        report = validate_budget_feasibility(
            TokenBudget(4, 1000, 1000),
            MonetaryReportingPolicy(hard_caps_by_model={"fixture": Decimal("0.01")}),
            pricing,
            model_binding="fixture",
        )
        self.assertTrue(report.feasible)
        with self.assertRaises(ValueError):
            validate_budget_feasibility(
                TokenBudget(4, 1000, 1000),
                MonetaryReportingPolicy(),
                None,
                model_binding="fixture",
            )

    def test_reservation_is_replaced_by_actual_usage(self) -> None:
        pricing = ProviderPricing(
            model_binding="fixture",
            cache_hit_input_per_million=Decimal("0.10"),
            cache_miss_input_per_million=Decimal("0.20"),
            output_per_million=Decimal("0.30"),
            source="fixture",
            observed_date="2026-08-21",
        )
        budget = TokenBudget(4, 1000, 1000)
        policy = MonetaryReportingPolicy(hard_caps_by_model={"fixture": Decimal("0.01")})
        reserved = reserve_before_call(
            spent=Decimal("0"), pricing=pricing, budget=budget, policy=policy
        )
        self.assertEqual(reserved, Decimal("0.0005"))
        reconciled = reconcile_usage(
            reserved=reserved,
            pricing=pricing,
            budget=budget,
            cache_hit_input_tokens=100,
            cache_miss_input_tokens=200,
            output_tokens=50,
            policy=policy,
        )
        self.assertEqual(reconciled, Decimal("0.000065"))


class ScheduleAndV030Tests(unittest.TestCase):
    def schedule(self, seed: int):
        return blocked_randomized_schedule(
            task_template_ids=["a", "b"],
            environment_seeds=[0, 1],
            sampling_trials=[0, 1],
            runtimes=["R1", "R2"],
            conditions=["clean", "fault"],
            model_slots=["m1", "m2"],
            schedule_seed=seed,
        )

    def test_blocked_schedule_reproducibility_balance_and_resume(self) -> None:
        first = self.schedule(7)
        repeat = self.schedule(7)
        alternate = self.schedule(8)
        self.assertEqual(first.as_dict(), repeat.as_dict())
        self.assertNotEqual(first.sha256, alternate.sha256)
        self.assertEqual(
            {item.cell_id for item in first.execution_order},
            {item.cell_id for item in alternate.execution_order},
        )
        self.assertTrue(first.balance["balanced"])
        prefix = [item.cell_id for item in first.execution_order[:3]]
        self.assertEqual(first.remaining(prefix), first.execution_order[3:])
        with self.assertRaises(ValueError):
            first.remaining(list(reversed(prefix)))

    def test_v030_is_design_only_with_48_templates(self) -> None:
        diagnostic = catalog_diagnostics()
        self.assertTrue(diagnostic["passed"])
        self.assertEqual(diagnostic["template_count"], 48)
        design = design_contract()
        self.assertEqual(design["provider_calls_executed"], 0)
        self.assertEqual(design["model_results"], "NOT_MATERIALIZED")
        self.assertEqual(design["power_simulation"]["selected_template_count"], 48)

    def test_no_safe_recovery_and_mutations(self) -> None:
        no_safe = scripted_oracle(condition="no_safe_recovery", runtime="R2")
        self.assertFalse(no_safe["recoverable"])
        self.assertFalse(no_safe["task_success"])
        self.assertEqual(no_safe["severe_side_effect_count"], 0)
        unsafe = scripted_oracle(
            condition="recoverable_fault", runtime="R2", mutation="unsafe_retry"
        )
        self.assertTrue(unsafe["unsafe_retry_detected"])
        self.assertFalse(unsafe["safe_success"])

    def test_fault_contract_rejects_overlapping_recovery_sets(self) -> None:
        valid = FaultContract(
            fault_id="f",
            precondition="p",
            injection_point="i",
            observable_symptom="o",
            hidden_ground_truth="h",
            valid_recovery_set=("retry",),
            prohibited_recovery_set=("stop",),
            required_final_invariants=("invariant",),
            forbidden_side_effects=("duplicate",),
            recoverable=True,
            applicable_runtime_mechanism="guard",
            mutation_tests=("mutation",),
        )
        arguments = copy.deepcopy(valid.as_dict())
        arguments["prohibited_recovery_set"] = ("retry",)
        with self.assertRaises(ValueError):
            FaultContract(**arguments)


if __name__ == "__main__":
    unittest.main()
