"""Token fairness and conservative model-specific monetary feasibility."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

MILLION = Decimal("1000000")


def _decimal(value: Decimal | str | int) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


@dataclass(frozen=True)
class TokenBudget:
    """A model-independent per-episode logical call and token contract."""

    max_calls: int
    max_input_tokens: int
    max_output_tokens: int

    def __post_init__(self) -> None:
        if min(self.max_calls, self.max_input_tokens, self.max_output_tokens) < 1:
            raise ValueError("token budget limits must be positive")

    def as_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderPricing:
    """Frozen model pricing in decimal USD per million tokens."""

    model_binding: str
    cache_hit_input_per_million: Decimal
    cache_miss_input_per_million: Decimal
    output_per_million: Decimal
    source: str
    observed_date: str

    def __post_init__(self) -> None:
        if not self.model_binding or not self.source or not self.observed_date:
            raise ValueError("pricing binding, source, and observed_date are required")
        for value in (
            self.cache_hit_input_per_million,
            self.cache_miss_input_per_million,
            self.output_per_million,
        ):
            if not isinstance(value, Decimal) or value < 0:
                raise ValueError("pricing values must be non-negative Decimal instances")

    def estimate(
        self,
        *,
        cache_hit_input_tokens: int,
        cache_miss_input_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        """Calculate exact decimal usage value at cache boundaries."""

        if min(cache_hit_input_tokens, cache_miss_input_tokens, output_tokens) < 0:
            raise ValueError("token usage cannot be negative")
        return (
            _decimal(cache_hit_input_tokens) * self.cache_hit_input_per_million
            + _decimal(cache_miss_input_tokens) * self.cache_miss_input_per_million
            + _decimal(output_tokens) * self.output_per_million
        ) / MILLION

    def worst_case_call_cost(self, budget: TokenBudget) -> Decimal:
        """Reserve all input at the more expensive cache rate and maximum output."""

        input_rate = max(self.cache_hit_input_per_million, self.cache_miss_input_per_million)
        return (
            _decimal(budget.max_input_tokens) * input_rate
            + _decimal(budget.max_output_tokens) * self.output_per_million
        ) / MILLION

    def as_dict(self) -> dict[str, str]:
        return {
            "model_binding": self.model_binding,
            "cache_hit_input_per_million": str(self.cache_hit_input_per_million),
            "cache_miss_input_per_million": str(self.cache_miss_input_per_million),
            "output_per_million": str(self.output_per_million),
            "source": self.source,
            "observed_date": self.observed_date,
        }


@dataclass(frozen=True)
class MonetaryReportingPolicy:
    """Treat monetary value as an outcome unless a per-model cap is explicit."""

    currency: str = "USD"
    hard_caps_by_model: dict[str, Decimal] | None = None

    def __post_init__(self) -> None:
        if self.currency != "USD":
            raise ValueError("only explicitly priced USD reporting is supported")
        if self.hard_caps_by_model is not None:
            if not self.hard_caps_by_model:
                raise ValueError("hard cap mapping must not be empty")
            if any(
                not isinstance(value, Decimal) or value <= 0
                for value in self.hard_caps_by_model.values()
            ):
                raise ValueError("hard caps must be positive Decimal instances")

    def cap_for(self, model_binding: str) -> Decimal | None:
        if self.hard_caps_by_model is None:
            return None
        if model_binding not in self.hard_caps_by_model:
            raise ValueError(f"missing model-specific monetary cap: {model_binding}")
        return self.hard_caps_by_model[model_binding]

    def as_dict(self) -> dict[str, Any]:
        return {
            "currency": self.currency,
            "monetary_cost_is_outcome": self.hard_caps_by_model is None,
            "hard_caps_by_model": (
                None
                if self.hard_caps_by_model is None
                else {key: str(value) for key, value in sorted(self.hard_caps_by_model.items())}
            ),
        }


@dataclass(frozen=True)
class BudgetFeasibilityReport:
    """Preflight proof that a configured monetary cap cannot bind a legal call."""

    model_binding: str
    feasible: bool
    token_budget: TokenBudget
    worst_case_call_cost: Decimal
    hard_cap: Decimal | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_binding": self.model_binding,
            "feasible": self.feasible,
            "token_budget": self.token_budget.as_dict(),
            "worst_case_call_cost": str(self.worst_case_call_cost),
            "hard_cap": None if self.hard_cap is None else str(self.hard_cap),
            "reason": self.reason,
        }


def validate_budget_feasibility(
    budget: TokenBudget,
    policy: MonetaryReportingPolicy,
    pricing: ProviderPricing | None,
    *,
    model_binding: str,
) -> BudgetFeasibilityReport:
    """Fail closed on missing pricing or a cap that a legal response can exceed."""

    if pricing is None:
        raise ValueError(f"pricing is required for budget feasibility: {model_binding}")
    if pricing.model_binding != model_binding:
        raise ValueError("pricing model binding mismatch")
    worst_case = pricing.worst_case_call_cost(budget)
    cap = policy.cap_for(model_binding)
    feasible = cap is None or worst_case < cap
    reason = (
        "monetary cost is reported as an outcome; no readiness cap applies"
        if cap is None
        else (
            "worst-case legal call is strictly below the model-specific cap"
            if feasible
            else "worst-case legal call can bind or exceed the model-specific cap"
        )
    )
    return BudgetFeasibilityReport(
        model_binding=model_binding,
        feasible=feasible,
        token_budget=budget,
        worst_case_call_cost=worst_case,
        hard_cap=cap,
        reason=reason,
    )


def reserve_before_call(
    *,
    spent: Decimal,
    pricing: ProviderPricing,
    budget: TokenBudget,
    policy: MonetaryReportingPolicy,
) -> Decimal:
    """Conservatively reserve a full legal response before transport starts."""

    if not isinstance(spent, Decimal) or spent < 0:
        raise ValueError("spent must be a non-negative Decimal")
    reserved = spent + pricing.worst_case_call_cost(budget)
    cap = policy.cap_for(pricing.model_binding)
    if cap is not None and reserved >= cap:
        raise ValueError("conservative reservation would bind or exceed the hard cap")
    return reserved


def reconcile_usage(
    *,
    reserved: Decimal,
    pricing: ProviderPricing,
    budget: TokenBudget,
    cache_hit_input_tokens: int,
    cache_miss_input_tokens: int,
    output_tokens: int,
    policy: MonetaryReportingPolicy,
) -> Decimal:
    """Replace a reservation with exact response usage and enforce the cap."""

    if not isinstance(reserved, Decimal) or reserved < 0:
        raise ValueError("reserved must be a non-negative Decimal")
    reservation = pricing.worst_case_call_cost(budget)
    if reserved < reservation:
        raise ValueError("reserved total is smaller than one legal-call reservation")
    actual = (
        reserved
        - reservation
        + pricing.estimate(
            cache_hit_input_tokens=cache_hit_input_tokens,
            cache_miss_input_tokens=cache_miss_input_tokens,
            output_tokens=output_tokens,
        )
    )
    cap = policy.cap_for(pricing.model_binding)
    if cap is not None and actual >= cap:
        raise ValueError("reconciled usage binds or exceeds the hard cap")
    return actual


def v029_budget_diagnostic() -> dict[str, Any]:
    """Reproduce the frozen v0.29 cap feasibility diagnosis without changing it."""

    budget = TokenBudget(max_calls=8, max_input_tokens=20_000, max_output_tokens=8_192)
    cap = Decimal("0.01")
    policy = MonetaryReportingPolicy(hard_caps_by_model={"flash": cap, "qwen": cap})
    source = "https://dev.opencode.ai/docs/go/ (historically observed 2026-08-09)"
    pricing = {
        "flash": ProviderPricing(
            model_binding="flash",
            cache_hit_input_per_million=Decimal("0.0028"),
            cache_miss_input_per_million=Decimal("0.14"),
            output_per_million=Decimal("0.28"),
            source=source,
            observed_date="2026-08-09",
        ),
        "qwen": ProviderPricing(
            model_binding="qwen",
            cache_hit_input_per_million=Decimal("0.04"),
            cache_miss_input_per_million=Decimal("0.40"),
            output_per_million=Decimal("1.60"),
            source=source,
            observed_date="2026-08-09",
        ),
    }
    reports = {
        name: validate_budget_feasibility(budget, policy, item, model_binding=name).as_dict()
        for name, item in pricing.items()
    }
    return {
        "study_contract": "v0.29 (read-only diagnostic)",
        "frozen_hard_cap_usd": str(cap),
        "reports": reports,
        "contract_modified": False,
        "analysis_status": "posthoc_methodology_diagnostic",
    }
