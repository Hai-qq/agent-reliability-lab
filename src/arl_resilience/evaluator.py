"""Evaluator evidence extension for cross-domain recovery contracts."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from arl.core.types import EvaluationReport


def add_resilience_evidence(
    report: EvaluationReport,
    trace_events: Sequence[dict[str, Any]],
) -> EvaluationReport:
    event_types = {"state_conflict_rebased", "compensation_contract_succeeded"}
    recovery_events = tuple(
        event["event_id"] for event in trace_events if event["event_type"] in event_types
    )
    merged = tuple(dict.fromkeys((*report.recovery_events, *recovery_events)))
    rebase_count = sum(event["event_type"] == "state_conflict_rebased" for event in trace_events)
    contract_count = sum(
        event["event_type"] == "compensation_contract_succeeded" for event in trace_events
    )
    return replace(
        report,
        recovery_events=merged,
        evidence=(
            *report.evidence,
            f"conflict_rebases={rebase_count}",
            f"compensation_contracts={contract_count}",
        ),
    )
