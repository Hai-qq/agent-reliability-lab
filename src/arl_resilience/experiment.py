"""Cross-domain guarded conflict and compensation experiment for ARL v0.9."""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from arl.core.types import Observation, StepResult, ToolAction, canonical_json, digest_value
from arl.runtime.journal import EventJournal
from arl_resilience import __version__
from arl_resilience.contracts import CompensationContract, GuardedAction, StateGuard
from arl_resilience.env import (
    ENV_VERSION,
    RETAIL_METADATA_CONFLICT_FAULT_ID,
    RETAIL_ORDER_CONFLICT_FAULT_ID,
    TRAVEL_METADATA_CONFLICT_FAULT_ID,
    TRAVEL_RESERVATION_CONFLICT_FAULT_ID,
    ConflictMode,
    ResilientRetailEnvironment,
    ResilientTravelEnvironment,
)
from arl_resilience.evaluator import add_resilience_evidence
from arl_resilience.runtime import (
    RetailResilienceRuntime,
    TravelResiliencePlan,
    TravelResilienceRuntime,
)
from arl_retail.env import PURCHASE_TASK_ID
from arl_retail.env import SCHEMA_VERSION as RETAIL_SCHEMA_VERSION
from arl_retail.evaluator import evaluate_retail
from arl_retail.experiment import task_actions as retail_task_actions
from arl_retail.runtime import RetailRuntime
from arl_travel.env import RECOVERY_TASK_ID
from arl_travel.env import SCHEMA_VERSION as TRAVEL_SCHEMA_VERSION
from arl_travel.evaluator import evaluate_travel
from arl_travel.experiment import task_plan as travel_task_plan
from arl_travel.runtime import TravelRuntime

SEEDS = (0, 1, 2)
DOMAINS = ("retail", "travel")
RUNTIMES = ("r2_confirmed", "r2_contract_guarded")
CONDITIONS = ("control", "compatible_conflict", "incompatible_conflict")
RUN_ID = "cross-domain-resilience-v0.9.0"

_HISTORICAL_SUMMARIES = {
    "v0.1": "artifacts/workspace_paired/summary.json",
    "v0.2": "artifacts/workspace_r2_postcommit/summary.json",
    "v0.3": "artifacts/workspace_multitask_v03/summary.json",
    "v0.4": "artifacts/workspace_validity_v04/summary.json",
    "v0.5": "artifacts/retail_minimal_v05/summary.json",
    "v0.6": "artifacts/travel_minimal_v06/summary.json",
    "v0.7": "artifacts/schema_adapter_v07/summary.json",
    "v0.8": "artifacts/workspace_conflict_v08/summary.json",
}


def retail_resilience_plan(observation: Observation) -> list[GuardedAction]:
    actions = retail_task_actions(observation, "r2_confirmed")
    task = observation.visible_task
    guard = StateGuard(
        tool_name="orders.get_order",
        schema_version=RETAIL_SCHEMA_VERSION,
        arguments={"order_id": task["order_id"]},
        value_path=("order", "status"),
        expected_value="placed",
    )
    return [
        GuardedAction(
            action=action,
            guards=(guard,) if action.tool_name == "retail.resolve_purchase_request" else (),
        )
        for action in actions
    ]


def travel_resilience_plan(observation: Observation) -> TravelResiliencePlan:
    base = travel_task_plan(observation, "r2_confirmed")
    task = observation.visible_task
    reservation_id = task["preferred"]["hotel_reservation_id"]
    precondition = StateGuard(
        tool_name="hotels.get_reservation",
        schema_version=TRAVEL_SCHEMA_VERSION,
        arguments={"reservation_id": reservation_id},
        value_path=("reservation", "status"),
        expected_value="active",
    )
    postcondition = StateGuard(
        tool_name="hotels.get_reservation",
        schema_version=TRAVEL_SCHEMA_VERSION,
        arguments={"reservation_id": reservation_id},
        value_path=("reservation", "status"),
        expected_value="cancelled",
    )
    cancel_action = base.recovery_actions[0]
    contract = CompensationContract(
        contract_id="travel.refundable_hotel.cancel.v1",
        trigger_tool=base.recovery_trigger_tool or "",
        trigger_error=base.recovery_trigger_error or "",
        action=cancel_action,
        preconditions=(precondition,),
        postconditions=(postcondition,),
    )
    return TravelResiliencePlan(
        primary_actions=tuple(GuardedAction(action=action) for action in base.primary_actions),
        recovery_actions=(
            contract,
            *(GuardedAction(action=action) for action in base.recovery_actions[1:]),
        ),
        recovery_trigger_tool=base.recovery_trigger_tool or "",
        recovery_trigger_error=base.recovery_trigger_error or "",
    )


