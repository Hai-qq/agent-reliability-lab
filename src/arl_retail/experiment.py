"""Two-task Retail v0.5 paired experiment and validity gates."""

from __future__ import annotations

import hashlib
import platform
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from arl.core.types import Observation, SnapshotRef, ToolAction, digest_value
from arl.runtime.journal import EventJournal
from arl_retail import __version__
from arl_retail.env import (
    ENV_VERSION,
    PURCHASE_TASK_ID,
    REFUND_TASK_ID,
    SCHEMA_VERSION,
    TASK_IDS,
    RetailEnvironment,
)
from arl_retail.evaluator import evaluate_retail
from arl_retail.runtime import RetailRuntime

SEEDS = (0, 1, 2)
RUNTIMES = ("r1_guarded", "r2_confirmed")
CONDITIONS = ("clean", "fault")
RUN_ID = "retail-minimal-v0.5.0"


def task_actions(observation: Observation, runtime_name: str) -> list[ToolAction]:
    task = observation.visible_task
    use_idempotency = runtime_name == "r2_confirmed"

    def key(operation: str) -> str | None:
        if not use_idempotency:
            return None
        return f"arl:{observation.task_id}:{observation.seed}:{operation}"

    if observation.task_id == PURCHASE_TASK_ID:
        target = min(
            task["offers"],
            key=lambda offer: (offer["final_unit_cents"], offer["product_id"]),
        )
        return [
            ToolAction(
                tool_name="cart.add_item",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "cart_id": task["cart_id"],
                    "product_id": target["product_id"],
                    "quantity": task["quantity"],
                },
                idempotency_key=key("add-item"),
                expected_state_version=0,
            ),
            ToolAction(
                tool_name="cart.apply_coupon",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "cart_id": task["cart_id"],
                    "coupon_code": target["coupon_code"],
                },
                idempotency_key=key("apply-coupon"),
                expected_state_version=1,
            ),
            ToolAction(
                tool_name="orders.place_order",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "order_id": task["order_id"],
                    "cart_id": task["cart_id"],
                    "customer_id": task["customer_id"],
                    "request_id": task["request_id"],
                },
                idempotency_key=key("place-order"),
                expected_state_version=2,
            ),
            ToolAction(
                tool_name="retail.resolve_purchase_request",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "request_id": task["request_id"],
                    "order_id": task["order_id"],
                },
                idempotency_key=key("resolve-purchase-request"),
                expected_state_version=3,
            ),
        ]

    return [
        ToolAction(
            tool_name="refunds.issue_partial_refund",
            schema_version=SCHEMA_VERSION,
            arguments={
                "refund_id": task["refund_id"],
                "request_id": task["request_id"],
                "order_id": task["order_id"],
                "product_id": task["product_id"],
                "quantity": task["quantity"],
                "reason": task["reason"],
            },
            idempotency_key=key("issue-refund"),
            expected_state_version=0,
        ),
        ToolAction(
            tool_name="retail.resolve_refund_request",
            schema_version=SCHEMA_VERSION,
            arguments={
                "request_id": task["request_id"],
                "refund_id": task["refund_id"],
            },
            idempotency_key=key("resolve-refund-request"),
            expected_state_version=1,
        ),
    ]


def _task_slug(task_id: str) -> str:
    return "purchase" if task_id == PURCHASE_TASK_ID else "refund"


def _fault_mode(task_id: str, condition: str) -> str:
    if condition == "clean":
        return "none"
    if task_id == PURCHASE_TASK_ID:
        return "order_postcommit_timeout_once"
    return "refund_postcommit_timeout_once"


