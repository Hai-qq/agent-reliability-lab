"""Machine-readable, fail-closed contract for the ARL confirmatory study."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from arl.core.types import digest_value

RUNTIME_NAMES = ("r0_raw", "r1_guarded", "r2_reliable")
CONDITIONS = ("clean", "recoverable_fault")
DOMAIN_TEMPLATE_COUNTS = {"workspace": 8, "retail": 8, "travel": 8}
FAULT_FAMILY_COUNTS = {
    "postcommit_response_loss": 4,
    "retryable_invocation_error": 4,
    "input_schema_drift": 4,
    "output_schema_drift": 4,
    "compatible_state_conflict": 4,
    "bounded_compensation": 4,
}


@dataclass(frozen=True)
class ModelSlot:
    """An exact model binding that remains deliberately empty before authorization."""

    slot_id: str
    role: str
    provider: str | None = None
    model_id: str | None = None
    revision: str | None = None

    def __post_init__(self) -> None:
        fields = (self.provider, self.model_id, self.revision)
        if any(value is not None for value in fields) and not all(fields):
            raise ValueError("provider, model_id, and revision must be bound together")

    @property
    def bound(self) -> bool:
        return self.provider is not None

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "bound": self.bound}


@dataclass(frozen=True)
class StageSpec:
    """One frozen study stage and its auditable episode arithmetic."""

    stage_id: str
    task_count: int
    environment_seed_count: int
    condition_count: int
    runtime_count: int
    agent_configuration_count: int
    sampling_trial_count: int
    uses_models: bool
    confirmatory: bool

    def __post_init__(self) -> None:
        dimensions = (
            self.task_count,
            self.environment_seed_count,
            self.condition_count,
            self.runtime_count,
            self.agent_configuration_count,
            self.sampling_trial_count,
        )
        if any(value < 1 for value in dimensions):
            raise ValueError("Study-stage dimensions must all be positive")

    @property
    def episode_count(self) -> int:
        return (
            self.task_count
            * self.environment_seed_count
            * self.condition_count
            * self.runtime_count
            * self.agent_configuration_count
            * self.sampling_trial_count
        )

    @property
    def formula(self) -> str:
        return " × ".join(
            str(value)
            for value in (
                self.task_count,
                self.environment_seed_count,
                self.condition_count,
                self.runtime_count,
                self.agent_configuration_count,
                self.sampling_trial_count,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "episode_count": self.episode_count, "formula": self.formula}


@dataclass(frozen=True)
class MainStudyContract:
    """The single source of truth for task scale, hypotheses, and model gates."""

    contract_version: str
    primary_hypothesis: str
    runtime_names: tuple[str, ...]
    conditions: tuple[str, ...]
    domain_template_counts: dict[str, int]
    fault_family_counts: dict[str, int]
    model_slots: tuple[ModelSlot, ...]
    stages: tuple[StageSpec, ...]
    primary_metric: str
    clean_noninferiority_margin: float
    bootstrap_resamples: int
    bootstrap_cluster: str

    def __post_init__(self) -> None:
        if self.runtime_names != RUNTIME_NAMES:
            raise ValueError(f"Runtime order must remain {RUNTIME_NAMES!r}")
        if self.conditions != CONDITIONS:
            raise ValueError(f"Condition order must remain {CONDITIONS!r}")
        if self.domain_template_counts != DOMAIN_TEMPLATE_COUNTS:
            raise ValueError("The confirmatory catalog must remain balanced at 8 tasks per domain")
        if self.fault_family_counts != FAULT_FAMILY_COUNTS:
            raise ValueError(
                "The six recoverable fault families must remain balanced at 4 tasks each"
            )
        if len({slot.slot_id for slot in self.model_slots}) != len(self.model_slots):
            raise ValueError("Model slot IDs must be unique")
        if len({stage.stage_id for stage in self.stages}) != len(self.stages):
            raise ValueError("Stage IDs must be unique")
        expected_counts = {
            "scripted_smoke": 12,
            "pilot": 144,
            "main": 864,
            "full_three_seed": 2592,
        }
        actual_counts = {stage.stage_id: stage.episode_count for stage in self.stages}
        if actual_counts != expected_counts:
            raise ValueError(
                f"Study arithmetic changed: expected {expected_counts!r}, got {actual_counts!r}"
            )
        if not -1.0 < self.clean_noninferiority_margin <= 0.0:
            raise ValueError("Clean noninferiority margin must be in (-1, 0]")
        if self.bootstrap_resamples < 1_000:
            raise ValueError("Confirmatory bootstrap requires at least 1,000 resamples")

    @property
    def task_template_count(self) -> int:
        return sum(self.domain_template_counts.values())

    def stage(self, stage_id: str) -> StageSpec:
        try:
            return next(stage for stage in self.stages if stage.stage_id == stage_id)
        except StopIteration as error:
            raise KeyError(f"Unknown stage: {stage_id}") from error

    def assert_ready(self, stage_id: str) -> None:
        """Fail closed when a model stage is requested before exact bindings exist."""

        stage = self.stage(stage_id)
        if not stage.uses_models:
            return
        required = stage.agent_configuration_count
        bound = sum(slot.bound for slot in self.model_slots)
        if bound < required:
            raise RuntimeError(
                f"Stage {stage_id!r} requires {required} exact model binding(s); found {bound}"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "primary_hypothesis": self.primary_hypothesis,
            "runtime_names": list(self.runtime_names),
            "conditions": list(self.conditions),
            "task_catalog": {
                "template_count": self.task_template_count,
                "domain_template_counts": dict(self.domain_template_counts),
                "fault_family_counts": dict(self.fault_family_counts),
            },
            "model_slots": [slot.as_dict() for slot in self.model_slots],
            "stages": [stage.as_dict() for stage in self.stages],
            "statistics": {
                "primary_metric": self.primary_metric,
                "clean_noninferiority_margin": self.clean_noninferiority_margin,
                "bootstrap_resamples": self.bootstrap_resamples,
                "bootstrap_cluster": self.bootstrap_cluster,
                "timeouts_and_failures_retained": True,
                "per_model_results_required": True,
            },
        }

    @property
    def sha256(self) -> str:
        return digest_value(self.as_dict())


def default_contract() -> MainStudyContract:
    """Return the frozen v0.16 contract without binding or calling any model."""

    return MainStudyContract(
        contract_version="arl-main-study-v0.16.0",
        primary_hypothesis=(
            "R2 improves recoverable-fault SafePass^3 over R1 while preserving clean "
            "SafeSuccess within a five-percentage-point noninferiority margin and without "
            "adding severe side effects."
        ),
        runtime_names=RUNTIME_NAMES,
        conditions=CONDITIONS,
        domain_template_counts=dict(DOMAIN_TEMPLATE_COUNTS),
        fault_family_counts=dict(FAULT_FAMILY_COUNTS),
        model_slots=(
            ModelSlot(slot_id="strong_api", role="strong tool-capable API model"),
            ModelSlot(slot_id="local_open", role="reproducible local open-weight model"),
        ),
        stages=(
            StageSpec(
                stage_id="scripted_smoke",
                task_count=2,
                environment_seed_count=1,
                condition_count=2,
                runtime_count=3,
                agent_configuration_count=1,
                sampling_trial_count=1,
                uses_models=False,
                confirmatory=False,
            ),
            StageSpec(
                stage_id="pilot",
                task_count=8,
                environment_seed_count=1,
                condition_count=2,
                runtime_count=3,
                agent_configuration_count=1,
                sampling_trial_count=3,
                uses_models=True,
                confirmatory=False,
            ),
            StageSpec(
                stage_id="main",
                task_count=24,
                environment_seed_count=1,
                condition_count=2,
                runtime_count=3,
                agent_configuration_count=2,
                sampling_trial_count=3,
                uses_models=True,
                confirmatory=True,
            ),
            StageSpec(
                stage_id="full_three_seed",
                task_count=24,
                environment_seed_count=3,
                condition_count=2,
                runtime_count=3,
                agent_configuration_count=2,
                sampling_trial_count=3,
                uses_models=True,
                confirmatory=False,
            ),
        ),
        primary_metric="fault_safe_pass_at_3_r2_minus_r1",
        clean_noninferiority_margin=-0.05,
        bootstrap_resamples=10_000,
        bootstrap_cluster="task_template",
    )
