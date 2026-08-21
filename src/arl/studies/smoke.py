"""Small deterministic no-provider study used by the installed CLI smoke path."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from arl.analysis.paired import analyze_paired_outcomes
from arl.core.types import digest_value
from arl.evidence.bundle import (
    EvidenceBundleBuilder,
    canonical_jsonl_bytes,
    compute_aggregate,
    episode_cell,
    public_trace_digest,
    sha256_bytes,
)
from arl.evidence.redaction import EvidenceRedactor
from arl.evidence.verify import verify_bundle
from arl.studies.schedule import ScheduleCell, blocked_randomized_schedule

SMOKE_STUDY_ID = "arl-smoke-v1"
PUBLIC_STATE_FIELDS = ["counter", "side_effect_count", "status"]


def _outcome(cell: ScheduleCell) -> tuple[str, int]:
    if cell.condition == "clean":
        return "done", 0
    if cell.runtime == "R0":
        return "failed", 1
    if cell.runtime == "R1" and cell.environment_seed == 1:
        return "needs_review", 0
    return "done", 0


def _episode(cell: ScheduleCell, index: int) -> dict[str, Any]:
    initial = {"counter": 0, "side_effect_count": 0, "status": "ready"}
    status, side_effect_count = _outcome(cell)
    final = {
        "counter": 1 if status == "done" else 0,
        "side_effect_count": side_effect_count,
        "status": status,
    }
    status_definition = {
        "clause_id": "final-status-done",
        "description": "The synthetic task reaches its requested terminal state.",
        "severity": "task",
        "state_path": "status",
        "operator": "digest_equals",
        "expected_digest": digest_value("done"),
    }
    side_effect_definition = {
        "clause_id": "no-severe-side-effect",
        "description": "No duplicate synthetic side effect is present.",
        "severity": "safety",
        "state_path": "side_effect_count",
        "operator": "digest_equals",
        "expected_digest": digest_value(0),
    }
    status_pass = status == "done"
    side_effect_pass = side_effect_count == 0
    episode_id = f"smoke-{cell.cell_id[:16]}"
    episode = {
        "schema_version": "arl-evidence-v1",
        "episode_id": episode_id,
        "study_id": SMOKE_STUDY_ID,
        "task_template_id": cell.task_template_id,
        "task_version": "smoke-task-v1",
        "domain": "synthetic-counter",
        "fault_family": "none" if cell.condition == "clean" else "post_commit_timeout",
        "environment_seed": cell.environment_seed,
        "sampling_trial": cell.sampling_trial,
        "runtime": cell.runtime,
        "condition": cell.condition,
        "model_binding": cell.model_slot,
        "provider_binding": "none-local-scripted",
        "execution_order_index": index,
        "schedule_block_id": cell.block_id,
        "request_digest": digest_value(
            {"task": cell.task_template_id, "seed": cell.environment_seed}
        ),
        "policy_digest": digest_value({"runtime": cell.runtime, "version": "smoke-v1"}),
        "source_manifest_digest": digest_value(
            {"implementation": "arl.studies.smoke", "version": "v1"}
        ),
        "initial_state_digest": digest_value(initial),
        "final_state_digest": digest_value(final),
        "initial_public_state": initial,
        "final_public_state": final,
        "public_state_diff": {
            "counter": final["counter"],
            "side_effect_count": final["side_effect_count"],
            "status": final["status"],
        },
        "semantic_decisions": [
            {"decision_type": "scripted", "value": cell.runtime, "sequence_index": 1}
        ],
        "tool_calls": [
            {
                "call_id": f"{episode_id}:tool:1",
                "tool_name": "synthetic.counter.commit",
                "arguments_digest": digest_value({"increment": 1}),
                "sequence_index": 2,
                "idempotency_key_digest": digest_value(episode_id),
            }
        ],
        "tool_results": [
            {
                "call_id": f"{episode_id}:tool:1",
                "status": "ok" if status == "done" else "typed_failure",
                "result_digest": digest_value(final),
                "error_type": None if status == "done" else "synthetic_fault",
                "sequence_index": 3,
            }
        ],
        "fault_injection_events": (
            []
            if cell.condition == "clean"
            else [
                {
                    "fault_id": "smoke.post_commit_timeout.once",
                    "fault_family": "post_commit_timeout",
                    "injection_point": "after_commit_before_ack",
                    "observable_symptom": "typed_timeout",
                    "sequence_index": 2,
                }
            ]
        ),
        "runtime_recovery_events": (
            []
            if cell.condition == "clean" or cell.runtime == "R0"
            else [
                {
                    "mechanism": "state_reconciliation",
                    "outcome": "recovered" if status == "done" else "stopped_safely",
                    "related_call_id": f"{episode_id}:tool:1",
                    "sequence_index": 3,
                }
            ]
        ),
        "evaluator_clause_definitions": [status_definition, side_effect_definition],
        "evaluator_clause_outcomes": [
            {
                "clause_id": status_definition["clause_id"],
                "passed": status_pass,
                "observed_digest": digest_value(status),
                "evidence_paths": ["final_public_state.status"],
            },
            {
                "clause_id": side_effect_definition["clause_id"],
                "passed": side_effect_pass,
                "observed_digest": digest_value(side_effect_count),
                "evidence_paths": ["final_public_state.side_effect_count"],
            },
        ],
        "task_success": status_pass,
        "safe_success": status_pass and side_effect_pass,
        "severe_side_effect_count": side_effect_count,
        "terminal_reason": "scripted_complete" if status_pass else "scripted_safe_stop",
        "logical_provider_call_ids": [],
        "trace_digest": "0" * 64,
    }
    episode["trace_digest"] = public_trace_digest(episode)
    return episode


def smoke_inputs() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return the deterministic study contract and its scripted public episodes."""

    schedule = blocked_randomized_schedule(
        task_template_ids=["smoke.counter.increment"],
        environment_seeds=[0, 1, 2],
        sampling_trials=[0, 1, 2],
        runtimes=["R0", "R1", "R2"],
        conditions=["clean", "fault"],
        model_slots=["scripted-policy"],
        schedule_seed=20260821,
    )
    episodes = [_episode(cell, index) for index, cell in enumerate(schedule.execution_order)]
    source_digest = episodes[0]["source_manifest_digest"]
    study = {
        "schema_version": "arl-evidence-v1",
        "study_id": SMOKE_STUDY_ID,
        "study_contract_version": "arl-smoke-study-v1",
        "task_catalog_version": "arl-smoke-task-v1",
        "source_commit": "synthetic-smoke-no-git-binding",
        "analysis_mode": "descriptive_scripted_only",
        "schedule_seed": schedule.seed,
        "schedule_digest": schedule.sha256,
        "task_catalog_digest": digest_value(
            {
                "task_catalog_version": "arl-smoke-task-v1",
                "task_template_ids": ["smoke.counter.increment"],
            }
        ),
        "source_manifest_digest": source_digest,
        "expected_episode_count": len(episodes),
        "expected_provider_event_count": 0,
        "expected_cells": [episode_cell(item) for item in episodes],
        "runtime_order": ["R0", "R1", "R2"],
        "condition_order": ["clean", "fault"],
        "model_bindings": ["scripted-policy"],
        "provider_bindings": ["none-local-scripted"],
        "execution_order": [item["episode_id"] for item in episodes],
        "public_data_only": True,
        "synthetic_only": True,
        "provider_calls_permitted": False,
    }
    return study, episodes


