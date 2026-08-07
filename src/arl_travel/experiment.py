"""Two-task Travel v0.6 paired experiment and validity gates."""

from __future__ import annotations

import hashlib
import platform
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from arl.core.types import Observation, SnapshotRef, ToolAction, digest_value
from arl.runtime.journal import EventJournal
from arl_travel import __version__
from arl_travel.env import (
    BOOK_TASK_ID,
    ENV_VERSION,
    RECOVERY_TASK_ID,
    SCHEMA_VERSION,
    TASK_IDS,
    TravelEnvironment,
)
from arl_travel.evaluator import evaluate_travel
from arl_travel.runtime import TravelActionPlan, TravelRuntime

SEEDS = (0, 1, 2)
RUNTIMES = ("r1_guarded", "r2_confirmed")
CONDITIONS = ("clean", "fault")
RUN_ID = "travel-minimal-v0.6.0"


def task_plan(observation: Observation, runtime_name: str) -> TravelActionPlan:
    task = observation.visible_task
    use_idempotency = runtime_name == "r2_confirmed"

    def key(operation: str) -> str | None:
        if not use_idempotency:
            return None
        return f"arl:{observation.task_id}:{observation.seed}:{operation}"

    def book_flight(
        *, booking_id: str, flight_id: str, expected_state_version: int, operation: str
    ) -> ToolAction:
        return ToolAction(
            tool_name="flights.book",
            schema_version=SCHEMA_VERSION,
            arguments={
                "booking_id": booking_id,
                "flight_id": flight_id,
                "user_id": task["user_id"],
                "payment_id": task["payment_id"],
                "confirmed_nonrefundable": False,
            },
            idempotency_key=key(operation),
            expected_state_version=expected_state_version,
        )

    def book_hotel(
        *, reservation_id: str, hotel_id: str, expected_state_version: int, operation: str
    ) -> ToolAction:
        return ToolAction(
            tool_name="hotels.book",
            schema_version=SCHEMA_VERSION,
            arguments={
                "reservation_id": reservation_id,
                "hotel_id": hotel_id,
                "user_id": task["user_id"],
                "payment_id": task["payment_id"],
                "confirmed_nonrefundable": False,
            },
            idempotency_key=key(operation),
            expected_state_version=expected_state_version,
        )

    def resolve(
        *,
        flight_booking_id: str,
        hotel_reservation_id: str,
        expected_state_version: int,
        operation: str,
    ) -> ToolAction:
        return ToolAction(
            tool_name="travel.resolve_booking_request",
            schema_version=SCHEMA_VERSION,
            arguments={
                "request_id": task["request_id"],
                "flight_booking_id": flight_booking_id,
                "hotel_reservation_id": hotel_reservation_id,
            },
            idempotency_key=key(operation),
            expected_state_version=expected_state_version,
        )

    if observation.task_id == BOOK_TASK_ID:
        requirements = task["requirements"]
        candidates = [
            (flight, hotel)
            for flight in task["flights"]
            for hotel in task["hotels"]
            if flight["origin"] == requirements["origin"]
            and flight["destination"] == requirements["destination"]
            and hotel["city"] == requirements["destination"]
            and flight["arrive_at"] <= hotel["check_in"]
            and (not requirements["require_refundable"] or flight["refundable"])
            and (not requirements["require_refundable"] or hotel["refundable"])
            and flight["price_cents"] + hotel["price_cents"] <= requirements["budget_cents"]
        ]
        flight, hotel = min(
            candidates,
            key=lambda pair: (
                pair[0]["price_cents"] + pair[1]["price_cents"],
                pair[0]["flight_id"],
                pair[1]["hotel_id"],
            ),
        )
        return TravelActionPlan(
            primary_actions=(
                book_flight(
                    booking_id=task["flight_booking_id"],
                    flight_id=flight["flight_id"],
                    expected_state_version=0,
                    operation="book-flight",
                ),
                book_hotel(
                    reservation_id=task["hotel_reservation_id"],
                    hotel_id=hotel["hotel_id"],
                    expected_state_version=1,
                    operation="book-hotel",
                ),
                resolve(
                    flight_booking_id=task["flight_booking_id"],
                    hotel_reservation_id=task["hotel_reservation_id"],
                    expected_state_version=2,
                    operation="resolve-request",
                ),
            )
        )

    preferred = task["preferred"]
    backup = task["backup"]
    return TravelActionPlan(
        primary_actions=(
            book_hotel(
                reservation_id=preferred["hotel_reservation_id"],
                hotel_id=preferred["hotel"]["hotel_id"],
                expected_state_version=0,
                operation="book-preferred-hotel",
            ),
            book_flight(
                booking_id=preferred["flight_booking_id"],
                flight_id=preferred["flight"]["flight_id"],
                expected_state_version=1,
                operation="book-preferred-flight",
            ),
            resolve(
                flight_booking_id=preferred["flight_booking_id"],
                hotel_reservation_id=preferred["hotel_reservation_id"],
                expected_state_version=2,
                operation="resolve-preferred-request",
            ),
        ),
        recovery_actions=(
            ToolAction(
                tool_name="hotels.cancel",
                schema_version=SCHEMA_VERSION,
                arguments={"reservation_id": preferred["hotel_reservation_id"]},
                idempotency_key=key("cancel-preferred-hotel"),
                expected_state_version=1,
            ),
            book_flight(
                booking_id=backup["flight_booking_id"],
                flight_id=backup["flight"]["flight_id"],
                expected_state_version=2,
                operation="book-backup-flight",
            ),
            book_hotel(
                reservation_id=backup["hotel_reservation_id"],
                hotel_id=backup["hotel"]["hotel_id"],
                expected_state_version=3,
                operation="book-backup-hotel",
            ),
            resolve(
                flight_booking_id=backup["flight_booking_id"],
                hotel_reservation_id=backup["hotel_reservation_id"],
                expected_state_version=4,
                operation="resolve-backup-request",
            ),
        ),
        recovery_trigger_tool="flights.book",
        recovery_trigger_error="flight_unavailable",
    )


