"""Four-template reliability and compensation-workflow experiment."""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from arl.core.types import Observation, canonical_json, digest_value
from arl.history import verify_recorded_source_manifest
from arl.runtime.journal import EventJournal
from arl_resilience.contracts import GuardedAction, StateGuard
from arl_resilience.evaluator import add_resilience_evidence
from arl_resilience.runtime import RetailResilienceRuntime
from arl_retail.env import PURCHASE_TASK_ID, REFUND_TASK_ID
from arl_retail.env import SCHEMA_VERSION as RETAIL_SCHEMA_VERSION
from arl_retail.evaluator import evaluate_retail
from arl_retail.experiment import task_actions as retail_task_actions
from arl_retail.runtime import RetailRuntime
from arl_scenarios import __version__
from arl_scenarios.catalog import (
    TASK_TEMPLATES,
    TEMPLATES_BY_ID,
    ReliabilityTaskTemplate,
)
from arl_scenarios.env import (
    ConflictMode,
    ScenarioRetailEnvironment,
    ScenarioTravelEnvironment,
)
from arl_scenarios.workflow import (
    CompensationWorkflowContract,
    ScenarioTravelRuntime,
    build_travel_scenario_plan,
)
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID
from arl_travel.evaluator import evaluate_travel
from arl_travel.experiment import task_plan as travel_task_plan
from arl_travel.runtime import TravelRuntime

SEEDS = (0, 1, 2)
RUNTIMES = ("r2_confirmed", "r2_template_guarded")
CONDITIONS = ("control", "compatible_conflict", "incompatible_conflict")
RUN_ID = "reliability-scenario-pack-v0.12.0"

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
}


def _mode(condition: str) -> ConflictMode:
    values: dict[str, ConflictMode] = {
        "control": "none",
        "compatible_conflict": "compatible_conflict",
        "incompatible_conflict": "incompatible_conflict",
    }
    return values[condition]


def build_retail_scenario_plan(observation: Observation) -> list[GuardedAction]:
    actions = retail_task_actions(observation, "r2_confirmed")
    task = observation.visible_task
    if observation.task_id == PURCHASE_TASK_ID:
        guard = StateGuard(
            tool_name="orders.get_order",
            schema_version=RETAIL_SCHEMA_VERSION,
            arguments={"order_id": task["order_id"]},
            value_path=("order", "status"),
            expected_value="placed",
        )
        conflict_tool = "retail.resolve_purchase_request"
    elif observation.task_id == REFUND_TASK_ID:
        guard = StateGuard(
            tool_name="refunds.get_refund",
            schema_version=RETAIL_SCHEMA_VERSION,
            arguments={"refund_id": task["refund_id"]},
            value_path=("refund", "status"),
            expected_value="issued",
        )
        conflict_tool = "retail.resolve_refund_request"
    else:  # pragma: no cover - environment validates the task
        raise ValueError(f"Unsupported Retail task: {observation.task_id}")
    return [
        GuardedAction(action=action, guards=(guard,) if action.tool_name == conflict_tool else ())
        for action in actions
    ]


def _normalized_baseline_report(report: Any) -> dict[str, Any]:
    value = report.as_dict()
    failure_code = value["failure_code"]
    value.setdefault("recovery_actions_planned", 0)
    value.setdefault("recovery_branch_count", 0)
    value.setdefault("compensation_count", 0)
    value.update(
        {
            "conflict_count": int(failure_code == "state_version_conflict"),
            "conflict_probe_count": 0,
            "conflict_rebase_count": 0,
            "conflict_abort_count": int(failure_code == "state_version_conflict"),
            "compensation_contract_attempt_count": 0,
            "compensation_contract_success_count": 0,
            "compensation_contract_failure_count": 0,
            "compensation_probe_count": 0,
            "workflow_contract_attempt_count": 0,
            "workflow_contract_success_count": 0,
            "workflow_contract_failure_count": 0,
            "workflow_terminal_probe_count": 0,
        }
    )
    return value


def _extended_retail_report(report: Any) -> dict[str, Any]:
    value = report.as_dict()
    value["runtime_name"] = "r2_template_guarded"
    value.update(
        {
            "workflow_contract_attempt_count": 0,
            "workflow_contract_success_count": 0,
            "workflow_contract_failure_count": 0,
            "workflow_terminal_probe_count": 0,
        }
    )
    return value


