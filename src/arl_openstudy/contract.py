"""Exact OpenCode Go bindings and prospective two-model study amendment."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from arl.core.types import digest_value
from arl_mainstudy.contract import MainStudyContract, ModelSlot, default_contract
from arl_mainstudy.model import ExactModelBinding

OPENCODE_GO_CATALOG_SNAPSHOT_DATE = "2026-08-09"
OPENCODE_GO_ENDPOINT = "https://opencode.ai/zen/go/v1/chat/completions"
OPENCODE_GO_MODELS_ENDPOINT = "https://opencode.ai/zen/go/v1/models"

FLASH_BINDING = ExactModelBinding(
    provider="opencode-go",
    model_id="deepseek-v4-flash",
    revision=f"listing-{OPENCODE_GO_CATALOG_SNAPSHOT_DATE}/non-thinking",
)
MIMO_BINDING = ExactModelBinding(
    provider="opencode-go",
    model_id="mimo-v2.5",
    revision=f"listing-{OPENCODE_GO_CATALOG_SNAPSHOT_DATE}/default-inference",
)
MODEL_BINDINGS = {
    "flash": FLASH_BINDING,
    "mimo": MIMO_BINDING,
}


def openstudy_contract() -> MainStudyContract:
    """Bind the frozen 864-episode arithmetic to two distinct Go models."""

    base = default_contract()
    contract = replace(
        base,
        contract_version="arl-main-study-v0.27.0-opencode-go-two-model-amendment",
        primary_hypothesis=(
            "For both OpenCode Go DeepSeek V4 Flash and MiMo-V2.5, R2 improves "
            "recoverable-fault SafePass^3 over R1 while preserving clean SafeSuccess "
            "within a five-percentage-point noninferiority margin and without adding "
            "severe side effects."
        ),
        model_slots=(
            ModelSlot(
                slot_id="flash",
                role="OpenCode Go DeepSeek V4 Flash non-thinking model",
                provider=FLASH_BINDING.provider,
                model_id=FLASH_BINDING.model_id,
                revision=FLASH_BINDING.revision,
            ),
            ModelSlot(
                slot_id="mimo",
                role="OpenCode Go low-cost MiMo-V2.5 comparison model",
                provider=MIMO_BINDING.provider,
                model_id=MIMO_BINDING.model_id,
                revision=MIMO_BINDING.revision,
            ),
        ),
    )
    contract.assert_ready("main")
    return contract


def amendment_record() -> dict[str, Any]:
    """Disclose provider migration, model-selection basis, and claim boundary."""

    record: dict[str, Any] = {
        "amendment_version": "arl-opencode-go-two-model-amendment-v1",
        "effective_date": "2026-08-09",
        "provider_gateway": "OpenCode Go",
        "endpoint": OPENCODE_GO_ENDPOINT,
        "selection_frozen_before_opencode_benchmark_canary": True,
        "prior_direct_deepseek_result_observed": True,
        "prior_result_included_in_new_864_matrix": False,
        "second_model_selection_basis": [
            "lowest published Go input/output price tier",
            "OpenAI-compatible chat-completions endpoint",
            "successful structured tool-call compatibility probe",
            "zero-day published data retention",
        ],
        "cross_model_consistency_claim_allowed": True,
        "cross_provider_generalization_claimed": False,
        "bindings": [MODEL_BINDINGS[slot].as_dict() for slot in ("flash", "mimo")],
    }
    return {**record, "sha256": digest_value(record)}