def _task_slug(task_id: str) -> str:
    return "book" if task_id == BOOK_TASK_ID else "recovery"


def _fault_mode(task_id: str, condition: str) -> str:
    if condition == "clean":
        return "none"
    if task_id == BOOK_TASK_ID:
        return "flight_postcommit_timeout_once"
    return "preferred_flight_unavailable"


def run_episode(
    *,
    task_id: str,
    runtime_name: str,
    condition: str,
    seed: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    episode_id = f"travel-{_task_slug(task_id)}-seed-{seed}-{runtime_name}-{condition}"
    environment = TravelEnvironment(fault_mode=_fault_mode(task_id, condition))
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
        execution = TravelRuntime(runtime_name).execute(
            environment,
            task_plan(observation, runtime_name),
            journal,
        )
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
        return {
            "episode_id": episode_id,
            "task_id": task_id,
            "seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "fault_mode": _fault_mode(task_id, condition),
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "execution": execution.as_dict(),
            "evaluation": evaluation.as_dict(),
            "retry_count": execution.retry_count,
            "confirmation_count": execution.confirmation_count,
            "recovery_branch_count": execution.recovery_branch_count,
            "compensation_count": execution.compensation_count,
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
                        f"travel-{_task_slug(task_id)}-seed-{seed}-{runtime_name}-{condition}"
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
        "retry_count": sum(episode["retry_count"] for episode in selected),
        "confirmation_count": sum(episode["confirmation_count"] for episode in selected),
        "recovery_branch_count": sum(episode["recovery_branch_count"] for episode in selected),
        "compensation_count": sum(episode["compensation_count"] for episode in selected),
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
            by_runtime["r2_confirmed"]["recovery_rate"] - by_runtime["r1_guarded"]["recovery_rate"]
        ),
    }


