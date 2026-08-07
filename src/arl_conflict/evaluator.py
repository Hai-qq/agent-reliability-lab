"""Workspace evaluator extension for guarded conflict-recovery events."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from arl.core.types import EvaluationReport, SnapshotRef
from arl_multitask.evaluator import evaluate_workspace_multitask


def evaluate_workspace_conflict(
    pre_snapshot: SnapshotRef,
    post_snapshot: SnapshotRef,
    trace_events: Sequence[dict[str, Any]],
) -> EvaluationReport:
    """Preserve state scoring and add explicit guarded-rebase evidence."""
    report = evaluate_workspace_multitask(pre_snapshot, post_snapshot, trace_events)
    conflict_rebases = tuple(
        event["event_id"]
        for event in trace_events
        if event["event_type"] == "state_conflict_rebased"
    )
    recovery_events = tuple(dict.fromkeys((*report.recovery_events, *conflict_rebases)))
    return replace(
        report,
        recovery_events=recovery_events,
        evidence=(*report.evidence, f"conflict_rebases={len(conflict_rebases)}"),
    )