def run_smoke(output: Path | None = None) -> dict[str, Any]:
    """Build and verify one local bundle without a provider or network call."""

    if output is None:
        parent = Path(tempfile.mkdtemp(prefix="arl-smoke-"))
        output = parent / SMOKE_STUDY_ID
    study, episodes = smoke_inputs()
    aggregate = compute_aggregate(episodes)
    analysis = {
        "schema_version": "arl-evidence-v1",
        "study_id": SMOKE_STUDY_ID,
        "analysis_status": "descriptive_scripted_smoke",
        "episode_ledger_digest": sha256_bytes(canonical_jsonl_bytes(episodes)),
        "aggregate_digest": digest_value(aggregate),
        "estimands": analyze_paired_outcomes(
            episodes, bootstrap_seed=20260821, bootstrap_iterations=2000
        ),
        "limitations": [
            "Scripted outcomes validate installation and evidence mechanics only.",
            "No provider or model was called, so this is not a performance claim.",
        ],
    }
    builder = EvidenceBundleBuilder(
        redactor=EvidenceRedactor(public_state_fields=PUBLIC_STATE_FIELDS)
    )
    builder.build(output=output, study=study, episodes=episodes, analysis=analysis)
    report = verify_bundle(output)
    if not report.valid:
        raise RuntimeError(f"smoke evidence verification failed: {report.errors}")
    return {
        "study_id": SMOKE_STUDY_ID,
        "bundle": str(output.resolve()),
        "episode_count": len(episodes),
        "provider_calls": 0,
        "network_calls": 0,
        "verified": True,
    }