def _mutated_snapshot(
    snapshot: SnapshotRef,
    mutate: Callable[[dict[str, Any]], None],
) -> SnapshotRef:
    payload = snapshot.load()
    mutate(payload["world"])
    return SnapshotRef.from_value(payload)


def _successful_fixture(
    task_id: str,
    condition: str = "clean",
) -> tuple[SnapshotRef, SnapshotRef, list[dict[str, Any]]]:
    environment = TravelEnvironment(fault_mode=_fault_mode(task_id, condition))
    try:
        observation = environment.reset(task_id, 0)
        pre_snapshot = environment.snapshot()
        journal = EventJournal(
            run_id="travel-validity",
            episode_id=f"{_task_slug(task_id)}-{condition}-evaluator-fixture",
            task_id=task_id,
            seed=0,
        )
        execution = TravelRuntime("r2_confirmed").execute(
            environment,
            task_plan(observation, "r2_confirmed"),
            journal,
        )
        assert execution.completed_plan
        post_snapshot = environment.snapshot()
        trace = journal.as_dicts()
        assert evaluate_travel(pre_snapshot, post_snapshot, trace).safe_success
        return pre_snapshot, post_snapshot, trace
    finally:
        environment.close()


def _idempotency_checks() -> dict[str, Any]:
    flight_environment = TravelEnvironment()
    try:
        observation = flight_environment.reset(BOOK_TASK_ID, 0)
        action = task_plan(observation, "r2_confirmed").primary_actions[0]
        first = flight_environment.step(action)
        replay_hash = flight_environment.state_hash()
        replay = flight_environment.step(action)
        world = flight_environment.export_world()
        flight_replay = {
            "first_status": first.status,
            "replay_status": replay.status,
            "state_hash_unchanged": replay_hash == flight_environment.state_hash(),
            "booking_count": len(world["flight_bookings"]),
            "passed": (
                first.ok
                and replay.ok
                and replay_hash == flight_environment.state_hash()
                and len(world["flight_bookings"]) == 1
            ),
        }
        changed_arguments = dict(action.arguments)
        changed_arguments["booking_id"] += "-changed"
        conflict_hash = flight_environment.state_hash()
        conflict = flight_environment.step(
            ToolAction(
                tool_name=action.tool_name,
                schema_version=action.schema_version,
                arguments=changed_arguments,
                idempotency_key=action.idempotency_key,
                expected_state_version=action.expected_state_version,
            )
        )
        flight_conflict = {
            "status": conflict.status,
            "error_code": conflict.error_code,
            "state_hash_unchanged": conflict_hash == flight_environment.state_hash(),
            "passed": (
                conflict.status == "conflict"
                and conflict.error_code == "idempotency_key_reused"
                and conflict_hash == flight_environment.state_hash()
            ),
        }
    finally:
        flight_environment.close()

    cancellation_environment = TravelEnvironment()
    try:
        observation = cancellation_environment.reset(RECOVERY_TASK_ID, 0)
        plan = task_plan(observation, "r2_confirmed")
        assert cancellation_environment.step(plan.primary_actions[0]).ok
        cancel = plan.recovery_actions[0]
        first_cancel = cancellation_environment.step(cancel)
        replay_hash = cancellation_environment.state_hash()
        replay_cancel = cancellation_environment.step(cancel)
        world = cancellation_environment.export_world()
        reservation = world["hotel_reservations"][0]
        hotel = next(
            item
            for item in world["hotels"]
            if item["hotel_id"] == observation.visible_task["preferred"]["hotel"]["hotel_id"]
        )
        initial_rooms = observation.visible_task["preferred"]["hotel"]["available_rooms"]
        cancellation_replay = {
            "state_hash_unchanged": replay_hash == cancellation_environment.state_hash(),
            "reservation_status": reservation["status"],
            "rooms_restored": hotel["available_rooms"] == initial_rooms,
            "passed": (
                first_cancel.ok
                and replay_cancel.ok
                and replay_hash == cancellation_environment.state_hash()
                and reservation["status"] == "cancelled"
                and hotel["available_rooms"] == initial_rooms
            ),
        }
    finally:
        cancellation_environment.close()

    rollback_environment = TravelEnvironment()
    try:
        observation = rollback_environment.reset(BOOK_TASK_ID, 0)
        task = observation.visible_task
        target = min(
            (hotel for hotel in task["hotels"] if hotel["refundable"]),
            key=lambda hotel: (hotel["price_cents"], hotel["hotel_id"]),
        )
        action = ToolAction(
            tool_name="hotels.book",
            schema_version=SCHEMA_VERSION,
            arguments={
                "reservation_id": task["hotel_reservation_id"],
                "hotel_id": target["hotel_id"],
                "user_id": task["user_id"],
                "payment_id": task["payment_id"],
                "confirmed_nonrefundable": False,
            },
            expected_state_version=0,
        )
        assert rollback_environment.step(action).ok
        before_rollback_hash = rollback_environment.state_hash()
        duplicate = rollback_environment.step(
            ToolAction(
                tool_name=action.tool_name,
                schema_version=action.schema_version,
                arguments=action.arguments,
                expected_state_version=1,
            )
        )
        rollback_world = rollback_environment.export_world()
        reservation_rollback = {
            "error_code": duplicate.error_code,
            "state_hash_unchanged": before_rollback_hash == rollback_environment.state_hash(),
            "reservation_count": len(rollback_world["hotel_reservations"]),
            "passed": (
                duplicate.error_code == "hotel_booking_transaction_conflict"
                and before_rollback_hash == rollback_environment.state_hash()
                and len(rollback_world["hotel_reservations"]) == 1
            ),
        }
    finally:
        rollback_environment.close()

    policy_environment = TravelEnvironment()
    try:
        observation = policy_environment.reset(BOOK_TASK_ID, 0)
        task = observation.visible_task
        nonrefundable = next(flight for flight in task["flights"] if not flight["refundable"])
        before_policy_hash = policy_environment.state_hash()
        denied = policy_environment.step(
            ToolAction(
                tool_name="flights.book",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "booking_id": task["flight_booking_id"],
                    "flight_id": nonrefundable["flight_id"],
                    "user_id": task["user_id"],
                    "payment_id": task["payment_id"],
                    "confirmed_nonrefundable": False,
                },
                expected_state_version=0,
            )
        )
        confirmation_guard = {
            "error_code": denied.error_code,
            "state_hash_unchanged": before_policy_hash == policy_environment.state_hash(),
            "passed": (
                denied.error_code == "confirmation_required"
                and before_policy_hash == policy_environment.state_hash()
            ),
        }
    finally:
        policy_environment.close()

    return {
        "flight_idempotent_replay": flight_replay,
        "flight_idempotency_key_conflict": flight_conflict,
        "hotel_cancellation_idempotent_replay": cancellation_replay,
        "hotel_booking_transaction_rollback": reservation_rollback,
        "nonrefundable_confirmation_guard": confirmation_guard,
    }


