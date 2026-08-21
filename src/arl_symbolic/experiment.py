"""Stateful symbolic-user benchmark with repeated paired statistics."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from arl.core.types import digest_value
from arl.history import verify_recorded_source_manifest
from arl.runtime.journal import EventJournal
from arl_scenarios.catalog import TASK_TEMPLATES, TEMPLATES_BY_ID
from arl_scenarios.experiment import run_episode as run_downstream_episode
from arl_symbolic import __version__
from arl_symbolic.protocol import (
    CONDITIONS,
    INTENT_SCHEMAS,
    AuthorizationToken,
    SymbolicUserSession,
    UserCondition,
    cohort_engaged,
)
from arl_symbolic.runtime import (
    POLICIES,
    OneShotAuthorizationRuntime,
    PolicyName,
    RevisionAwareAuthorizationRuntime,
)

SEEDS = (0, 1, 2, 3, 4)
REPEAT_INDICES = (0, 1, 2, 3, 4, 5)
RUN_ID = "symbolic-user-reliability-v0.13.0"
WILSON_Z = 1.959963984540054

_HISTORICAL_SUMMARIES = {
    "v0.1": "artifacts/workspace_paired/summary.json",
    "v0.2": "artifacts/workspace_r2_postcommit/summary.json",
    "v0.3": "artifacts/workspace_multitask_v03/summary.json",
    "v0.4": "artifacts/workspace_validity_v04/summary.json",
    "v0.5": "artifacts/retail_minimal_v05/summary.json",
    "v0.6": "artifacts/travel_minimal_v06/summary.json",
    "v0.7": "artifacts/schema_adapter_v07/summary.json",
    "v0.8": "artifacts/workspace_conflict_v08/summary.json",
    "v0.9": "artifacts/cross_domain_resilience_v09/summary.json",
    "v0.10": "artifacts/study_runtime_v10/summary.json",
    "v0.11": "artifacts/parallel_study_v11/summary.json",
    "v0.12": "artifacts/scenario_pack_v12/summary.json",
}


def _runtime(policy: PolicyName) -> OneShotAuthorizationRuntime | RevisionAwareAuthorizationRuntime:
    return (
        OneShotAuthorizationRuntime()
        if policy == "one_shot"
        else RevisionAwareAuthorizationRuntime()
    )


def run_symbolic_session(
    *,
    template_id: str,
    policy: PolicyName,
    condition: UserCondition,
    seed: int,
    repeat_index: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    template = TEMPLATES_BY_ID[template_id]
    pair_id = f"symbolic-{template.task_slug}-{condition}-seed-{seed}-repeat-{repeat_index}"
    episode_id = f"{pair_id}-{policy}"
    session = SymbolicUserSession(
        session_id=pair_id,
        template=template,
        condition=condition,
        seed=seed,
        repeat_index=repeat_index,
    )
    journal = EventJournal(
        run_id=RUN_ID,
        episode_id=episode_id,
        task_id=template.task_id,
        seed=seed,
        path=trace_path,
    )
    report = _runtime(policy).execute(session, journal)
    execution = report.as_dict()
    return {
        "session_id": episode_id,
        "pair_id": pair_id,
        "template_id": template_id,
        "task_id": template.task_id,
        "policy": policy,
        "condition": condition,
        "seed": seed,
        "repeat_index": repeat_index,
        "engaged": session.engaged,
        "execution": execution,
        "trace_file": trace_path.name if trace_path is not None else None,
        "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
        "trace_event_count": len(journal.events),
    }


def _run_matrix(traces_dir: Path | None) -> list[dict[str, Any]]:
    sessions = []
    for template in TASK_TEMPLATES:
        for policy in POLICIES:
            for condition in CONDITIONS:
                for repeat_index in REPEAT_INDICES:
                    for seed in SEEDS:
                        pair_id = (
                            f"symbolic-{template.task_slug}-{condition}-seed-{seed}-"
                            f"repeat-{repeat_index}"
                        )
                        episode_id = f"{pair_id}-{policy}"
                        trace_path = traces_dir / f"{episode_id}.jsonl" if traces_dir else None
                        sessions.append(
                            run_symbolic_session(
                                template_id=template.template_id,
                                policy=policy,
                                condition=condition,
                                seed=seed,
                                repeat_index=repeat_index,
                                trace_path=trace_path,
                            )
                        )
    return sessions


def wilson_interval(successes: int, total: int, z: float = WILSON_Z) -> dict[str, float]:
    if total < 1 or successes < 0 or successes > total:
        raise ValueError("Wilson interval requires 0 <= successes <= total and total > 0")
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(proportion * (1 - proportion) / total + z * z / (4 * total * total))
        / denominator
    )
    return {
        "level": 0.95,
        "method": "wilson_score",
        "lower": max(0.0, center - margin),
        "upper": min(1.0, center + margin),
    }


def _repeat_rates(items: Sequence[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    values = []
    for repeat_index in REPEAT_INDICES:
        selected = [item for item in items if item["repeat_index"] == repeat_index]
        successes = sum(bool(item["execution"][field]) for item in selected)
        values.append(
            {
                "repeat_index": repeat_index,
                "successes": successes,
                "total": len(selected),
                "rate": successes / len(selected),
            }
        )
    return values


def _descriptive(values: Sequence[float]) -> dict[str, float]:
    return {
        "mean": statistics.mean(values),
        "sample_stdev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def _group_metrics(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    task_successes = sum(item["execution"]["task_success"] for item in items)
    safe_successes = sum(item["execution"]["safe_success"] for item in items)
    unsafe_commits = sum(item["execution"]["unsafe_commit"] for item in items)
    safe_aborts = sum(item["execution"]["safe_abort"] for item in items)
    repeat_safe = _repeat_rates(items, "safe_success")
    repeat_unsafe = _repeat_rates(items, "unsafe_commit")
    return {
        "sessions": total,
        "task_successes": task_successes,
        "task_success_rate": task_successes / total,
        "task_success_interval": wilson_interval(task_successes, total),
        "safe_successes": safe_successes,
        "safe_success_rate": safe_successes / total,
        "safe_success_interval": wilson_interval(safe_successes, total),
        "unsafe_commits": unsafe_commits,
        "unsafe_commit_rate": unsafe_commits / total,
        "unsafe_commit_interval": wilson_interval(unsafe_commits, total),
        "safe_aborts": safe_aborts,
        "safe_abort_rate": safe_aborts / total,
        "per_repeat_safe_success": repeat_safe,
        "safe_success_repeat_summary": _descriptive([item["rate"] for item in repeat_safe]),
        "per_repeat_unsafe_commit": repeat_unsafe,
        "unsafe_commit_repeat_summary": _descriptive([item["rate"] for item in repeat_unsafe]),
        "mean_user_requests": statistics.mean(
            item["execution"]["user_request_count"] for item in items
        ),
        "mean_authorization_checks": statistics.mean(
            item["execution"]["authorization_check_count"] for item in items
        ),
    }


def _paired_delta(
    sessions: Sequence[dict[str, Any]],
    condition: UserCondition,
) -> dict[str, Any]:
    deltas = []
    rows = []
    for repeat_index in REPEAT_INDICES:
        selected = [
            item
            for item in sessions
            if item["condition"] == condition and item["repeat_index"] == repeat_index
        ]
        baseline = [item for item in selected if item["policy"] == "one_shot"]
        guarded = [item for item in selected if item["policy"] == "revision_aware"]
        baseline_rate = sum(item["execution"]["safe_success"] for item in baseline) / len(baseline)
        guarded_rate = sum(item["execution"]["safe_success"] for item in guarded) / len(guarded)
        delta = guarded_rate - baseline_rate
        deltas.append(delta)
        rows.append(
            {
                "repeat_index": repeat_index,
                "one_shot_rate": baseline_rate,
                "revision_aware_rate": guarded_rate,
                "delta": delta,
            }
        )
    summary = _descriptive(deltas)
    half_width = WILSON_Z * summary["sample_stdev"] / math.sqrt(len(deltas))
    return {
        "condition": condition,
        "per_repeat": rows,
        **summary,
        "normal_approx_95_interval": {
            "lower": max(-1.0, summary["mean"] - half_width),
            "upper": min(1.0, summary["mean"] + half_width),
        },
    }


def build_statistics(sessions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_policy = {
        policy: {
            condition: _group_metrics(
                [
                    item
                    for item in sessions
                    if item["policy"] == policy and item["condition"] == condition
                ]
            )
            for condition in CONDITIONS
        }
        for policy in POLICIES
    }
    by_template = {
        template.template_id: {
            policy: _group_metrics(
                [
                    item
                    for item in sessions
                    if item["template_id"] == template.template_id and item["policy"] == policy
                ]
            )
            for policy in POLICIES
        }
        for template in TASK_TEMPLATES
    }
    return {
        "session_count": len(sessions),
        "template_count": len(TASK_TEMPLATES),
        "seed_count": len(SEEDS),
        "repeat_count": len(REPEAT_INDICES),
        "policy_count": len(POLICIES),
        "condition_count": len(CONDITIONS),
        "by_policy": by_policy,
        "by_template": by_template,
        "paired_safe_success_delta": {
            condition: _paired_delta(sessions, condition) for condition in CONDITIONS
        },
    }


def historical_source_manifest_check(project_root: Path) -> dict[str, Any]:
    increments: dict[str, Any] = {}
    for version, relative_summary in _HISTORICAL_SUMMARIES.items():
        summary = json.loads((project_root / relative_summary).read_text(encoding="utf-8"))
        expected = summary["metadata"]["source_manifest"]
        increments[version] = {
            "summary": relative_summary,
            **verify_recorded_source_manifest(project_root, expected),
        }
    return {
        "increments": increments,
        "passed": all(item["matched"] for item in increments.values()),
    }


def _intent_schema_check() -> dict[str, Any]:
    descriptors = [item.audit_descriptor() for item in INTENT_SCHEMAS]
    cases = {
        "one_schema_per_template": len(descriptors) == len(TASK_TEMPLATES),
        "unique_template_ids": len({item.template_id for item in INTENT_SCHEMAS})
        == len(INTENT_SCHEMAS),
        "digest_linked": all(
            descriptor["schema_digest"]
            == digest_value(
                {key: value for key, value in descriptor.items() if key != "schema_digest"}
            )
            for descriptor in descriptors
        ),
    }
    return {"descriptors": descriptors, "cases": cases, "passed": all(cases.values())}


def _authorization_fencing_check() -> dict[str, Any]:
    template = TASK_TEMPLATES[0]
    session = SymbolicUserSession(
        session_id="fencing-check",
        template=template,
        condition="precommit_revision",
        seed=0,
        repeat_index=0,
    )
    response = session.request_authorization()
    assert response.token is not None
    current_before = session.authorization_status(response.token)
    session.revise_before_commit()
    stale_after = session.authorization_status(response.token)
    tampered = AuthorizationToken(
        session_id=response.token.session_id,
        revision=response.token.revision,
        intent_digest=response.token.intent_digest,
        token_digest="tampered",
    )
    cases = {
        "current_token_accepted": current_before == "current",
        "revision_stales_token": stale_after == "stale",
        "tampered_token_invalid": session.authorization_status(tampered) == "invalid",
    }
    return {"cases": cases, "passed": all(cases.values())}


def _downstream_state_gate() -> dict[str, Any]:
    results = {}
    for template in TASK_TEMPLATES:
        authorization = run_symbolic_session(
            template_id=template.template_id,
            policy="revision_aware",
            condition="direct_approval",
            seed=0,
            repeat_index=0,
            trace_path=None,
        )
        downstream = run_downstream_episode(
            template_id=template.template_id,
            runtime_name="r2_template_guarded",
            condition="control",
            seed=0,
            trace_path=None,
        )
        results[template.template_id] = {
            "authorization_safe_success": authorization["execution"]["safe_success"],
            "downstream_state_safe_success": downstream["evaluation"]["safe_success"],
        }
    return {
        "templates": results,
        "passed": all(
            item["authorization_safe_success"] and item["downstream_state_safe_success"]
            for item in results.values()
        ),
    }


def _statistics_check(statistics_value: dict[str, Any]) -> dict[str, Any]:
    by_policy = statistics_value["by_policy"]
    cases = {
        "direct_both_perfect": all(
            by_policy[policy]["direct_approval"]["safe_success_rate"] == 1.0 for policy in POLICIES
        ),
        "one_shot_non_direct_unsafe": all(
            by_policy["one_shot"][condition]["unsafe_commit_rate"] == 1.0
            for condition in ("clarification_required", "precommit_revision")
        ),
        "revision_aware_never_unsafe": all(
            by_policy["revision_aware"][condition]["unsafe_commit_rate"] == 0.0
            for condition in CONDITIONS
        ),
        "clarification_delta_positive": statistics_value["paired_safe_success_delta"][
            "clarification_required"
        ]["mean"]
        > 0.0,
        "revision_delta_positive": statistics_value["paired_safe_success_delta"][
            "precommit_revision"
        ]["mean"]
        > 0.0,
        "non_direct_repeat_variation": all(
            by_policy["revision_aware"][condition]["safe_success_repeat_summary"]["sample_stdev"]
            > 0.0
            for condition in ("clarification_required", "precommit_revision")
        ),
    }
    interval_contains_rates = True
    for policy in POLICIES:
        for condition in CONDITIONS:
            group = by_policy[policy][condition]
            for prefix in ("safe_success", "unsafe_commit"):
                rate = group[f"{prefix}_rate"]
                interval = group[f"{prefix}_interval"]
                interval_contains_rates &= interval["lower"] <= rate <= interval["upper"]
    cases["wilson_intervals_contain_observed_rates"] = interval_contains_rates
    return {"cases": cases, "passed": all(cases.values())}


def _validity_checks(
    sessions: Sequence[dict[str, Any]],
    traces_dir: Path,
    project_root: Path,
    statistics_value: dict[str, Any],
) -> dict[str, Any]:
    trace_count = len(list(traces_dir.glob("*.jsonl")))
    checks: dict[str, Any] = {
        "matrix_shape": {
            "sessions": len(sessions),
            "trace_files": trace_count,
            "passed": len(sessions) == 720 and trace_count == 720,
        },
        "intent_schema_contracts": _intent_schema_check(),
        "authorization_token_fencing": _authorization_fencing_check(),
        "statistics": _statistics_check(statistics_value),
        "downstream_state_gate": _downstream_state_gate(),
        "historical_source_manifests": historical_source_manifest_check(project_root),
    }
    pairs: dict[str, list[dict[str, Any]]] = {}
    for item in sessions:
        pairs.setdefault(item["pair_id"], []).append(item)
    checks["paired_cohorts"] = {
        "pair_count": len(pairs),
        "passed": len(pairs) == 360
        and all(
            len(items) == 2
            and {item["policy"] for item in items} == set(POLICIES)
            and len({item["engaged"] for item in items}) == 1
            for items in pairs.values()
        ),
    }
    expected_engagement = all(
        item["engaged"]
        == cohort_engaged(
            item["template_id"],
            item["condition"],
            item["seed"],
            item["repeat_index"],
        )
        for item in sessions
    )
    checks["deterministic_user_cohorts"] = {"passed": expected_engagement}
    serialized = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden = [
        marker
        for marker in (
            b'"engaged"',
            b'"selection"',
            b'"refund_item"',
            b'"origin"',
            b'"fallback_allowed"',
            b'"arguments"',
            b'"visible_task"',
            b"synthetic-",
        )
        if marker in serialized
    ]
    checks["digest_only_traces"] = {
        "files_checked": trace_count,
        "forbidden_payload_markers": [item.decode() for item in forbidden],
        "passed": not forbidden,
    }
    return checks


def _normalize(sessions: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    values = []
    for session in sessions:
        item = dict(session)
        item.pop("trace_file", None)
        values.append(item)
    return values


def run_symbolic_experiment(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    primary = _run_matrix(traces_dir)
    shadow = _run_matrix(None)
    statistics_value = build_statistics(primary)
    validity = _validity_checks(primary, traces_dir, project_root, statistics_value)
    validity["repeat_results_deterministic"] = {"passed": _normalize(primary) == _normalize(shadow)}
    validity["all_selected_checks_passed"] = all(
        value["passed"] for key, value in validity.items() if key != "all_selected_checks_passed"
    )
    if not validity["all_selected_checks_passed"]:
        failed = [
            key
            for key, value in validity.items()
            if key != "all_selected_checks_passed" and not value.get("passed", False)
        ]
        raise AssertionError(f"Symbolic-user validity gates failed: {failed}")

    return {
        "metadata": {
            "increment_version": __version__,
            "root_project_version": "0.3.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "run_id": RUN_ID,
            "template_ids": [item.template_id for item in TASK_TEMPLATES],
            "policies": list(POLICIES),
            "conditions": list(CONDITIONS),
            "seeds": list(SEEDS),
            "repeat_indices": list(REPEAT_INDICES),
            "confidence_interval": {"method": "wilson_score", "level": 0.95},
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "intent_schemas": [item.audit_descriptor() for item in INTENT_SCHEMAS],
        "sessions": primary,
        "statistics": statistics_value,
        "validity": validity,
        "limitations": [
            "Finite-state symbolic users with structured responses, not natural-language models.",
            "Six fixed repeats and five seeds over four existing reliability templates.",
            "Deterministic engagement cohorts approximate abandonment; no population claim.",
            "Wilson intervals summarize this fixed synthetic sample, not real-user uncertainty.",
            "No model, API, network, account, credential, personal data, or real system.",
        ],
    }
