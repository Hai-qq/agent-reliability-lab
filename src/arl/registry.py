"""Machine-readable claim and study status registry."""

from __future__ import annotations

from typing import Any

CLAIMS: tuple[dict[str, Any], ...] = (
    {
        "claim_id": "ARL-V028-INFRASTRUCTURE",
        "exact_claim_text": (
            "The saved v0.28 infrastructure checks passed, but Qwen readiness failed."
        ),
        "study_id": "opencode-go-flash-qwen-v0.28",
        "source_commit": "71792c832b17cbf362f3a4a14e7e81b2b14426e9",
        "study_contract_version": "v0.28",
        "task_catalog_version": "main-pack-v1",
        "model_provider_binding": "OpenCode Go gateway; Flash and Qwen slots",
        "preregistration_status": "registered contract; confirmatory gate not reached",
        "infrastructure_valid": True,
        "readiness_valid": False,
        "analysis_mode": "exploratory_only",
        "claim_status": "BLOCKED",
        "public_evidence_availability": "SUMMARY_AND_EXPLORATORY_ANALYSIS_ONLY",
        "independent_replication_status": "NOT_REPORTED",
        "limitations": [
            "Qwen readiness failed.",
            "No confirmatory claim is permitted.",
            (
                "Both model slots used the same gateway and do not establish "
                "cross-provider replication."
            ),
        ],
        "supersedes": None,
        "superseded_by": None,
    },
    {
        "claim_id": "ARL-V029-DESCRIPTIVE",
        "exact_claim_text": (
            "The v0.29 run completed 2,592 scheduled episodes, but its saved outcomes "
            "are descriptive only."
        ),
        "study_id": "opencode-go-holdout-v0.29",
        "source_commit": "71792c832b17cbf362f3a4a14e7e81b2b14426e9",
        "study_contract_version": "v0.29",
        "task_catalog_version": "holdout-pack-v1",
        "model_provider_binding": "OpenCode Go gateway; Flash and Qwen slots",
        "preregistration_status": "registered holdout; inference gates failed",
        "infrastructure_valid": False,
        "readiness_valid": False,
        "analysis_mode": "descriptive_aggregates_only",
        "claim_status": "INVALID_FOR_INFERENCE",
        "public_evidence_availability": "NOT_MATERIALIZED",
        "independent_replication_status": "NOT_REPORTED",
        "limitations": [
            "Two Qwen provider HTTP 503 outcomes were unrecovered.",
            "Four Qwen episodes violated the frozen monetary cap.",
            "Confirmatory and exploratory inference are blocked.",
            "The public checkout lacks the ignored full episode ledger and traces.",
            "Fixed serial execution order permits temporal/provider drift confounding.",
        ],
        "supersedes": None,
        "superseded_by": None,
    },
    {
        "claim_id": "ARL-V030-DESIGN",
        "exact_claim_text": (
            "v0.30 is a design and scripted-preflight contract; it contains no "
            "model-performance result."
        ),
        "study_id": "arl-study-v0.30.0",
        "source_commit": "PENDING_FUTURE_EXECUTION_COMMIT",
        "study_contract_version": "arl-study-v0.30.0",
        "task_catalog_version": "arl-planning-tasks-v0.30.0",
        "model_provider_binding": "UNBOUND_MODEL_SLOTS",
        "preregistration_status": "design_only_pending_external_execution",
        "infrastructure_valid": None,
        "readiness_valid": None,
        "analysis_mode": "preregistered_design_only",
        "claim_status": "NO_RESULTS",
        "public_evidence_availability": "SCRIPTED_FIXTURE_ONLY",
        "independent_replication_status": "PENDING_EXTERNAL_REPLICATION",
        "limitations": [
            "No provider was called.",
            "Scripted oracle checks are infrastructure tests, not agent outcomes.",
            "Model binding, pricing snapshot, and execution commit remain future inputs.",
        ],
        "supersedes": None,
        "superseded_by": None,
    },
)

STUDIES: tuple[dict[str, Any], ...] = (
    {
        "study_id": "opencode-go-flash-qwen-v0.28",
        "contract_version": "v0.28",
        "status": "blocked",
        "analysis": "exploratory_only",
        "public_episode_evidence": "not_materialized",
    },
    {
        "study_id": "opencode-go-holdout-v0.29",
        "contract_version": "v0.29",
        "status": "invalid",
        "analysis": "descriptive_only",
        "public_episode_evidence": "not_materialized",
    },
    {
        "study_id": "arl-study-v0.30.0",
        "contract_version": "arl-study-v0.30.0",
        "status": "design_only",
        "analysis": "preregistered_pending_execution",
        "public_episode_evidence": "scripted_fixture_only",
    },
    {
        "study_id": "arl-smoke-v1",
        "contract_version": "arl-smoke-study-v1",
        "status": "synthetic_smoke",
        "analysis": "descriptive_scripted_only",
        "public_episode_evidence": "materialized_example",
    },
)


def claims() -> list[dict[str, Any]]:
    """Return detached claim records safe for caller mutation."""

    return [dict(item) for item in CLAIMS]


def studies() -> list[dict[str, Any]]:
    """Return detached study records safe for caller mutation."""

    return [dict(item) for item in STUDIES]
