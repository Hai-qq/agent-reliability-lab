"""R2 evaluator adapter that recognizes state-confirmation recovery evidence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from arl.core.types import EvaluationReport, SnapshotRef
from arl.evaluators.workspace import evaluate_workspace


def evaluate_workspace_r2(
    pre_snapshot: SnapshotRef,
    post_snapshot: SnapshotRef,
    trace_events: Sequence[dict[str, Any]],
) -> EvaluationReport:
    report = evaluate_workspace(pre_snapshot, post_snapshot, trace_events)
    recovery_events = tuple(
        event["event_id"]
        for event in trace_events
        if event["event_type"] in {"retry_scheduled", "state_confirmation_succeeded"}
    )
    return replace(report, recovery_events=recovery_events)