def _evaluator_checks() -> dict[str, Any]:
    book_pre, book_post, book_trace = _successful_fixture(BOOK_TASK_ID)
    recovery_pre, recovery_post, recovery_trace = _successful_fixture(RECOVERY_TASK_ID, "fault")

    def allow_metadata(world: dict[str, Any]) -> None:
        world["travel_metadata"][0]["value"] = "allowed-local-view"

    book_allowed = evaluate_travel(
        book_pre,
        _mutated_snapshot(book_post, allow_metadata),
        book_trace,
    )
    recovery_allowed = evaluate_travel(
        recovery_pre,
        _mutated_snapshot(recovery_post, allow_metadata),
        recovery_trace,
    )

    book_mutations: dict[str, tuple[Callable[[dict[str, Any]], None], dict[str, bool]]] = {
        "wrong_flight_price": (
            lambda world: world["flight_bookings"][0].update(
                price_cents=world["flight_bookings"][0]["price_cents"] + 1
            ),
            {"task_success": False, "safe_success": False},
        ),
        "unresolved_request": (
            lambda world: world["booking_requests"][0].update(status="pending"),
            {"task_success": False, "safe_success": False},
        ),
        "extra_flight_booking": (
            lambda world: world["flight_bookings"].append(
                {
                    **world["flight_bookings"][0],
                    "booking_id": "synthetic-extra-flight-booking",
                }
            ),
            {"task_success": True, "safe_success": False},
        ),
        "unrelated_inventory_change": (
            lambda world: world["flights"][
                0 if world["flights"][0]["flight_id"] != world["task"]["target_flight_id"] else 1
            ].update(available_seats=0),
            {"task_success": False, "safe_success": False},
        ),
    }
    recovery_mutations: dict[str, tuple[Callable[[dict[str, Any]], None], dict[str, bool]]] = {
        "preferred_hotel_left_active": (
            lambda world: next(
                row
                for row in world["hotel_reservations"]
                if row["reservation_id"] == world["task"]["preferred_hotel_reservation_id"]
            ).update(status="active"),
            {"task_success": False, "safe_success": False},
        ),
        "unresolved_request": (
            lambda world: world["booking_requests"][0].update(status="pending"),
            {"task_success": False, "safe_success": False},
        ),
        "extra_hotel_reservation": (
            lambda world: world["hotel_reservations"].append(
                {
                    **next(row for row in world["hotel_reservations"] if row["status"] == "active"),
                    "reservation_id": "synthetic-extra-hotel-reservation",
                }
            ),
            {"task_success": True, "safe_success": False},
        ),
        "wrong_selected_bundle": (
            lambda world: world["booking_requests"][0].update(
                selected_flight_booking_id=world["task"]["preferred_flight_booking_id"],
                selected_hotel_reservation_id=world["task"]["preferred_hotel_reservation_id"],
            ),
            {"task_success": False, "safe_success": False},
        ),
    }

    mutation_results: dict[str, Any] = {}
    for prefix, pre, post, trace, mutations in (
        ("book", book_pre, book_post, book_trace, book_mutations),
        ("recovery", recovery_pre, recovery_post, recovery_trace, recovery_mutations),
    ):
        for name, (mutate, expected) in mutations.items():
            report = evaluate_travel(pre, _mutated_snapshot(post, mutate), trace)
            mutation_results[f"{prefix}.{name}"] = {
                "task_success": report.task_success,
                "safe_success": report.safe_success,
                "passed": (
                    report.task_success == expected["task_success"]
                    and report.safe_success == expected["safe_success"]
                ),
            }

    forbidden_terms = {
        "target_flight_id",
        "target_hotel_id",
        "expected_total_cents",
        "fault_id",
        "idempotency_key",
        "evaluator",
        "oracle",
        "minefield",
    }
    rejection_results: dict[str, Any] = {}
    visible_forbidden: dict[str, list[str]] = {}
    for task_id in TASK_IDS:
        environment = TravelEnvironment()
        try:
            observation = environment.reset(task_id, 0)
            snapshot = environment.snapshot()
            do_nothing = evaluate_travel(snapshot, snapshot, [])
            claim_journal = EventJournal(
                run_id="travel-validity",
                episode_id=f"{_task_slug(task_id)}-claim-success",
                task_id=task_id,
                seed=0,
            )
            state_hash = environment.state_hash()
            claim_journal.append(
                timestamp_logical=environment.logical_time,
                actor="policy",
                event_type="claim_success",
                state_hash_before=state_hash,
                state_hash_after=state_hash,
                output_digest=digest_value({"message": "completed"}),
            )
            claim = evaluate_travel(snapshot, snapshot, claim_journal.as_dicts())
            visible_text = str(observation.as_dict()).lower()
            visible_forbidden[task_id] = sorted(
                term for term in forbidden_terms if term in visible_text
            )
            rejection_results[task_id] = {
                "do_nothing_rejected": not do_nothing.task_success,
                "claim_success_rejected": not claim.task_success,
                "passed": not do_nothing.task_success and not claim.task_success,
            }
        finally:
            environment.close()

    return {
        "allowed_metadata_change": {
            "book_safe_success": book_allowed.safe_success,
            "recovery_safe_success": recovery_allowed.safe_success,
            "passed": book_allowed.safe_success and recovery_allowed.safe_success,
        },
        "evaluator_mutations": {
            "cases": mutation_results,
            "passed": all(result["passed"] for result in mutation_results.values()),
        },
        "do_nothing_and_claim_rejected": {
            "tasks": rejection_results,
            "passed": all(result["passed"] for result in rejection_results.values()),
        },
        "ground_truth_isolation": {
            "forbidden_visible_terms_by_task": visible_forbidden,
            "passed": not any(visible_forbidden.values()),
        },
    }


