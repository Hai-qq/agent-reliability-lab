"""Scripted v0.30 infrastructure preflight; it cannot call a provider."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from arl.studies.budget import (
    MonetaryReportingPolicy,
    ProviderPricing,
    TokenBudget,
    validate_budget_feasibility,
)
from arl.studies.schedule import FrozenSchedule, blocked_randomized_schedule
from arl.studies.smoke import run_smoke
from arl.studies.v030 import (
    SCHEDULE_SEED,
    catalog_diagnostics,
    design_contract,
    scripted_oracle,
    task_catalog,
)


def run_scripted_preflight() -> dict[str, Any]:
    """Validate design mechanics with synthetic oracles and zero model calls."""

    design = design_contract()
    template_ids = [item.task_template_id for item in task_catalog()]
    environment_seeds = [0, 1, 2]
    sampling_trials = [0, 1, 2]
    runtimes = ["R0", "R1", "R2"]
    conditions = ["clean", "recoverable_fault", "unseen_fault", "no_safe_recovery"]
    model_slots = ["model-slot-a", "model-slot-b"]

    def make_schedule(seed: int) -> FrozenSchedule:
        return blocked_randomized_schedule(
            task_template_ids=template_ids,
            environment_seeds=environment_seeds,
            sampling_trials=sampling_trials,
            runtimes=runtimes,
            conditions=conditions,
            model_slots=model_slots,
            schedule_seed=seed,
        )

    first = make_schedule(SCHEDULE_SEED)
    repeat = make_schedule(SCHEDULE_SEED)
    alternate = make_schedule(SCHEDULE_SEED + 1)

    fixture_pricing = ProviderPricing(
        model_binding="scripted-price-fixture",
        cache_hit_input_per_million=Decimal("0.10"),
        cache_miss_input_per_million=Decimal("0.20"),
        output_per_million=Decimal("0.30"),
        source="local scripted preflight fixture",
        observed_date="2026-08-21",
    )
    budget = TokenBudget(8, 20_000, 8_192)
    budget_report = validate_budget_feasibility(
        budget,
        MonetaryReportingPolicy(),
        fixture_pricing,
        model_binding=fixture_pricing.model_binding,
    )
    clean = scripted_oracle(condition="clean", runtime="R1")
    recoverable = scripted_oracle(condition="recoverable_fault", runtime="R2")
    no_safe = scripted_oracle(condition="no_safe_recovery", runtime="R2")
    false_success = scripted_oracle(
        condition="no_safe_recovery", runtime="R2", mutation="false_success"
    )
    duplicate = scripted_oracle(
        condition="recoverable_fault", runtime="R2", mutation="duplicate_side_effect"
    )
    unsafe_retry = scripted_oracle(
        condition="recoverable_fault", runtime="R2", mutation="unsafe_retry"
    )
    with tempfile.TemporaryDirectory(prefix="arl-v030-preflight-") as temporary:
        smoke = run_smoke(Path(temporary) / "public-smoke")

    checks = {
        "task_catalog": catalog_diagnostics()["passed"],
        "power_selects_48_templates": design["power_simulation"]["selected_template_count"] == 48,
        "clean_oracle": clean["task_success"] and clean["safe_success"],
        "recoverable_oracle": recoverable["task_success"] and recoverable["safe_success"],
        "no_safe_recovery_oracle": (
            not no_safe["recoverable"]
            and not no_safe["task_success"]
            and no_safe["severe_side_effect_count"] == 0
            and no_safe["terminal_reason"] == "no_safe_recovery"
        ),
        "evaluator_mutation": false_success["evaluator_rejected_mutation"],
        "duplicate_side_effect_detection": (
            duplicate["severe_side_effect_count"] == 1 and not duplicate["safe_success"]
        ),
        "unsafe_retry_detection": (
            unsafe_retry["unsafe_retry_detected"] and not unsafe_retry["safe_success"]
        ),
        "public_evidence_and_verifier": smoke["verified"],
        "schedule_same_seed_identical": first.as_dict() == repeat.as_dict(),
        "schedule_different_seed_changes_order": first.sha256 != alternate.sha256,
        "schedule_cell_set_preserved": (
            {item.cell_id for item in first.execution_order}
            == {item.cell_id for item in alternate.execution_order}
        ),
        "schedule_balanced": first.balance["balanced"],
        "budget_feasibility": budget_report.feasible,
    }
    return {
        "study_id": design["study_id"],
        "preflight_type": "scripted_infrastructure_only",
        "model_calls": 0,
        "provider_calls": 0,
        "network_calls": 0,
        "model_results": "NOT_MATERIALIZED",
        "checks": checks,
        "all_selected_checks_passed": all(checks.values()),
        "schedule_sha256": first.sha256,
        "schedule_cell_count": len(first.execution_order),
        "budget": budget_report.as_dict(),
    }
