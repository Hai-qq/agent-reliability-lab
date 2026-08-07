"""Paired schema-drift experiment and validity gates for v0.7."""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json, digest_value
from arl.runtime.journal import EventJournal
from arl_schema import __version__
from arl_schema.adapter import SchemaAdapter, SchemaAdapterError
from arl_schema.env import (
    ENV_VERSION,
    FLIGHT_ACTION_FAULT_ID,
    HOTEL_RESULT_FAULT_ID,
    SchemaDriftEnvironment,
)
from arl_schema.runtime import SchemaRuntime
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID, TASK_IDS
from arl_travel.evaluator import evaluate_travel
from arl_travel.experiment import task_plan

SEEDS = (0, 1, 2)
RUNTIMES = ("r1_guarded", "r2_schema_adapted")
CONDITIONS = ("clean", "fault")
RUN_ID = "schema-adapter-v0.7.0"

_HISTORICAL_SUMMARIES = {
    "v0.1": "artifacts/workspace_paired/summary.json",
    "v0.2": "artifacts/workspace_r2_postcommit/summary.json",
    "v0.3": "artifacts/workspace_multitask_v03/summary.json",
    "v0.4": "artifacts/workspace_validity_v04/summary.json",
    "v0.5": "artifacts/retail_minimal_v05/summary.json",
    "v0.6": "artifacts/travel_minimal_v06/summary.json",
}


def _task_slug(task_id: str) -> str:
    return "book" if task_id == BOOK_TASK_ID else "recovery"


def _drift_mode(task_id: str, condition: str) -> str:
    if condition == "clean":
        return "none"
    if task_id == BOOK_TASK_ID:
        return "flight_action_schema_v2"
    return "hotel_result_schema_v2"


def _plan_runtime_name(runtime_name: str) -> str:
    return "r2_confirmed" if runtime_name == "r2_schema_adapted" else "r1_guarded"


def run_episode(
    *,
    task_id: str,
    runtime_name: str,
    condition: str,
    seed: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    episode_id = f"schema-{_task_slug(task_id)}-seed-{seed}-{runtime_name}-{condition}"
    drift_mode = _drift_mode(task_id, condition)
    environment = SchemaDriftEnvironment(drift_mode=drift_mode)
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
                    "runtime": runtime_name,
                    "condition": condition,
                    "observation": observation.as_dict(),
                }
            ),
        )
        plan = task_plan(observation, _plan_runtime_name(runtime_name))
        execution = SchemaRuntime(runtime_name).execute(environment, plan, journal)
        evaluation = evaluate_travel(
            initial_snapshot,
            environment.snapshot(),
            journal.as_dicts(),
        )
        final_hash = environment.state_hash()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="evaluator",
            event_type="evaluation_completed",
            state_hash_before=final_hash,
            state_hash_after=final_hash,
            output_digest=digest_value(evaluation.as_dict()),
        )
        world = environment.export_world()
        fault_ids = sorted(
            {event.fault_id for event in journal.events if event.fault_id is not None}
        )
        return {
            "episode_id": episode_id,
            "task_id": task_id,
            "seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "drift_mode": drift_mode,
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "execution": execution.as_dict(),
            "evaluation": evaluation.as_dict(),
            "schema_adaptation_count": execution.schema_adaptation_count,
            "output_normalization_count": execution.output_normalization_count,
            "observed_fault_ids": fault_ids,
            "final_state_counts": {
                "flight_bookings": len(world["flight_bookings"]),
                "hotel_reservations": len(world["hotel_reservations"]),
                "idempotency_records": len(world["idempotency_records"]),
            },
            "trace_file": trace_path.name if trace_path is not None else None,
            "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
            "trace_event_count": len(journal.events),
        }
    finally:
        environment.close()