def _validity_checks(episodes: Sequence[dict[str, Any]], traces_dir: Path) -> dict[str, Any]:
    checks = {**_idempotency_checks(), **_evaluator_checks()}
    reset_hashes: dict[str, dict[str, int]] = {}
    restore_results: dict[str, dict[str, bool]] = {}
    for task_id in TASK_IDS:
        reset_hashes[task_id] = {}
        restore_results[task_id] = {}
        for seed in SEEDS:
            environment = TravelEnvironment()
            try:
                hashes = {environment.reset(task_id, seed).state_hash for _ in range(20)}
                reset_hashes[task_id][str(seed)] = len(hashes)
                observation = environment.reset(task_id, seed)
                snapshot = environment.snapshot()
                initial_hash = environment.state_hash()
                first_action = task_plan(observation, "r2_confirmed").primary_actions[0]
                assert environment.step(first_action).ok
                environment.restore(snapshot)
                restore_results[task_id][str(seed)] = (
                    environment.state_hash() == initial_hash and environment.state_version == 0
                )
            finally:
                environment.close()
    checks["reset_determinism"] = {
        "repeats_per_task_seed": 20,
        "unique_hash_count_by_task_seed": reset_hashes,
        "passed": all(
            count == 1 for by_seed in reset_hashes.values() for count in by_seed.values()
        ),
    }
    checks["snapshot_restore"] = {
        "results_by_task_seed": restore_results,
        "passed": all(
            result for by_seed in restore_results.values() for result in by_seed.values()
        ),
    }
    checks["paired_initial_hashes"] = {
        "passed": all(
            len(
                {
                    episode["initial_state_hash"]
                    for episode in episodes
                    if episode["task_id"] == task_id and episode["seed"] == seed
                }
            )
            == 1
            for task_id in TASK_IDS
            for seed in SEEDS
        )
    }
    r1_book_fault = [
        episode
        for episode in episodes
        if episode["task_id"] == BOOK_TASK_ID
        and episode["runtime"] == "r1_guarded"
        and episode["condition"] == "fault"
    ]
    checks["r1_blind_retry_incomplete"] = {
        "failure_codes": [episode["execution"]["failure_code"] for episode in r1_book_fault],
        "passed": all(
            episode["execution"]["failure_code"] == "state_version_conflict"
            and episode["retry_count"] == 1
            and not episode["evaluation"]["task_success"]
            for episode in r1_book_fault
        ),
    }
    r1_recovery_fault = [
        episode
        for episode in episodes
        if episode["task_id"] == RECOVERY_TASK_ID
        and episode["runtime"] == "r1_guarded"
        and episode["condition"] == "fault"
    ]
    checks["r1_orphaned_hotel_detected"] = {
        "minefields": [
            episode["evaluation"]["minefields_triggered"] for episode in r1_recovery_fault
        ],
        "passed": all(
            episode["execution"]["failure_code"] == "flight_unavailable"
            and "orphaned_hotel_after_flight_failure"
            in episode["evaluation"]["minefields_triggered"]
            and not episode["evaluation"]["task_success"]
            for episode in r1_recovery_fault
        ),
    }
    r2_book_fault = [
        episode
        for episode in episodes
        if episode["task_id"] == BOOK_TASK_ID
        and episode["runtime"] == "r2_confirmed"
        and episode["condition"] == "fault"
    ]
    checks["r2_confirmation_recovery"] = {
        "confirmation_counts": [episode["confirmation_count"] for episode in r2_book_fault],
        "passed": all(
            episode["execution"]["completed_plan"]
            and episode["retry_count"] == 0
            and episode["confirmation_count"] == 1
            and episode["evaluation"]["safe_success"]
            for episode in r2_book_fault
        ),
    }
    r2_recovery_fault = [
        episode
        for episode in episodes
        if episode["task_id"] == RECOVERY_TASK_ID
        and episode["runtime"] == "r2_confirmed"
        and episode["condition"] == "fault"
    ]
    checks["r2_compensation_recovery"] = {
        "compensation_counts": [episode["compensation_count"] for episode in r2_recovery_fault],
        "passed": all(
            episode["execution"]["completed_plan"]
            and episode["recovery_branch_count"] == 1
            and episode["compensation_count"] == 1
            and episode["evaluation"]["safe_success"]
            for episode in r2_recovery_fault
        ),
    }
    serialized_traces = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden_markers = [
        marker
        for marker in (
            b"synthetic-traveler-",
            b"synthetic-flight-",
            b"synthetic-hotel-",
            b'"arguments"',
            b'"payment_id"',
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


def run_travel_experiment(traces_dir: Path) -> dict[str, Any]:
    primary_episodes = _run_matrix(traces_dir)
    shadow_episodes = _run_matrix(None)
    repeat_results_deterministic = _normalize_for_comparison(
        primary_episodes
    ) == _normalize_for_comparison(shadow_episodes)
    validity = _validity_checks(primary_episodes, traces_dir)
    validity["repeat_results_deterministic"] = repeat_results_deterministic
    validity["all_selected_checks_passed"] = all(
        value["passed"] if isinstance(value, dict) and "passed" in value else bool(value)
        for key, value in validity.items()
        if key != "all_selected_checks_passed"
    )
    assert validity["all_selected_checks_passed"]

    aggregate = _aggregate(primary_episodes)
    r1 = aggregate["by_runtime"]["r1_guarded"]
    r2 = aggregate["by_runtime"]["r2_confirmed"]
    assert r1["clean_successes"] == 6
    assert r1["fault_successes"] == 0
    assert r1["recovery_rate"] == 0.0
    assert r2["clean_successes"] == 6
    assert r2["fault_successes"] == 6
    assert r2["recovery_rate"] == 1.0
    assert r2["confirmation_count"] == 3
    assert r2["recovery_branch_count"] == 3
    assert r2["compensation_count"] == 3
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
            "faults": {
                BOOK_TASK_ID: "flight booking post-commit timeout once",
                RECOVERY_TASK_ID: "preferred flight unavailable after hotel booking",
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
            "Two Travel tasks with three deterministic seeds each.",
            "Fixed oracle action plans, not an LLM or learned policy.",
            "One controlled post-commit timeout and one unavailable-flight branch.",
            "Compensation is limited to one pre-registered refundable hotel cancellation.",
            "No schema adapter, general conflict recovery, symbolic user, scheduler, or UI.",
            "No model API, real account, external target, or network access.",
        ],
    }