def run_episode(
    *,
    task_id: str,
    runtime_name: str,
    condition: str,
    seed: int,
    trace_path: Path | None,
) -> dict[str, Any]:
    episode_id = f"retail-{_task_slug(task_id)}-seed-{seed}-{runtime_name}-{condition}"
    environment = RetailEnvironment(fault_mode=_fault_mode(task_id, condition))
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
        execution = RetailRuntime(runtime_name).execute(
            environment,
            task_actions(observation, runtime_name),
            journal,
        )
        evaluation = evaluate_retail(
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
            "final_state_counts": {
                "orders": len(world["orders"]),
                "order_items": len(world["order_items"]),
                "refunds": len(world["refunds"]),
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
                        f"retail-{_task_slug(task_id)}-seed-{seed}-{runtime_name}-{condition}"
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


def _successful_fixture(task_id: str) -> tuple[SnapshotRef, SnapshotRef, list[dict[str, Any]]]:
    environment = RetailEnvironment()
    try:
        observation = environment.reset(task_id, 0)
        pre_snapshot = environment.snapshot()
        journal = EventJournal(
            run_id="retail-validity",
            episode_id=f"{_task_slug(task_id)}-evaluator-fixture",
            task_id=task_id,
            seed=0,
        )
        execution = RetailRuntime("r2_confirmed").execute(
            environment,
            task_actions(observation, "r2_confirmed"),
            journal,
        )
        assert execution.completed_plan
        post_snapshot = environment.snapshot()
        trace = journal.as_dicts()
        assert evaluate_retail(pre_snapshot, post_snapshot, trace).safe_success
        return pre_snapshot, post_snapshot, trace
    finally:
        environment.close()


def _idempotency_checks() -> dict[str, Any]:
    purchase_environment = RetailEnvironment()
    try:
        observation = purchase_environment.reset(PURCHASE_TASK_ID, 0)
        actions = task_actions(observation, "r2_confirmed")
        assert purchase_environment.step(actions[0]).ok
        assert purchase_environment.step(actions[1]).ok
        first = purchase_environment.step(actions[2])
        before_replay_hash = purchase_environment.state_hash()
        replay = purchase_environment.step(actions[2])
        purchase_world = purchase_environment.export_world()
        order_replay = {
            "first_status": first.status,
            "replay_status": replay.status,
            "state_hash_unchanged": before_replay_hash == purchase_environment.state_hash(),
            "order_count": len(purchase_world["orders"]),
            "passed": (
                first.ok
                and replay.ok
                and before_replay_hash == purchase_environment.state_hash()
                and len(purchase_world["orders"]) == 1
            ),
        }
        changed_arguments = dict(actions[2].arguments)
        changed_arguments["order_id"] += "-changed"
        conflict_before_hash = purchase_environment.state_hash()
        conflict = purchase_environment.step(
            ToolAction(
                tool_name=actions[2].tool_name,
                schema_version=actions[2].schema_version,
                arguments=changed_arguments,
                idempotency_key=actions[2].idempotency_key,
                expected_state_version=actions[2].expected_state_version,
            )
        )
        order_conflict = {
            "status": conflict.status,
            "error_code": conflict.error_code,
            "state_hash_unchanged": conflict_before_hash == purchase_environment.state_hash(),
            "passed": (
                conflict.status == "conflict"
                and conflict.error_code == "idempotency_key_reused"
                and conflict_before_hash == purchase_environment.state_hash()
            ),
        }
    finally:
        purchase_environment.close()

    refund_environment = RetailEnvironment()
    try:
        observation = refund_environment.reset(REFUND_TASK_ID, 0)
        action = task_actions(observation, "r2_confirmed")[0]
        first_refund = refund_environment.step(action)
        before_refund_replay_hash = refund_environment.state_hash()
        replay_refund = refund_environment.step(action)
        refund_world = refund_environment.export_world()
        refund_replay = {
            "state_hash_unchanged": (before_refund_replay_hash == refund_environment.state_hash()),
            "refund_count": len(refund_world["refunds"]),
            "passed": (
                first_refund.ok
                and replay_refund.ok
                and before_refund_replay_hash == refund_environment.state_hash()
                and len(refund_world["refunds"]) == 1
            ),
        }
    finally:
        refund_environment.close()

    rollback_environment = RetailEnvironment()
    try:
        observation = rollback_environment.reset(REFUND_TASK_ID, 0)
        first_action = task_actions(observation, "r1_guarded")[0]
        assert rollback_environment.step(first_action).ok
        before_rollback_hash = rollback_environment.state_hash()
        duplicate = rollback_environment.step(
            ToolAction(
                tool_name=first_action.tool_name,
                schema_version=first_action.schema_version,
                arguments=first_action.arguments,
                expected_state_version=1,
            )
        )
        rollback_world = rollback_environment.export_world()
        target_item = next(
            item
            for item in rollback_world["order_items"]
            if item["product_id"] == observation.visible_task["product_id"]
        )
        refund_rollback = {
            "error_code": duplicate.error_code,
            "state_hash_unchanged": before_rollback_hash == rollback_environment.state_hash(),
            "refund_count": len(rollback_world["refunds"]),
            "refunded_quantity": target_item["refunded_quantity"],
            "passed": (
                duplicate.error_code == "refund_transaction_conflict"
                and before_rollback_hash == rollback_environment.state_hash()
                and len(rollback_world["refunds"]) == 1
                and target_item["refunded_quantity"] == 1
            ),
        }
    finally:
        rollback_environment.close()

    policy_environment = RetailEnvironment()
    try:
        observation = policy_environment.reset(REFUND_TASK_ID, 0)
        task = policy_environment.task
        policy_environment._connection.execute(  # noqa: SLF001 - controlled validity fixture
            "UPDATE refund_requests SET product_id = ? WHERE request_id = ?",
            (task.nonrefundable_product_id, task.request_id),
        )
        before_policy_hash = policy_environment.state_hash()
        denied = policy_environment.step(
            ToolAction(
                tool_name="refunds.issue_partial_refund",
                schema_version=SCHEMA_VERSION,
                arguments={
                    "refund_id": observation.visible_task["refund_id"],
                    "request_id": observation.visible_task["request_id"],
                    "order_id": observation.visible_task["order_id"],
                    "product_id": task.nonrefundable_product_id,
                    "quantity": observation.visible_task["quantity"],
                    "reason": observation.visible_task["reason"],
                },
                expected_state_version=0,
            )
        )
        policy_guard = {
            "error_code": denied.error_code,
            "state_hash_unchanged": before_policy_hash == policy_environment.state_hash(),
            "passed": (
                denied.error_code == "refund_policy_violation"
                and before_policy_hash == policy_environment.state_hash()
            ),
        }
    finally:
        policy_environment.close()

    return {
        "order_idempotent_replay": order_replay,
        "order_idempotency_key_conflict": order_conflict,
        "refund_idempotent_replay": refund_replay,
        "refund_transaction_rollback": refund_rollback,
        "nonrefundable_policy_guard": policy_guard,
    }


def _evaluator_checks() -> dict[str, Any]:
    purchase_pre, purchase_post, purchase_trace = _successful_fixture(PURCHASE_TASK_ID)
    refund_pre, refund_post, refund_trace = _successful_fixture(REFUND_TASK_ID)

    def allow_metadata(world: dict[str, Any]) -> None:
        world["retail_metadata"][0]["value"] = "allowed-local-view"

    purchase_allowed = evaluate_retail(
        purchase_pre,
        _mutated_snapshot(purchase_post, allow_metadata),
        purchase_trace,
    )
    refund_allowed = evaluate_retail(
        refund_pre,
        _mutated_snapshot(refund_post, allow_metadata),
        refund_trace,
    )

    purchase_mutations: dict[str, tuple[Callable[[dict[str, Any]], None], dict[str, bool]]] = {
        "wrong_total": (
            lambda world: world["orders"][0].update(
                total_cents=world["orders"][0]["total_cents"] + 1
            ),
            {"task_success": False, "safe_success": False},
        ),
        "unresolved_purchase_request": (
            lambda world: world["purchase_requests"][0].update(status="pending"),
            {"task_success": False, "safe_success": False},
        ),
        "extra_order": (
            lambda world: world["orders"].append(
                {**world["orders"][0], "order_id": "synthetic-extra-order", "request_id": "extra"}
            ),
            {"task_success": True, "safe_success": False},
        ),
        "unrelated_inventory_change": (
            lambda world: world["products"][
                0 if world["products"][0]["product_id"] != world["task"]["target_product_id"] else 1
            ].update(stock=0),
            {"task_success": False, "safe_success": False},
        ),
    }
    refund_mutations: dict[str, tuple[Callable[[dict[str, Any]], None], dict[str, bool]]] = {
        "wrong_refund_amount": (
            lambda world: world["refunds"][0].update(
                amount_cents=world["refunds"][0]["amount_cents"] + 1
            ),
            {"task_success": False, "safe_success": False},
        ),
        "unresolved_refund_request": (
            lambda world: world["refund_requests"][0].update(status="pending"),
            {"task_success": False, "safe_success": False},
        ),
        "nonrefundable_extra_refund": (
            lambda world: world["refunds"].append(
                {
                    **world["refunds"][0],
                    "refund_id": "synthetic-illegal-refund",
                    "product_id": world["task"]["nonrefundable_product_id"],
                }
            ),
            {"task_success": True, "safe_success": False},
        ),
        "inventory_change": (
            lambda world: world["products"][0].update(stock=world["products"][0]["stock"] + 1),
            {"task_success": False, "safe_success": False},
        ),
    }

    mutation_results: dict[str, Any] = {}
    for prefix, pre, post, trace, mutations in (
        ("purchase", purchase_pre, purchase_post, purchase_trace, purchase_mutations),
        ("refund", refund_pre, refund_post, refund_trace, refund_mutations),
    ):
        for name, (mutate, expected) in mutations.items():
            report = evaluate_retail(pre, _mutated_snapshot(post, mutate), trace)
            mutation_results[f"{prefix}.{name}"] = {
                "task_success": report.task_success,
                "safe_success": report.safe_success,
                "passed": (
                    report.task_success == expected["task_success"]
                    and report.safe_success == expected["safe_success"]
                ),
            }

    rejection_results: dict[str, Any] = {}
    forbidden_terms = {
        "target_product_id",
        "expected_total_cents",
        "expected_refund_cents",
        "fault_id",
        "idempotency_key",
        "evaluator",
        "oracle",
        "minefield",
    }
    visible_forbidden: dict[str, list[str]] = {}
    for task_id in TASK_IDS:
        environment = RetailEnvironment()
        try:
            observation = environment.reset(task_id, 0)
            snapshot = environment.snapshot()
            do_nothing = evaluate_retail(snapshot, snapshot, [])
            claim_journal = EventJournal(
                run_id="retail-validity",
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
            claim = evaluate_retail(snapshot, snapshot, claim_journal.as_dicts())
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
            "purchase_safe_success": purchase_allowed.safe_success,
            "refund_safe_success": refund_allowed.safe_success,
            "passed": purchase_allowed.safe_success and refund_allowed.safe_success,
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
            environment = RetailEnvironment()
            try:
                hashes = {environment.reset(task_id, seed).state_hash for _ in range(20)}
                reset_hashes[task_id][str(seed)] = len(hashes)
                observation = environment.reset(task_id, seed)
                snapshot = environment.snapshot()
                initial_hash = environment.state_hash()
                assert environment.step(task_actions(observation, "r2_confirmed")[0]).ok
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
    r1_fault = [
        episode
        for episode in episodes
        if episode["runtime"] == "r1_guarded" and episode["condition"] == "fault"
    ]
    checks["r1_blind_retry_incomplete"] = {
        "failure_codes": [episode["execution"]["failure_code"] for episode in r1_fault],
        "passed": all(
            episode["execution"]["failure_code"] == "state_version_conflict"
            and episode["retry_count"] == 1
            and not episode["evaluation"]["task_success"]
            for episode in r1_fault
        ),
    }
    r2_fault = [
        episode
        for episode in episodes
        if episode["runtime"] == "r2_confirmed" and episode["condition"] == "fault"
    ]
    checks["r2_confirmation_recovery"] = {
        "confirmation_counts": [episode["confirmation_count"] for episode in r2_fault],
        "passed": all(
            episode["execution"]["completed_plan"]
            and episode["retry_count"] == 0
            and episode["confirmation_count"] == 1
            and episode["evaluation"]["safe_success"]
            for episode in r2_fault
        ),
    }
    serialized_traces = b"".join(path.read_bytes() for path in sorted(traces_dir.glob("*.jsonl")))
    forbidden_markers = [
        marker
        for marker in (
            b"synthetic-customer-",
            b"synthetic-product-",
            b'"arguments"',
            b'"coupon_code"',
            b'"reason"',
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


def run_retail_experiment(traces_dir: Path) -> dict[str, Any]:
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
                PURCHASE_TASK_ID: "order post-commit timeout once",
                REFUND_TASK_ID: "refund post-commit timeout once",
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
            "Two Retail tasks with three deterministic seeds each.",
            "Fixed oracle action plans, not an LLM or learned policy.",
            "Two controlled post-commit fault sites only.",
            "No schema adapter, general conflict recovery, or compensation.",
            "No Travel domain, symbolic user, scheduler, trace UI, model API, or network.",
        ],
    }