def _run_matrix(traces_dir: Path | None) -> list[dict[str, Any]]:
    episodes: list[dict[str, Any]] = []
    for task_id in TASK_IDS:
        for runtime_name in RUNTIMES:
            for condition in CONDITIONS:
                for seed in SEEDS:
                    episode_id = (
                        f"schema-{_task_slug(task_id)}-seed-{seed}-{runtime_name}-{condition}"
                    )
                    trace_path = traces_dir / f"{episode_id}.jsonl" if traces_dir else None
                    episodes.append(
                        run_episode(
                            task_id=task_id,
                            runtime_name=runtime_name,
                            condition=condition,
                            seed=seed,
                            trace_path=trace_path,
                        )
                    )
    return episodes


def _runtime_aggregate(episodes: Sequence[dict[str, Any]], runtime_name: str) -> dict[str, Any]:
    selected = [episode for episode in episodes if episode["runtime"] == runtime_name]
    clean = [episode for episode in selected if episode["condition"] == "clean"]
    fault = [episode for episode in selected if episode["condition"] == "fault"]
    clean_success_pairs = {
        (episode["task_id"], episode["seed"])
        for episode in clean
        if episode["evaluation"]["task_success"]
    }
    recovered_fault_pairs = {
        (episode["task_id"], episode["seed"])
        for episode in fault
        if (episode["task_id"], episode["seed"]) in clean_success_pairs
        and episode["evaluation"]["task_success"]
    }
    return {
        "episode_count": len(selected),
        "clean_successes": sum(episode["evaluation"]["task_success"] for episode in clean),
        "clean_total": len(clean),
        "fault_successes": sum(episode["evaluation"]["task_success"] for episode in fault),
        "fault_total": len(fault),
        "safe_successes": sum(episode["evaluation"]["safe_success"] for episode in selected),
        "safe_total": len(selected),
        "schema_adaptation_count": sum(episode["schema_adaptation_count"] for episode in selected),
        "output_normalization_count": sum(
            episode["output_normalization_count"] for episode in selected
        ),
        "recovery_rate": (
            len(recovered_fault_pairs) / len(clean_success_pairs) if clean_success_pairs else None
        ),
        "recovered_fault_pairs": [
            {"task_id": task_id, "seed": seed} for task_id, seed in sorted(recovered_fault_pairs)
        ],
    }