def _mode(condition: str) -> ConflictMode:
    modes: dict[str, ConflictMode] = {
        "control": "none",
        "compatible_conflict": "compatible_conflict",
        "incompatible_conflict": "incompatible_conflict",
    }
    return modes[condition]


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
        }
    )
    return value


def _final_state(domain: str, world: dict[str, Any]) -> dict[str, Any]:
    if domain == "retail":
        return {
            "order_status": world["orders"][0]["status"] if world["orders"] else None,
            "request_status": world["purchase_requests"][0]["status"],
            "order_count": len(world["orders"]),
            "idempotency_record_count": len(world["idempotency_records"]),
        }
    preferred_id = world["task"]["preferred_hotel_reservation_id"]
    preferred = next(
        (item for item in world["hotel_reservations"] if item["reservation_id"] == preferred_id),
        None,
    )
    return {
        "preferred_hotel_status": preferred["status"] if preferred else None,
        "request_status": world["booking_requests"][0]["status"],
        "active_hotel_count": sum(
            item["status"] == "active" for item in world["hotel_reservations"]
        ),
        "flight_booking_count": len(world["flight_bookings"]),
        "idempotency_record_count": len(world["idempotency_records"]),
    }


def run_episode(
    *,
    domain: str,
    runtime_name: str,
    condition: str,
    seed: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    task_id = PURCHASE_TASK_ID if domain == "retail" else RECOVERY_TASK_ID
    episode_id = f"resilience-{domain}-seed-{seed}-{runtime_name}-{condition}"
    environment: ResilientRetailEnvironment | ResilientTravelEnvironment
    environment = (
        ResilientRetailEnvironment(_mode(condition))
        if domain == "retail"
        else ResilientTravelEnvironment(_mode(condition))
    )
    try:
        observation = environment.reset(task_id, seed)
        initial_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=RUN_ID,
            episode_id=episode_id,
            task_id=task_id,
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
                    "domain": domain,
                    "runtime": runtime_name,
                    "condition": condition,
                    "observation": observation.as_dict(),
                }
            ),
        )
        if domain == "retail":
            plan = retail_resilience_plan(observation)
            if runtime_name == "r2_contract_guarded":
                execution = RetailResilienceRuntime().execute(environment, plan, journal)
                execution_value = execution.as_dict()
            else:
                execution = RetailRuntime("r2_confirmed").execute(
                    environment,
                    [item.action for item in plan],
                    journal,
                )
                execution_value = _normalized_baseline_report(execution)
            evaluation = evaluate_retail(
                initial_snapshot,
                environment.snapshot(),
                journal.as_dicts(),
            )
        else:
            plan = travel_resilience_plan(observation)
            if runtime_name == "r2_contract_guarded":
                execution = TravelResilienceRuntime().execute(environment, plan, journal)
                execution_value = execution.as_dict()
            else:
                execution = TravelRuntime("r2_confirmed").execute(
                    environment,
                    travel_task_plan(observation, "r2_confirmed"),
                    journal,
                )
                execution_value = _normalized_baseline_report(execution)
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
        trace_events = journal.as_dicts()
        world = environment.export_world()
        return {
            "episode_id": episode_id,
            "domain": domain,
            "task_id": task_id,
            "seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "conflict_mode": _mode(condition),
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "execution": execution_value,
            "evaluation": evaluation.as_dict(),
            "observed_fault_ids": sorted(
                {event["fault_id"] for event in trace_events if event["fault_id"]}
            ),
            "final_state": _final_state(domain, world),
            "trace_file": trace_path.name if trace_path is not None else None,
            "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
            "trace_event_count": len(journal.events),
        }
    finally:
        environment.close()