def _rows_by_id(rows: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {row[key]: row for row in rows}


def _final_state(template: ReliabilityTaskTemplate, world: dict[str, Any]) -> dict[str, Any]:
    task = world["task"]
    if template.task_id == PURCHASE_TASK_ID:
        orders = _rows_by_id(world["orders"], "order_id")
        requests = _rows_by_id(world["purchase_requests"], "request_id")
        target = orders.get(task["order_id"])
        return {
            "conflict_target_status": target["status"] if target else None,
            "request_status": requests[task["request_id"]]["status"],
            "result_count": len(world["orders"]),
        }
    if template.task_id == REFUND_TASK_ID:
        refunds = _rows_by_id(world["refunds"], "refund_id")
        requests = _rows_by_id(world["refund_requests"], "request_id")
        target = refunds.get(task["refund_id"])
        return {
            "conflict_target_status": target["status"] if target else None,
            "request_status": requests[task["request_id"]]["status"],
            "result_count": len(world["refunds"]),
        }
    bookings = _rows_by_id(world["flight_bookings"], "booking_id")
    reservations = _rows_by_id(world["hotel_reservations"], "reservation_id")
    requests = _rows_by_id(world["booking_requests"], "request_id")
    if template.task_id == BOOK_TASK_ID:
        reservation = reservations.get(task["hotel_reservation_id"])
        booking = bookings.get(task["flight_booking_id"])
        return {
            "conflict_target_status": reservation["status"] if reservation else None,
            "flight_status": booking["status"] if booking else None,
            "request_status": requests[task["request_id"]]["status"],
            "result_count": len(bookings) + len(reservations),
        }
    preferred = reservations.get(task["preferred_hotel_reservation_id"])
    backup_hotel = reservations.get(task["backup_hotel_reservation_id"])
    backup_flight = bookings.get(task["backup_flight_booking_id"])
    return {
        "conflict_target_status": preferred["status"] if preferred else None,
        "backup_hotel_status": backup_hotel["status"] if backup_hotel else None,
        "backup_flight_status": backup_flight["status"] if backup_flight else None,
        "request_status": requests[task["request_id"]]["status"],
        "result_count": len(bookings) + len(reservations),
    }


def run_episode(
    *,
    template_id: str,
    runtime_name: str,
    condition: str,
    seed: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    template = TEMPLATES_BY_ID[template_id]
    episode_id = f"scenario-{template.task_slug}-seed-{seed}-{runtime_name}-{condition}"
    environment: ScenarioRetailEnvironment | ScenarioTravelEnvironment
    environment = (
        ScenarioRetailEnvironment(template, _mode(condition))
        if template.domain == "retail"
        else ScenarioTravelEnvironment(template, _mode(condition))
    )
    try:
        observation = environment.reset(template.task_id, seed)
        initial_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=RUN_ID,
            episode_id=episode_id,
            task_id=template.task_id,
            seed=seed,
            path=trace_path,
        )
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="harness",
            event_type="episode_started",
            state_hash_before=initial_hash,
            state_hash_after=initial_hash,
            input_digest=digest_value(
                {
                    "template": template.audit_descriptor(),
                    "runtime": runtime_name,
                    "condition": condition,
                    "observation": observation.as_dict(),
                }
            ),
        )
        if template.domain == "retail":
            assert isinstance(environment, ScenarioRetailEnvironment)
            plan = build_retail_scenario_plan(observation)
            if runtime_name == "r2_template_guarded":
                execution = _extended_retail_report(
                    RetailResilienceRuntime().execute(environment, plan, journal)
                )
            else:
                execution = _normalized_baseline_report(
                    RetailRuntime("r2_confirmed").execute(
                        environment,
                        [item.action for item in plan],
                        journal,
                    )
                )
            evaluation = evaluate_retail(
                initial_snapshot,
                environment.snapshot(),
                journal.as_dicts(),
            )
        else:
            assert isinstance(environment, ScenarioTravelEnvironment)
            scenario_plan = build_travel_scenario_plan(observation)
            if runtime_name == "r2_template_guarded":
                execution = ScenarioTravelRuntime().execute(
                    environment,
                    scenario_plan,
                    journal,
                )
            else:
                execution = _normalized_baseline_report(
                    TravelRuntime("r2_confirmed").execute(
                        environment,
                        travel_task_plan(observation, "r2_confirmed"),
                        journal,
                    )
                )
            evaluation = evaluate_travel(
                initial_snapshot,
                environment.snapshot(),
                journal.as_dicts(),
            )
        evaluation = add_resilience_evidence(evaluation, journal.as_dicts())
        final_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="evaluator",
            event_type="evaluation_completed",
            state_hash_before=final_hash,
            state_hash_after=final_hash,
            output_digest=digest_value(evaluation.as_dict()),
        )
        events = journal.as_dicts()
        world = environment.export_world()
        return {
            "episode_id": episode_id,
            "template_id": template.template_id,
            "domain": template.domain,
            "task_id": template.task_id,
            "seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "conflict_mode": _mode(condition),
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "execution": execution,
            "evaluation": evaluation.as_dict(),
            "observed_fault_ids": sorted(
                {event["fault_id"] for event in events if event["fault_id"]}
            ),
            "final_state": _final_state(template, world),
            "trace_file": trace_path.name if trace_path is not None else None,
            "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
            "trace_event_count": len(journal.events),
        }
    finally:
        environment.close()