def _aggregate(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_runtime = {
        runtime_name: _runtime_aggregate(episodes, runtime_name) for runtime_name in RUNTIMES
    }
    by_task: dict[str, Any] = {}
    for task_id in TASK_IDS:
        by_task[task_id] = {}
        for runtime_name in RUNTIMES:
            selected = [
                episode
                for episode in episodes
                if episode["task_id"] == task_id and episode["runtime"] == runtime_name
            ]
            by_task[task_id][runtime_name] = {
                condition: {
                    "successes": sum(
                        episode["evaluation"]["task_success"]
                        for episode in selected
                        if episode["condition"] == condition
                    ),
                    "total": sum(episode["condition"] == condition for episode in selected),
                }
                for condition in CONDITIONS
            }
    return {
        "episode_count": len(episodes),
        "task_count": len(TASK_IDS),
        "seed_count": len(SEEDS),
        "runtime_count": len(RUNTIMES),
        "condition_count": len(CONDITIONS),
        "by_runtime": by_runtime,
        "by_task": by_task,
        "paired_recovery_rate_delta_r2_minus_r1": (
            by_runtime["r2_schema_adapted"]["recovery_rate"]
            - by_runtime["r1_guarded"]["recovery_rate"]
        ),
    }


def _raises_adapter_error(call: Callable[[], object]) -> bool:
    try:
        call()
    except SchemaAdapterError:
        return True
    return False


def _adapter_mutation_checks() -> dict[str, Any]:
    environment = SchemaDriftEnvironment("flight_action_schema_v2")
    try:
        observation = environment.reset(BOOK_TASK_ID, 0)
        canonical = task_plan(observation, "r2_confirmed").primary_actions[0]
        action_descriptor = environment.describe_tool("flights.book")
    finally:
        environment.close()

    missing = dict(canonical.arguments)
    missing.pop("payment_id")
    extra = {**canonical.arguments, "payment_ref": canonical.arguments["payment_id"]}
    wrong_type = {**canonical.arguments, "confirmed_nonrefundable": 0}
    unknown_action_descriptor = json.loads(canonical_json(action_descriptor))
    unknown_action_descriptor["action"]["schema_version"] = "9.9"
    mismatched_action_descriptor = json.loads(canonical_json(action_descriptor))
    mismatched_action_descriptor["action"]["required_fields"] = ["reservation_ref"]

    hotel_environment = SchemaDriftEnvironment("hotel_result_schema_v2")
    try:
        hotel_observation = hotel_environment.reset(RECOVERY_TASK_ID, 0)
        hotel_action = task_plan(hotel_observation, "r2_confirmed").primary_actions[0]
        hotel_result = hotel_environment.step(hotel_action)
        result_descriptor = hotel_environment.describe_tool("hotels.book")
    finally:
        hotel_environment.close()
    assert hotel_result.ok and hotel_result.value is not None
    missing_result = dict(hotel_result.value)
    missing_result.pop("amount")
    wrong_result = json.loads(canonical_json(hotel_result.value))
    wrong_result["amount"]["minor_units"] = "15000"
    unknown_result_descriptor = json.loads(canonical_json(result_descriptor))
    unknown_result_descriptor["result"]["schema_version"] = "9.9"
    permissive_result_descriptor = json.loads(canonical_json(result_descriptor))
    permissive_result_descriptor["result"]["additional_fields"] = True

    checks = {
        "missing_action_field": _raises_adapter_error(
            lambda: SchemaAdapter.adapt_action(
                replace(canonical, arguments=missing), action_descriptor
            )
        ),
        "extra_action_field": _raises_adapter_error(
            lambda: SchemaAdapter.adapt_action(
                replace(canonical, arguments=extra), action_descriptor
            )
        ),
        "wrong_action_type": _raises_adapter_error(
            lambda: SchemaAdapter.adapt_action(
                replace(canonical, arguments=wrong_type), action_descriptor
            )
        ),
        "unknown_action_version": _raises_adapter_error(
            lambda: SchemaAdapter.adapt_action(canonical, unknown_action_descriptor)
        ),
        "mismatched_action_descriptor": _raises_adapter_error(
            lambda: SchemaAdapter.adapt_action(canonical, mismatched_action_descriptor)
        ),
        "missing_result_field": _raises_adapter_error(
            lambda: SchemaAdapter.normalize_result(
                tool_name="hotels.book",
                result=replace(hotel_result, value=missing_result),
                descriptor=result_descriptor,
            )
        ),
        "wrong_result_type": _raises_adapter_error(
            lambda: SchemaAdapter.normalize_result(
                tool_name="hotels.book",
                result=replace(hotel_result, value=wrong_result),
                descriptor=result_descriptor,
            )
        ),
        "unknown_result_version": _raises_adapter_error(
            lambda: SchemaAdapter.normalize_result(
                tool_name="hotels.book",
                result=hotel_result,
                descriptor=unknown_result_descriptor,
            )
        ),
        "permissive_result_descriptor": _raises_adapter_error(
            lambda: SchemaAdapter.normalize_result(
                tool_name="hotels.book",
                result=hotel_result,
                descriptor=permissive_result_descriptor,
            )
        ),
    }
    return {"cases": checks, "passed": all(checks.values())}


def _descriptor_checks() -> dict[str, Any]:
    forbidden = ("fault", "target", "seed", "oracle", "evaluator", "idempotency")
    descriptors: list[dict[str, Any]] = []
    deterministic = True
    for mode in ("none", "flight_action_schema_v2", "hotel_result_schema_v2"):
        environment = SchemaDriftEnvironment(mode)
        try:
            environment.reset(BOOK_TASK_ID, 0)
            for tool_name in (
                "flights.book",
                "hotels.book",
                "travel.resolve_booking_request",
            ):
                first = environment.describe_tool(tool_name)
                second = environment.describe_tool(tool_name)
                deterministic = deterministic and first == second and first is not second
                descriptors.append(first)
        finally:
            environment.close()
    serialized = canonical_json(descriptors).lower()
    present = [marker for marker in forbidden if marker in serialized]
    versions = sorted(
        {
            section["schema_version"]
            for descriptor in descriptors
            for section in (descriptor["action"], descriptor["result"])
        }
    )
    return {
        "descriptor_count": len(descriptors),
        "versions": versions,
        "forbidden_markers": present,
        "passed": deterministic and not present and versions == ["1.0", "2.0"],
    }


def _reset_and_snapshot_checks() -> dict[str, Any]:
    reference: dict[tuple[str, int], str] = {}
    for task_id in TASK_IDS:
        for seed in SEEDS:
            environment = SchemaDriftEnvironment()
            try:
                reference[(task_id, seed)] = environment.reset(task_id, seed).state_hash
            finally:
                environment.close()

    environment = SchemaDriftEnvironment("flight_action_schema_v2")
    reset_passed = True
    try:
        for index in range(20):
            task_id = TASK_IDS[index % len(TASK_IDS)]
            seed = SEEDS[index % len(SEEDS)]
            observation = environment.reset(task_id, seed)
            reset_passed = reset_passed and bool(
                observation.state_hash == reference[(task_id, seed)]
                and observation.state_version == 0
                and observation.timestamp_logical == 0
                and observation.env_version == ENV_VERSION
            )
    finally:
        environment.close()

    snapshot_environment = SchemaDriftEnvironment("flight_action_schema_v2")
    try:
        observation = snapshot_environment.reset(BOOK_TASK_ID, 1)
        plan = task_plan(observation, "r2_confirmed")
        descriptor = snapshot_environment.describe_tool("flights.book")
        adapted, _ = SchemaAdapter.adapt_action(plan.primary_actions[0], descriptor)
        assert snapshot_environment.step(adapted).ok
        checkpoint = snapshot_environment.snapshot()
        checkpoint_hash = snapshot_environment.state_hash()
        checkpoint_time = snapshot_environment.logical_time
        assert snapshot_environment.step(plan.primary_actions[1]).ok
        snapshot_environment.restore(checkpoint)
        snapshot_passed = bool(
            snapshot_environment.state_hash() == checkpoint_hash
            and snapshot_environment.logical_time == checkpoint_time
            and snapshot_environment.state_version == 1
            and snapshot_environment.describe_tool("flights.book") == descriptor
        )
    finally:
        snapshot_environment.close()
    return {
        "reset_iterations": 20,
        "reset_passed": reset_passed,
        "snapshot_restore_passed": snapshot_passed,
        "passed": reset_passed and snapshot_passed,
    }


def _baseline_rejection_checks() -> dict[str, Any]:
    results: dict[str, bool] = {}
    for task_id in TASK_IDS:
        environment = SchemaDriftEnvironment()
        try:
            environment.reset(task_id, 0)
            initial = environment.snapshot()
            do_nothing = evaluate_travel(initial, initial, [])
            fake_trace = [
                {
                    "event_id": "claim-only:0001",
                    "event_type": "evaluation_completed",
                    "tool_name": None,
                    "error_code": None,
                    "fault_id": None,
                }
            ]
            claim_only = evaluate_travel(initial, initial, fake_trace)
            results[f"{_task_slug(task_id)}_do_nothing_rejected"] = not do_nothing.task_success
            results[f"{_task_slug(task_id)}_claim_only_rejected"] = not claim_only.task_success
        finally:
            environment.close()
    return {"cases": results, "passed": all(results.values())}


def historical_source_manifest_check(project_root: Path) -> dict[str, Any]:
    details: dict[str, Any] = {}
    for version, relative_summary in _HISTORICAL_SUMMARIES.items():
        summary_path = project_root / relative_summary
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
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


def _validity_checks(
    episodes: Sequence[dict[str, Any]],
    traces_dir: Path,
    project_root: Path,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    checks["matrix_shape"] = {
        "episodes": len(episodes),
        "trace_files": len(list(traces_dir.glob("*.jsonl"))),
        "passed": len(episodes) == 24 and len(list(traces_dir.glob("*.jsonl"))) == 24,
    }

    paired_hashes: dict[str, list[str]] = {}
    paired_ok = True
    for task_id in TASK_IDS:
        for runtime_name in RUNTIMES:
            for seed in SEEDS:
                selected = [
                    episode
                    for episode in episodes
                    if episode["task_id"] == task_id
                    and episode["runtime"] == runtime_name
                    and episode["seed"] == seed
                ]
                hashes = sorted(episode["initial_state_hash"] for episode in selected)
                paired_hashes[f"{task_id}:{runtime_name}:{seed}"] = hashes
                paired_ok = paired_ok and len(selected) == 2 and len(set(hashes)) == 1
    checks["paired_initial_states"] = {"pairs": paired_hashes, "passed": paired_ok}

    clean = [episode for episode in episodes if episode["condition"] == "clean"]
    checks["clean_control_success"] = {
        "successes": sum(episode["evaluation"]["safe_success"] for episode in clean),
        "total": len(clean),
        "passed": len(clean) == 12
        and all(episode["evaluation"]["safe_success"] for episode in clean),
    }

    fault = [episode for episode in episodes if episode["condition"] == "fault"]
    expected_fault = {
        BOOK_TASK_ID: FLIGHT_ACTION_FAULT_ID,
        RECOVERY_TASK_ID: HOTEL_RESULT_FAULT_ID,
    }
    checks["single_registered_difference"] = {
        "fault_ids": {episode["episode_id"]: episode["observed_fault_ids"] for episode in fault},
        "passed": all(
            episode["observed_fault_ids"] == [expected_fault[episode["task_id"]]]
            for episode in fault
        )
        and all(not episode["observed_fault_ids"] for episode in clean),
    }

    r1_book_fault = [
        episode
        for episode in fault
        if episode["task_id"] == BOOK_TASK_ID and episode["runtime"] == "r1_guarded"
    ]
    checks["r1_action_drift_failure"] = {
        "failure_codes": [episode["execution"]["failure_code"] for episode in r1_book_fault],
        "passed": len(r1_book_fault) == 3
        and all(
            episode["execution"]["failure_code"] == "schema_version_unsupported"
            and episode["final_state_counts"]["flight_bookings"] == 0
            and not episode["evaluation"]["task_success"]
            for episode in r1_book_fault
        ),
    }

    r1_recovery_fault = [
        episode
        for episode in fault
        if episode["task_id"] == RECOVERY_TASK_ID and episode["runtime"] == "r1_guarded"
    ]
    checks["r1_output_drift_failure"] = {
        "failure_codes": [episode["execution"]["failure_code"] for episode in r1_recovery_fault],
        "passed": len(r1_recovery_fault) == 3
        and all(
            episode["execution"]["failure_code"] == "result_contract_violation"
            and episode["execution"]["result_contract_violations"] == 1
            and episode["final_state_counts"]["hotel_reservations"] == 1
            and not episode["evaluation"]["task_success"]
            for episode in r1_recovery_fault
        ),
    }

    r2_book_fault = [
        episode
        for episode in fault
        if episode["task_id"] == BOOK_TASK_ID and episode["runtime"] == "r2_schema_adapted"
    ]
    checks["r2_action_schema_recovery"] = {
        "adaptation_counts": [episode["schema_adaptation_count"] for episode in r2_book_fault],
        "passed": len(r2_book_fault) == 3
        and all(
            episode["execution"]["completed_plan"]
            and episode["schema_adaptation_count"] == 1
            and episode["output_normalization_count"] == 0
            and episode["evaluation"]["safe_success"]
            for episode in r2_book_fault
        ),
    }

    r2_recovery_fault = [
        episode
        for episode in fault
        if episode["task_id"] == RECOVERY_TASK_ID and episode["runtime"] == "r2_schema_adapted"
    ]
    checks["r2_output_schema_recovery"] = {
        "normalization_counts": [
            episode["output_normalization_count"] for episode in r2_recovery_fault
        ],
        "passed": len(r2_recovery_fault) == 3
        and all(
            episode["execution"]["completed_plan"]
            and episode["schema_adaptation_count"] == 0
            and episode["output_normalization_count"] == 1
            and episode["evaluation"]["safe_success"]
            for episode in r2_recovery_fault
        ),
    }

    checks["adapter_mutations_rejected"] = _adapter_mutation_checks()
    checks["public_descriptors_non_oracular"] = _descriptor_checks()
    checks["reset_and_snapshot_restore"] = _reset_and_snapshot_checks()
    checks["baselines_rejected"] = _baseline_rejection_checks()
    checks["historical_source_manifests"] = historical_source_manifest_check(project_root)

    serialized_traces = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden_markers = [
        marker
        for marker in (
            b"synthetic-traveler-",
            b"synthetic-flight-",
            b"synthetic-hotel-",
            b'"arguments"',
            b'"payment_id"',
            b'"visible_task"',
        )
        if marker in serialized_traces
    ]
    checks["digest_only_traces"] = {
        "forbidden_payload_markers": [marker.decode() for marker in forbidden_markers],
        "passed": not forbidden_markers,
    }
    return checks


def _normalize_for_comparison(episodes: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for episode in episodes:
        item = dict(episode)
        item.pop("trace_file", None)
        normalized.append(item)
    return normalized


def run_schema_experiment(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    primary_episodes = _run_matrix(traces_dir)
    shadow_episodes = _run_matrix(None)
    repeat_results_deterministic = _normalize_for_comparison(
        primary_episodes
    ) == _normalize_for_comparison(shadow_episodes)
    validity = _validity_checks(primary_episodes, traces_dir, project_root)
    validity["repeat_results_deterministic"] = {"passed": repeat_results_deterministic}
    validity["all_selected_checks_passed"] = all(
        value["passed"] for key, value in validity.items() if key != "all_selected_checks_passed"
    )
    assert validity["all_selected_checks_passed"]

    aggregate = _aggregate(primary_episodes)
    r1 = aggregate["by_runtime"]["r1_guarded"]
    r2 = aggregate["by_runtime"]["r2_schema_adapted"]
    assert r1["clean_successes"] == 6
    assert r1["fault_successes"] == 0
    assert r1["recovery_rate"] == 0.0
    assert r2["clean_successes"] == 6
    assert r2["fault_successes"] == 6
    assert r2["recovery_rate"] == 1.0
    assert r2["schema_adaptation_count"] == 3
    assert r2["output_normalization_count"] == 3
    assert aggregate["paired_recovery_rate_delta_r2_minus_r1"] == 1.0

    return {
        "metadata": {
            "increment_version": __version__,
            "root_project_version": "0.3.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "environment_version": ENV_VERSION,
            "task_ids": list(TASK_IDS),
            "seeds": list(SEEDS),
            "runtimes": list(RUNTIMES),
            "conditions": list(CONDITIONS),
            "registered_differences": {
                BOOK_TASK_ID: "flights.book action contract 1.0 -> 2.0",
                RECOVERY_TASK_ID: "hotels.book success result contract 1.0 -> 2.0",
            },
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "trace_payload_policy": "digests and typed metadata only",
        },
        "episodes": primary_episodes,
        "aggregate": aggregate,
        "validity": validity,
        "limitations": [
            "Two controlled schema changes over the existing synthetic Travel tasks.",
            "Static explicit mappings, not automatic schema matching or model inference.",
            "Fixed oracle action plans, not an LLM or learned policy.",
            "No simultaneous drift, unregistered version negotiation, scheduler, or UI.",
            "No model API, real account, external target, credential, or network access.",
        ],
    }