def _run_matrix(traces_dir: Path | None) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for domain in DOMAINS:
        for runtime_name in RUNTIMES:
            for condition in CONDITIONS:
                for seed in SEEDS:
                    episode_id = f"resilience-{domain}-seed-{seed}-{runtime_name}-{condition}"
                    trace_path = traces_dir / f"{episode_id}.jsonl" if traces_dir else None
                    episodes.append(
                        run_episode(
                            domain=domain,
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
        "conflict_probe_count": sum(item["execution"]["conflict_probe_count"] for item in episodes),
        "conflict_rebase_count": sum(
            item["execution"]["conflict_rebase_count"] for item in episodes
        ),
        "conflict_abort_count": sum(item["execution"]["conflict_abort_count"] for item in episodes),
        "compensation_contract_attempt_count": sum(
            item["execution"]["compensation_contract_attempt_count"] for item in episodes
        ),
        "compensation_contract_success_count": sum(
            item["execution"]["compensation_contract_success_count"] for item in episodes
        ),
        "compensation_contract_failure_count": sum(
            item["execution"]["compensation_contract_failure_count"] for item in episodes
        ),
    }


def _aggregate(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_runtime = {
        runtime: _selection_aggregate([item for item in episodes if item["runtime"] == runtime])
        for runtime in RUNTIMES
    }
    by_domain = {
        domain: {
            runtime: _selection_aggregate(
                [
                    item
                    for item in episodes
                    if item["domain"] == domain and item["runtime"] == runtime
                ]
            )
            for runtime in RUNTIMES
        }
        for domain in DOMAINS
    }
    return {
        "episode_count": len(episodes),
        "domain_count": len(DOMAINS),
        "task_count": len(DOMAINS),
        "seed_count": len(SEEDS),
        "runtime_count": len(RUNTIMES),
        "condition_count": len(CONDITIONS),
        "by_runtime": by_runtime,
        "by_domain": by_domain,
        "compatible_recovery_rate_delta": (
            by_runtime["r2_contract_guarded"]["compatible_conflict_recovery_rate"]
            - by_runtime["r2_confirmed"]["compatible_conflict_recovery_rate"]
        ),
    }


def historical_source_manifest_check(project_root: Path) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for version, relative_summary in _HISTORICAL_SUMMARIES.items():
        summary = json.loads((project_root / relative_summary).read_text(encoding="utf-8"))
        manifest = summary["metadata"]["source_manifest"]
        expected_files = manifest["files"]
        actual_files = {
            relative_path: hashlib.sha256((project_root / relative_path).read_bytes()).hexdigest()
            for relative_path in sorted(expected_files)
        }
        actual_sha = hashlib.sha256(canonical_json(actual_files).encode("utf-8")).hexdigest()
        details[version] = {
            "summary": relative_summary,
            "expected_sha256": manifest["sha256"],
            "actual_sha256": actual_sha,
            "file_count": len(actual_files),
            "matched": actual_files == expected_files and actual_sha == manifest["sha256"],
        }
    return {"increments": details, "passed": all(item["matched"] for item in details.values())}


def _guard_contract_checks() -> dict[str, Any]:
    guard = StateGuard(
        tool_name="records.get",
        schema_version="1.0",
        arguments={"record_id": "synthetic"},
        value_path=("record", "status"),
        expected_value="ready",
    )

    def result(value: dict[str, Any]) -> StepResult:
        return StepResult(
            status="ok",
            value=value,
            error_code=None,
            state_version=1,
            retry_after_ms=None,
            state_hash_before="before",
            state_hash_after="after",
            timestamp_logical=1,
        )

    cases = {
        "exact_value_matches": guard.matches(result({"record": {"status": "ready"}})),
        "changed_value_rejected": not guard.matches(result({"record": {"status": "changed"}})),
        "missing_path_rejected": not guard.matches(result({"record": {}})),
        "wrong_shape_rejected": not guard.matches(result({"record": []})),
    }
    return {"cases": cases, "passed": all(cases.values())}


def _compensation_contract_checks() -> dict[str, Any]:
    action = ToolAction(
        tool_name="hotels.cancel",
        schema_version="1.0",
        arguments={"reservation_id": "synthetic"},
        idempotency_key="synthetic-key",
        expected_state_version=1,
    )
    guard = StateGuard(
        tool_name="hotels.get_reservation",
        schema_version="1.0",
        arguments={"reservation_id": "synthetic"},
        value_path=("reservation", "status"),
        expected_value="active",
    )
    post = StateGuard(
        tool_name=guard.tool_name,
        schema_version=guard.schema_version,
        arguments=guard.arguments,
        value_path=guard.value_path,
        expected_value="cancelled",
    )
    contract = CompensationContract(
        contract_id="synthetic.contract",
        trigger_tool="flights.book",
        trigger_error="flight_unavailable",
        action=action,
        preconditions=(guard,),
        postconditions=(post,),
    )
    rejected = 0
    invalid_values = (
        {"max_attempts": 2},
        {"preconditions": ()},
        {"postconditions": ()},
        {"action": replace_tool_action(action, idempotency_key=None)},
    )
    for changes in invalid_values:
        values = {
            "contract_id": contract.contract_id,
            "trigger_tool": contract.trigger_tool,
            "trigger_error": contract.trigger_error,
            "action": contract.action,
            "preconditions": contract.preconditions,
            "postconditions": contract.postconditions,
            "max_attempts": contract.max_attempts,
            **changes,
        }
        try:
            CompensationContract(**values)
        except ValueError:
            rejected += 1
    cases = {
        "trigger_matches": contract.matches_trigger("flights.book", "flight_unavailable"),
        "wrong_trigger_rejected": not contract.matches_trigger(
            "flights.book", "payment_not_authorized"
        ),
        "invalid_contracts_rejected": rejected == len(invalid_values),
        "audit_descriptor_is_digest_only": "synthetic-key"
        not in canonical_json(contract.audit_descriptor()),
    }
    return {"cases": cases, "passed": all(cases.values())}


def replace_tool_action(action: ToolAction, **changes: Any) -> ToolAction:
    values = action.as_dict()
    values.update(changes)
    return ToolAction(**values)


def _reset_snapshot_and_baseline_checks() -> dict[str, Any]:
    reset_hashes: dict[str, list[str]] = {}
    for domain in DOMAINS:
        for mode in ("none", "compatible_conflict", "incompatible_conflict"):
            environment = (
                ResilientRetailEnvironment(mode)  # type: ignore[arg-type]
                if domain == "retail"
                else ResilientTravelEnvironment(mode)  # type: ignore[arg-type]
            )
            task_id = PURCHASE_TASK_ID if domain == "retail" else RECOVERY_TASK_ID
            try:
                reset_hashes[f"{domain}:{mode}"] = [
                    environment.reset(task_id, 0).state_hash for _ in range(20)
                ]
            finally:
                environment.close()
    reset_passed = all(len(set(hashes)) == 1 for hashes in reset_hashes.values())

    reruns: dict[str, bool] = {}
    baseline_rejections: dict[str, bool] = {}
    for domain in DOMAINS:
        environment = (
            ResilientRetailEnvironment("compatible_conflict")
            if domain == "retail"
            else ResilientTravelEnvironment("compatible_conflict")
        )
        task_id = PURCHASE_TASK_ID if domain == "retail" else RECOVERY_TASK_ID
        try:
            observation = environment.reset(task_id, 1)
            initial = environment.snapshot()
            journal = EventJournal(
                run_id="v09-validity",
                episode_id=f"{domain}-first",
                task_id=task_id,
                seed=1,
            )
            if domain == "retail":
                first = RetailResilienceRuntime().execute(
                    environment,
                    retail_resilience_plan(observation),
                    journal,
                )
                do_nothing = evaluate_retail(initial, initial, [])
            else:
                first = TravelResilienceRuntime().execute(
                    environment,
                    travel_resilience_plan(observation),
                    journal,
                )
                do_nothing = evaluate_travel(initial, initial, [])
            first_hash = environment.state_hash()
            environment.restore(initial)
            second_observation = observation
            second_journal = EventJournal(
                run_id="v09-validity",
                episode_id=f"{domain}-first",
                task_id=task_id,
                seed=1,
            )
            if domain == "retail":
                second = RetailResilienceRuntime().execute(
                    environment,
                    retail_resilience_plan(second_observation),
                    second_journal,
                )
            else:
                second = TravelResilienceRuntime().execute(
                    environment,
                    travel_resilience_plan(second_observation),
                    second_journal,
                )
            reruns[domain] = bool(
                first.completed_plan
                and second.completed_plan
                and first_hash == environment.state_hash()
                and journal.jsonl_bytes() == second_journal.jsonl_bytes()
            )
            baseline_rejections[domain] = not do_nothing.task_success
        finally:
            environment.close()
    return {
        "reset_iterations_per_mode": 20,
        "reset_passed": reset_passed,
        "snapshot_restore_and_reinjection": reruns,
        "do_nothing_rejected": baseline_rejections,
        "passed": reset_passed and all(reruns.values()) and all(baseline_rejections.values()),
    }


def _expected_fault_ids(domain: str, condition: str) -> list[str]:
    values: list[str] = []
    if domain == "travel":
        values.append("fault.travel.preferred_flight.unavailable")
    if condition == "compatible_conflict":
        values.append(
            RETAIL_METADATA_CONFLICT_FAULT_ID
            if domain == "retail"
            else TRAVEL_METADATA_CONFLICT_FAULT_ID
        )
    elif condition == "incompatible_conflict":
        values.append(
            RETAIL_ORDER_CONFLICT_FAULT_ID
            if domain == "retail"
            else TRAVEL_RESERVATION_CONFLICT_FAULT_ID
        )
    return sorted(values)


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
        "passed": len(episodes) == 36 and trace_count == 36,
    }
    checks["paired_initial_states"] = {
        "unique_hashes_by_domain_seed": {
            f"{domain}:{seed}": sorted(
                {
                    item["initial_state_hash"]
                    for item in episodes
                    if item["domain"] == domain and item["seed"] == seed
                }
            )
            for domain in DOMAINS
            for seed in SEEDS
        },
        "passed": all(
            len(
                {
                    item["initial_state_hash"]
                    for item in episodes
                    if item["domain"] == domain and item["seed"] == seed
                }
            )
            == 1
            for domain in DOMAINS
            for seed in SEEDS
        ),
    }
    controls = [item for item in episodes if item["condition"] == "control"]
    checks["control_success"] = {
        "successes": sum(item["evaluation"]["safe_success"] for item in controls),
        "total": len(controls),
        "passed": len(controls) == 12
        and all(item["evaluation"]["safe_success"] for item in controls),
    }
    checks["registered_differences"] = {
        "fault_ids": {item["episode_id"]: item["observed_fault_ids"] for item in episodes},
        "passed": all(
            item["observed_fault_ids"] == _expected_fault_ids(item["domain"], item["condition"])
            for item in episodes
        ),
    }
    baseline_conflicts = [
        item
        for item in episodes
        if item["runtime"] == "r2_confirmed" and item["condition"] != "control"
    ]
    checks["baseline_stops_on_state_conflict"] = {
        "episodes": [item["episode_id"] for item in baseline_conflicts],
        "passed": len(baseline_conflicts) == 12
        and all(
            item["execution"]["failure_code"] == "state_version_conflict"
            and not item["evaluation"]["task_success"]
            for item in baseline_conflicts
        ),
    }
    aware_compatible = [
        item
        for item in episodes
        if item["runtime"] == "r2_contract_guarded" and item["condition"] == "compatible_conflict"
    ]
    checks["cross_domain_compatible_recovery"] = {
        "episodes": [item["episode_id"] for item in aware_compatible],
        "passed": len(aware_compatible) == 6
        and all(
            item["execution"]["completed_plan"]
            and item["execution"]["conflict_count"] == 1
            and item["execution"]["conflict_probe_count"] == 1
            and item["execution"]["conflict_rebase_count"] == 1
            and item["execution"]["conflict_abort_count"] == 0
            and item["evaluation"]["safe_success"]
            for item in aware_compatible
        ),
    }
    aware_incompatible = [
        item
        for item in episodes
        if item["runtime"] == "r2_contract_guarded" and item["condition"] == "incompatible_conflict"
    ]
    checks["cross_domain_incompatible_fail_closed"] = {
        "episodes": [item["episode_id"] for item in aware_incompatible],
        "passed": len(aware_incompatible) == 6
        and all(
            not item["execution"]["completed_plan"]
            and item["execution"]["failure_code"] == "conflict_precondition_changed"
            and item["execution"]["conflict_probe_count"] == 1
            and item["execution"]["conflict_rebase_count"] == 0
            and item["execution"]["conflict_abort_count"] == 1
            and item["final_state"][
                "order_status" if item["domain"] == "retail" else "preferred_hotel_status"
            ]
            == "externally_changed"
            and item["final_state"]["request_status"] == "pending"
            for item in aware_incompatible
        ),
    }
    aware_travel = [
        item
        for item in episodes
        if item["domain"] == "travel" and item["runtime"] == "r2_contract_guarded"
    ]
    checks["compensation_contract_audit"] = {
        "attempts": sum(
            item["execution"]["compensation_contract_attempt_count"] for item in aware_travel
        ),
        "successes": sum(
            item["execution"]["compensation_contract_success_count"] for item in aware_travel
        ),
        "failures": sum(
            item["execution"]["compensation_contract_failure_count"] for item in aware_travel
        ),
        "passed": len(aware_travel) == 9
        and sum(item["execution"]["compensation_contract_attempt_count"] for item in aware_travel)
        == 9
        and sum(item["execution"]["compensation_contract_success_count"] for item in aware_travel)
        == 6
        and sum(item["execution"]["compensation_contract_failure_count"] for item in aware_travel)
        == 3,
    }
    checks["guard_contract_mutations"] = _guard_contract_checks()
    checks["compensation_contract_mutations"] = _compensation_contract_checks()
    checks["reset_snapshot_and_baselines"] = _reset_snapshot_and_baseline_checks()
    checks["historical_source_manifests"] = historical_source_manifest_check(project_root)

    forbidden_visible: dict[str, list[str]] = {}
    for domain in DOMAINS:
        environment = (
            ResilientRetailEnvironment() if domain == "retail" else ResilientTravelEnvironment()
        )
        task_id = PURCHASE_TASK_ID if domain == "retail" else RECOVERY_TASK_ID
        try:
            visible = canonical_json(environment.reset(task_id, 0).as_dict()).lower()
        finally:
            environment.close()
        forbidden_visible[domain] = [
            marker
            for marker in ("fault_id", "conflict_mode", "evaluator", "oracle", "minefield")
            if marker in visible
        ]
    checks["ground_truth_isolation"] = {
        "forbidden_visible_markers": forbidden_visible,
        "passed": all(not values for values in forbidden_visible.values()),
    }

    serialized = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden_trace_markers = [
        marker
        for marker in (
            b"@synthetic.invalid",
            b'"arguments"',
            b'"visible_task"',
            b"external-observer:",
            b"synthetic-key",
        )
        if marker in serialized
    ]
    checks["digest_only_traces"] = {
        "forbidden_payload_markers": [marker.decode() for marker in forbidden_trace_markers],
        "passed": not forbidden_trace_markers,
    }
    return checks


def _normalize_for_comparison(episodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for episode in episodes:
        item = dict(episode)
        item.pop("trace_file", None)
        normalized.append(item)
    return normalized


def run_resilience_experiment(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    primary = _run_matrix(traces_dir)
    shadow = _run_matrix(None)
    repeat_deterministic = _normalize_for_comparison(primary) == _normalize_for_comparison(shadow)
    validity = _validity_checks(primary, traces_dir, project_root)
    validity["repeat_results_deterministic"] = {"passed": repeat_deterministic}
    validity["all_selected_checks_passed"] = all(
        value["passed"] for key, value in validity.items() if key != "all_selected_checks_passed"
    )
    assert validity["all_selected_checks_passed"]

    aggregate = _aggregate(primary)
    baseline = aggregate["by_runtime"]["r2_confirmed"]
    guarded = aggregate["by_runtime"]["r2_contract_guarded"]
    assert baseline["by_condition"]["control"]["task_successes"] == 6
    assert baseline["by_condition"]["compatible_conflict"]["task_successes"] == 0
    assert guarded["by_condition"]["control"]["task_successes"] == 6
    assert guarded["by_condition"]["compatible_conflict"]["task_successes"] == 6
    assert guarded["by_condition"]["incompatible_conflict"]["task_successes"] == 0
    assert guarded["incompatible_conflict_classified_abort_rate"] == 1.0
    assert aggregate["compatible_recovery_rate_delta"] == 1.0

    return {
        "metadata": {
            "increment_version": __version__,
            "root_project_version": "0.3.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "environment_version": ENV_VERSION,
            "domains": list(DOMAINS),
            "task_ids": [PURCHASE_TASK_ID, RECOVERY_TASK_ID],
            "seeds": list(SEEDS),
            "runtimes": list(RUNTIMES),
            "conditions": list(CONDITIONS),
            "registered_differences": {
                "retail_compatible": "atomic unrelated metadata change before request resolution",
                "retail_incompatible": "atomic target order-status change before resolution",
                "travel_compatible": "atomic unrelated metadata change before compensation",
                "travel_incompatible": (
                    "atomic target reservation-status change before compensation"
                ),
            },
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "episodes": primary,
        "aggregate": aggregate,
        "validity": validity,
        "limitations": [
            "Two existing synthetic tasks, one Retail and one Travel, with three seeds.",
            "One registered conflict site per domain and one guarded rebase maximum per action.",
            "One compensation action type with exact public-read preconditions and postconditions.",
            "No automatic semantic merge, dynamic compensation planner, model, or learned policy.",
            "No scheduler, symbolic user, trace UI, real account, credential, or network access.",
        ],
    }