def _run_matrix(traces_dir: Path | None) -> list[dict[str, Any]]:
    episodes = []
    for template in TASK_TEMPLATES:
        for runtime_name in RUNTIMES:
            for condition in CONDITIONS:
                for seed in SEEDS:
                    episode_id = (
                        f"scenario-{template.task_slug}-seed-{seed}-{runtime_name}-{condition}"
                    )
                    trace_path = traces_dir / f"{episode_id}.jsonl" if traces_dir else None
                    episodes.append(
                        run_episode(
                            template_id=template.template_id,
                            runtime_name=runtime_name,
                            condition=condition,
                            seed=seed,
                            trace_path=trace_path,
                        )
                    )
    return episodes


def _selection_aggregate(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_condition = {
        condition: {
            "task_successes": sum(
                item["evaluation"]["task_success"]
                for item in episodes
                if item["condition"] == condition
            ),
            "safe_successes": sum(
                item["evaluation"]["safe_success"]
                for item in episodes
                if item["condition"] == condition
            ),
            "total": sum(item["condition"] == condition for item in episodes),
        }
        for condition in CONDITIONS
    }
    incompatible = [item for item in episodes if item["condition"] == "incompatible_conflict"]
    return {
        "episode_count": len(episodes),
        "by_condition": by_condition,
        "compatible_conflict_recovery_rate": (
            by_condition["compatible_conflict"]["task_successes"]
            / by_condition["compatible_conflict"]["total"]
        ),
        "incompatible_conflict_classified_abort_rate": (
            sum(
                item["execution"]["failure_code"] == "conflict_precondition_changed"
                for item in incompatible
            )
            / len(incompatible)
        ),
        "conflict_count": sum(item["execution"]["conflict_count"] for item in episodes),
        "conflict_rebase_count": sum(
            item["execution"]["conflict_rebase_count"] for item in episodes
        ),
        "workflow_attempt_count": sum(
            item["execution"]["workflow_contract_attempt_count"] for item in episodes
        ),
        "workflow_success_count": sum(
            item["execution"]["workflow_contract_success_count"] for item in episodes
        ),
        "workflow_failure_count": sum(
            item["execution"]["workflow_contract_failure_count"] for item in episodes
        ),
    }


def _aggregate(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_runtime = {
        runtime: _selection_aggregate([item for item in episodes if item["runtime"] == runtime])
        for runtime in RUNTIMES
    }
    by_template = {
        template.template_id: {
            runtime: _selection_aggregate(
                [
                    item
                    for item in episodes
                    if item["template_id"] == template.template_id and item["runtime"] == runtime
                ]
            )
            for runtime in RUNTIMES
        }
        for template in TASK_TEMPLATES
    }
    return {
        "episode_count": len(episodes),
        "template_count": len(TASK_TEMPLATES),
        "domain_count": len({item.domain for item in TASK_TEMPLATES}),
        "seed_count": len(SEEDS),
        "runtime_count": len(RUNTIMES),
        "condition_count": len(CONDITIONS),
        "by_runtime": by_runtime,
        "by_template": by_template,
        "compatible_recovery_rate_delta": (
            by_runtime["r2_template_guarded"]["compatible_conflict_recovery_rate"]
            - by_runtime["r2_confirmed"]["compatible_conflict_recovery_rate"]
        ),
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


def _expected_fault_ids(
    template: ReliabilityTaskTemplate,
    condition: str,
) -> list[str]:
    values = []
    if template.task_id == RECOVERY_TASK_ID:
        values.append("fault.travel.preferred_flight.unavailable")
    if condition == "compatible_conflict":
        values.append(template.compatible_fault_id)
    elif condition == "incompatible_conflict":
        values.append(template.incompatible_fault_id)
    return sorted(values)


def _catalog_check() -> dict[str, Any]:
    descriptors = [item.audit_descriptor() for item in TASK_TEMPLATES]
    cases = {
        "four_unique_templates": len({item.template_id for item in TASK_TEMPLATES}) == 4,
        "four_tasks": len({item.task_id for item in TASK_TEMPLATES}) == 4,
        "four_conflict_tools": len({item.conflict_tool for item in TASK_TEMPLATES}) == 4,
        "two_domains": {item.domain for item in TASK_TEMPLATES} == {"retail", "travel"},
        "workflow_registered": sum(
            item.compensation_type == "bounded_workflow" for item in TASK_TEMPLATES
        )
        == 1,
        "descriptors_digest_linked": all(
            descriptor["template_digest"]
            == digest_value(
                {key: value for key, value in descriptor.items() if key != "template_digest"}
            )
            for descriptor in descriptors
        ),
    }
    return {"descriptors": descriptors, "cases": cases, "passed": all(cases.values())}


def _workflow_contract_check() -> dict[str, Any]:
    template = next(item for item in TASK_TEMPLATES if item.task_id == RECOVERY_TASK_ID)
    environment = ScenarioTravelEnvironment(template, "none")
    try:
        observation = environment.reset(template.task_id, 0)
        workflow = build_travel_scenario_plan(observation).workflow
        assert workflow is not None
    finally:
        environment.close()
    rejected = 0
    mutations = (
        {"max_attempts": 2},
        {"steps": workflow.steps[:1]},
        {"terminal_postconditions": ()},
    )
    for changes in mutations:
        values = {
            "contract_id": workflow.contract_id,
            "trigger_tool": workflow.trigger_tool,
            "trigger_error": workflow.trigger_error,
            "steps": workflow.steps,
            "terminal_postconditions": workflow.terminal_postconditions,
            "max_attempts": workflow.max_attempts,
            **changes,
        }
        try:
            CompensationWorkflowContract(**values)
        except ValueError:
            rejected += 1
    try:
        replace(
            workflow.steps[0],
            action=replace(workflow.steps[0].action, idempotency_key=None),
        )
    except ValueError:
        rejected += 1
    serialized = canonical_json(workflow.audit_descriptor())
    cases = {
        "four_bounded_steps": len(workflow.steps) == 4,
        "six_terminal_guards": len(workflow.terminal_postconditions) == 6,
        "invalid_mutations_rejected": rejected == len(mutations) + 1,
        "digest_only_descriptor": "synthetic-" not in serialized,
    }
    return {"cases": cases, "passed": all(cases.values())}


def _baseline_and_reset_check() -> dict[str, Any]:
    do_nothing: dict[str, bool] = {}
    restore_replays: dict[str, bool] = {}
    for template in TASK_TEMPLATES:
        environment: ScenarioRetailEnvironment | ScenarioTravelEnvironment
        environment = (
            ScenarioRetailEnvironment(template, "compatible_conflict")
            if template.domain == "retail"
            else ScenarioTravelEnvironment(template, "compatible_conflict")
        )
        try:
            observation = environment.reset(template.task_id, 0)
            initial = environment.snapshot()
            evaluation = (
                evaluate_retail(initial, initial, [])
                if template.domain == "retail"
                else evaluate_travel(initial, initial, [])
            )
            do_nothing[template.template_id] = not evaluation.task_success
            first = run_episode(
                template_id=template.template_id,
                runtime_name="r2_template_guarded",
                condition="compatible_conflict",
                seed=1,
                trace_path=None,
            )
            second = run_episode(
                template_id=template.template_id,
                runtime_name="r2_template_guarded",
                condition="compatible_conflict",
                seed=1,
                trace_path=None,
            )
            restore_replays[template.template_id] = first == second
            environment.restore(initial)
            restore_replays[template.template_id] = bool(
                restore_replays[template.template_id]
                and environment.state_hash() == observation.state_hash
            )
        finally:
            environment.close()
    return {
        "do_nothing_rejected": do_nothing,
        "reset_and_snapshot_replay": restore_replays,
        "passed": all(do_nothing.values()) and all(restore_replays.values()),
    }


def _validity_checks(
    episodes: Sequence[dict[str, Any]],
    traces_dir: Path,
    project_root: Path,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    trace_count = len(list(traces_dir.glob("*.jsonl")))
    checks["matrix_shape"] = {
        "episodes": len(episodes),
        "trace_files": trace_count,
        "passed": len(episodes) == 72 and trace_count == 72,
    }
    checks["task_template_catalog"] = _catalog_check()
    checks["paired_initial_states"] = {
        "passed": all(
            len(
                {
                    item["initial_state_hash"]
                    for item in episodes
                    if item["template_id"] == template.template_id and item["seed"] == seed
                }
            )
            == 1
            for template in TASK_TEMPLATES
            for seed in SEEDS
        )
    }
    controls = [item for item in episodes if item["condition"] == "control"]
    checks["control_success"] = {
        "successes": sum(item["evaluation"]["safe_success"] for item in controls),
        "total": len(controls),
        "passed": len(controls) == 24
        and all(item["evaluation"]["safe_success"] for item in controls),
    }
    checks["registered_differences"] = {
        "passed": all(
            item["observed_fault_ids"]
            == _expected_fault_ids(TEMPLATES_BY_ID[item["template_id"]], item["condition"])
            for item in episodes
        )
    }
    baseline_conflicts = [
        item
        for item in episodes
        if item["runtime"] == "r2_confirmed" and item["condition"] != "control"
    ]
    checks["baseline_stops_on_state_conflict"] = {
        "episodes": len(baseline_conflicts),
        "passed": len(baseline_conflicts) == 24
        and all(
            item["execution"]["failure_code"] == "state_version_conflict"
            and not item["evaluation"]["task_success"]
            for item in baseline_conflicts
        ),
    }
    compatible = [
        item
        for item in episodes
        if item["runtime"] == "r2_template_guarded" and item["condition"] == "compatible_conflict"
    ]
    checks["all_template_compatible_recovery"] = {
        "episodes": len(compatible),
        "passed": len(compatible) == 12
        and all(
            item["execution"]["completed_plan"]
            and item["execution"]["conflict_count"] == 1
            and item["execution"]["conflict_rebase_count"] == 1
            and item["execution"]["conflict_abort_count"] == 0
            and item["evaluation"]["safe_success"]
            for item in compatible
        ),
    }
    incompatible = [
        item
        for item in episodes
        if item["runtime"] == "r2_template_guarded" and item["condition"] == "incompatible_conflict"
    ]
    checks["all_template_incompatible_fail_closed"] = {
        "episodes": len(incompatible),
        "passed": len(incompatible) == 12
        and all(
            not item["execution"]["completed_plan"]
            and item["execution"]["failure_code"] == "conflict_precondition_changed"
            and item["execution"]["conflict_rebase_count"] == 0
            and item["execution"]["conflict_abort_count"] == 1
            and item["final_state"]["conflict_target_status"] == "externally_changed"
            and item["final_state"]["request_status"] == "pending"
            for item in incompatible
        ),
    }
    workflow_episodes = [
        item
        for item in episodes
        if item["task_id"] == RECOVERY_TASK_ID and item["runtime"] == "r2_template_guarded"
    ]
    workflow_attempts = sum(
        item["execution"]["workflow_contract_attempt_count"] for item in workflow_episodes
    )
    workflow_successes = sum(
        item["execution"]["workflow_contract_success_count"] for item in workflow_episodes
    )
    workflow_failures = sum(
        item["execution"]["workflow_contract_failure_count"] for item in workflow_episodes
    )
    terminal_probes = sum(
        item["execution"]["workflow_terminal_probe_count"] for item in workflow_episodes
    )
    checks["compensation_workflow_audit"] = {
        "attempts": workflow_attempts,
        "successes": workflow_successes,
        "failures": workflow_failures,
        "terminal_probes": terminal_probes,
        "passed": len(workflow_episodes) == 9
        and workflow_attempts == 9
        and workflow_successes == 6
        and workflow_failures == 3
        and terminal_probes == 36,
    }
    checks["workflow_contract_mutations"] = _workflow_contract_check()
    checks["reset_snapshot_and_baselines"] = _baseline_and_reset_check()
    checks["historical_source_manifests"] = historical_source_manifest_check(project_root)

    forbidden_visible: dict[str, list[str]] = {}
    for template in TASK_TEMPLATES:
        environment = (
            ScenarioRetailEnvironment(template, "none")
            if template.domain == "retail"
            else ScenarioTravelEnvironment(template, "none")
        )
        try:
            visible = canonical_json(environment.reset(template.task_id, 0).as_dict()).lower()
        finally:
            environment.close()
        forbidden_visible[template.template_id] = [
            marker
            for marker in ("fault_id", "conflict_mode", "evaluator", "oracle", "minefield")
            if marker in visible
        ]
    checks["ground_truth_isolation"] = {
        "forbidden_visible_markers": forbidden_visible,
        "passed": all(not values for values in forbidden_visible.values()),
    }
    serialized = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden = [
        marker
        for marker in (
            b"@synthetic.invalid",
            b'"arguments"',
            b'"visible_task"',
            b"scenario-observer:",
            b"synthetic-key",
        )
        if marker in serialized
    ]
    checks["digest_only_traces"] = {
        "files_checked": trace_count,
        "forbidden_payload_markers": [item.decode() for item in forbidden],
        "passed": not forbidden,
    }
    return checks


def _normalize(episodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    values = []
    for episode in episodes:
        item = dict(episode)
        item.pop("trace_file", None)
        values.append(item)
    return values


def run_scenario_pack(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    primary = _run_matrix(traces_dir)
    shadow = _run_matrix(None)
    validity = _validity_checks(primary, traces_dir, project_root)
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
        raise AssertionError(f"Scenario-pack validity gates failed: {failed}")

    aggregate = _aggregate(primary)
    baseline = aggregate["by_runtime"]["r2_confirmed"]
    guarded = aggregate["by_runtime"]["r2_template_guarded"]
    assert baseline["by_condition"]["control"]["safe_successes"] == 12
    assert baseline["by_condition"]["compatible_conflict"]["safe_successes"] == 0
    assert guarded["by_condition"]["control"]["safe_successes"] == 12
    assert guarded["by_condition"]["compatible_conflict"]["safe_successes"] == 12
    assert guarded["by_condition"]["incompatible_conflict"]["safe_successes"] == 0
    assert aggregate["compatible_recovery_rate_delta"] == 1.0

    return {
        "metadata": {
            "increment_version": __version__,
            "root_project_version": "0.3.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "run_id": RUN_ID,
            "template_ids": [item.template_id for item in TASK_TEMPLATES],
            "task_ids": [item.task_id for item in TASK_TEMPLATES],
            "seeds": list(SEEDS),
            "runtimes": list(RUNTIMES),
            "conditions": list(CONDITIONS),
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "templates": [item.audit_descriptor() for item in TASK_TEMPLATES],
        "episodes": primary,
        "aggregate": aggregate,
        "validity": validity,
        "limitations": [
            "Four fixed task templates over the existing synthetic Retail and Travel worlds.",
            "One registered conflict site per template and one guarded rebase per action.",
            "One fixed four-step Travel compensation workflow; no dynamic planner.",
            "Exact public-read guards only; no automatic semantic merge.",
            "Fixed oracle plans; no model, symbolic user, account, credential, or network.",
        ],
    }
