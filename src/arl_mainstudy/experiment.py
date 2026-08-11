"""Cross-domain, no-model smoke experiment for the ARL main-study contract."""

from __future__ import annotations

import hashlib
import platform
from collections import defaultdict
from pathlib import Path
from typing import Any

from arl.core.types import digest_value
from arl.runtime.journal import EventJournal
from arl_mainstudy import __version__
from arl_mainstudy.adapters import SMOKE_ADAPTERS, SMOKE_TEMPLATE_IDS
from arl_mainstudy.agents import ScriptedAgent
from arl_mainstudy.catalog import catalog_audit
from arl_mainstudy.contract import CONDITIONS, RUNTIME_NAMES, default_contract
from arl_mainstudy.protocol import AgentFeedback
from arl_mainstudy.runtime import ActionRuntime

RUN_ID = "arl-main-study-scripted-smoke-v0.16.0"
SMOKE_ENVIRONMENT_SEED = 0


def _episode_id(template_id: str, runtime_name: str, condition: str) -> str:
    return f"main-smoke-{template_id}-{runtime_name}-{condition}"


def run_episode(
    *,
    template_id: str,
    runtime_name: str,
    condition: str,
    seed: int = SMOKE_ENVIRONMENT_SEED,
    trace_path: Path | None,
) -> dict[str, Any]:
    try:
        adapter = SMOKE_ADAPTERS[template_id]
    except KeyError as error:
        raise ValueError(f"Unknown smoke template: {template_id}") from error
    episode_id = _episode_id(template_id, runtime_name, condition)
    environment = adapter.create_environment(condition)
    try:
        observation = environment.reset(adapter.task_id, seed)
        initial_snapshot = environment.snapshot()
        initial_hash = environment.state_hash()
        journal = EventJournal(
            run_id=RUN_ID,
            episode_id=episode_id,
            task_id=adapter.task_id,
            seed=seed,
            path=trace_path,
        )
        contract = default_contract()
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="harness",
            event_type="episode_started",
            state_hash_before=initial_hash,
            state_hash_after=initial_hash,
            input_digest=digest_value(
                {
                    "contract_sha256": contract.sha256,
                    "template_id": template_id,
                    "runtime": runtime_name,
                    "condition": condition,
                    "observation": observation.as_dict(),
                }
            ),
        )
        agent = ScriptedAgent(adapter.semantic_actions(observation))
        agent.reset(observation)
        journal.append(
            timestamp_logical=environment.logical_time,
            actor="agent",
            event_type="policy_initialized",
            state_hash_before=initial_hash,
            state_hash_after=initial_hash,
            input_digest=agent.policy_digest,
        )
        runtime = ActionRuntime(runtime_name, adapter.runtime_hooks())
        feedback: AgentFeedback | None = None
        action_reports: list[dict[str, Any]] = []
        failure_code: str | None = None
        action_ordinal = 0

        while action_ordinal < 32:
            semantic_action = agent.next_action(feedback)
            if semantic_action is None:
                break
            action_ordinal += 1
            state_hash = environment.state_hash()
            journal.append(
                timestamp_logical=environment.logical_time,
                actor="agent",
                event_type="agent_action_selected",
                state_hash_before=state_hash,
                state_hash_after=state_hash,
                input_digest=digest_value(semantic_action.as_dict()),
                tool_name=semantic_action.tool_name,
                schema_version=semantic_action.schema_version,
            )
            report, feedback = runtime.execute(
                environment,
                semantic_action,
                journal,
                episode_key=episode_id,
                action_ordinal=action_ordinal,
            )
            action_reports.append(report.as_dict())
            if not feedback.accepted:
                failure_code = feedback.error_code
                break
        else:  # pragma: no cover - current plans contain at most four actions
            failure_code = "agent_step_budget_exhausted"

        completed_plan = failure_code is None and action_ordinal == agent.action_count
        evaluation = adapter.evaluate(
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
        observed_fault_ids = sorted(
            {event.fault_id for event in journal.events if event.fault_id is not None}
        )
        return {
            "episode_id": episode_id,
            "template_id": template_id,
            "task_id": adapter.task_id,
            "domain": adapter.domain,
            "environment_seed": seed,
            "runtime": runtime_name,
            "condition": condition,
            "fault_family": adapter.blueprint.main_fault_family,
            "expected_fault_id": adapter.expected_fault_id
            if condition == "recoverable_fault"
            else None,
            "observed_fault_ids": observed_fault_ids,
            "policy": {
                "policy_id": agent.policy_id,
                "policy_sha256": agent.policy_digest,
                "planned_action_count": agent.action_count,
                "emitted_action_count": action_ordinal,
                "model_calls": agent.model_calls,
            },
            "execution": {
                "completed_plan": completed_plan,
                "failure_code": failure_code,
                "tool_attempts": sum(item["tool_attempts"] for item in action_reports),
                "retry_count": sum(item["retry_count"] for item in action_reports),
                "confirmation_count": sum(item["confirmation_count"] for item in action_reports),
                "result_contract_violations": sum(
                    item["result_contract_violations"] for item in action_reports
                ),
                "actions": action_reports,
            },
            "evaluation": evaluation.as_dict(),
            "initial_state_hash": initial_hash,
            "final_state_hash": final_hash,
            "trace_file": trace_path.name if trace_path is not None else None,
            "trace_sha256": hashlib.sha256(journal.jsonl_bytes()).hexdigest(),
            "trace_event_count": len(journal.events),
            "external_network_calls": 0,
        }
    finally:
        environment.close()


def _aggregate(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    by_runtime: dict[str, dict[str, Any]] = {}
    for runtime_name in RUNTIME_NAMES:
        by_condition: dict[str, Any] = {}
        for condition in CONDITIONS:
            selected = [
                item
                for item in episodes
                if item["runtime"] == runtime_name and item["condition"] == condition
            ]
            by_condition[condition] = {
                "episodes": len(selected),
                "task_successes": sum(item["evaluation"]["task_success"] for item in selected),
                "safe_successes": sum(item["evaluation"]["safe_success"] for item in selected),
                "completed_plans": sum(item["execution"]["completed_plan"] for item in selected),
                "tool_attempts": sum(item["execution"]["tool_attempts"] for item in selected),
                "retry_count": sum(item["execution"]["retry_count"] for item in selected),
                "confirmation_count": sum(
                    item["execution"]["confirmation_count"] for item in selected
                ),
            }
        clean_success = {
            item["template_id"]
            for item in episodes
            if item["runtime"] == runtime_name
            and item["condition"] == "clean"
            and item["evaluation"]["safe_success"]
        }
        recovered = {
            item["template_id"]
            for item in episodes
            if item["runtime"] == runtime_name
            and item["condition"] == "recoverable_fault"
            and item["evaluation"]["safe_success"]
            and item["template_id"] in clean_success
        }
        by_runtime[runtime_name] = {
            "by_condition": by_condition,
            "matched_clean_capable_tasks": len(clean_success),
            "recovered_fault_tasks": len(recovered),
            "recovery_rate": len(recovered) / len(clean_success) if clean_success else None,
        }
    return {
        "episode_count": len(episodes),
        "template_count": len({item["template_id"] for item in episodes}),
        "runtime_count": len({item["runtime"] for item in episodes}),
        "condition_count": len({item["condition"] for item in episodes}),
        "model_calls": sum(item["policy"]["model_calls"] for item in episodes),
        "external_network_calls": sum(item["external_network_calls"] for item in episodes),
        "by_runtime": by_runtime,
        "fault_recovery_rate_delta_r2_minus_r1": (
            by_runtime["r2_reliable"]["recovery_rate"] - by_runtime["r1_guarded"]["recovery_rate"]
        ),
    }


def _trace_payload_audit(traces_dir: Path) -> dict[str, Any]:
    forbidden = (
        b'"arguments"',
        b'"visible_task"',
        b"@synthetic.invalid",
        b"synthetic-event",
        b"synthetic-order",
    )
    files = sorted(traces_dir.glob("*.jsonl"))
    findings: dict[str, list[str]] = {}
    for path in files:
        payload = path.read_bytes().lower()
        matches = [marker.decode("utf-8") for marker in forbidden if marker.lower() in payload]
        if matches:
            findings[path.name] = matches
    return {
        "trace_count": len(files),
        "forbidden_payload_findings": findings,
        "passed": len(files) == 12 and not findings,
    }


def _validity(
    episodes: list[dict[str, Any]],
    traces_dir: Path,
    contract_sha256: str,
) -> dict[str, Any]:
    matrix = {(item["template_id"], item["runtime"], item["condition"]) for item in episodes}
    expected_matrix = {
        (template_id, runtime_name, condition)
        for template_id in SMOKE_TEMPLATE_IDS
        for runtime_name in RUNTIME_NAMES
        for condition in CONDITIONS
    }
    policy_digests: dict[str, set[str]] = defaultdict(set)
    reset_hashes: dict[str, set[str]] = defaultdict(set)
    for item in episodes:
        policy_digests[item["template_id"]].add(item["policy"]["policy_sha256"])
        reset_hashes[item["template_id"]].add(item["initial_state_hash"])

    expected_outcomes = all(
        item["evaluation"]["safe_success"]
        == (item["condition"] == "clean" or item["runtime"] == "r2_reliable")
        for item in episodes
    )
    fault_isolation = all(
        (
            not item["observed_fault_ids"]
            if item["condition"] == "clean"
            else item["observed_fault_ids"] == [item["expected_fault_id"]]
        )
        for item in episodes
    )
    r2_fault = [
        item
        for item in episodes
        if item["runtime"] == "r2_reliable" and item["condition"] == "recoverable_fault"
    ]
    r1_fault = [
        item
        for item in episodes
        if item["runtime"] == "r1_guarded" and item["condition"] == "recoverable_fault"
    ]
    r0_fault = [
        item
        for item in episodes
        if item["runtime"] == "r0_raw" and item["condition"] == "recoverable_fault"
    ]
    contract = default_contract()
    contract.assert_ready("scripted_smoke")
    main_fail_closed = False
    try:
        contract.assert_ready("main")
    except RuntimeError:
        main_fail_closed = True

    checks = {
        "contract_digest_matches": contract.sha256 == contract_sha256,
        "exact_twelve_episode_matrix": len(episodes) == 12 and matrix == expected_matrix,
        "same_semantic_policy_across_conditions_and_runtimes": all(
            len(values) == 1 for values in policy_digests.values()
        ),
        "clean_fault_reset_hash_match": all(len(values) == 1 for values in reset_hashes.values()),
        "expected_clean_and_fault_outcomes": expected_outcomes,
        "single_registered_fault_difference": fault_isolation,
        "r0_has_no_retries": all(item["execution"]["retry_count"] == 0 for item in r0_fault),
        "r1_blind_retry_does_not_claim_recovery": all(
            item["execution"]["retry_count"] == 1 and not item["evaluation"]["safe_success"]
            for item in r1_fault
        ),
        "r2_confirms_each_ambiguous_commit": all(
            item["execution"]["confirmation_count"] == 1 and item["evaluation"]["safe_success"]
            for item in r2_fault
        ),
        "zero_model_and_network_calls": all(
            item["policy"]["model_calls"] == 0 and item["external_network_calls"] == 0
            for item in episodes
        ),
        "model_stages_fail_closed_until_bound": main_fail_closed,
    }
    catalog = catalog_audit()
    trace_payloads = _trace_payload_audit(traces_dir)
    checks["catalog_blueprint_balanced"] = catalog["passed"]
    checks["digest_only_traces"] = trace_payloads["passed"]
    return {
        "checks": checks,
        "all_selected_checks_passed": all(checks.values()),
        "policy_digests": {
            template_id: sorted(values) for template_id, values in sorted(policy_digests.items())
        },
        "reset_hashes": {
            template_id: sorted(values) for template_id, values in sorted(reset_hashes.items())
        },
        "catalog": catalog,
        "trace_payloads": trace_payloads,
    }


def run_scripted_smoke(traces_dir: Path, project_root: Path) -> dict[str, Any]:
    """Run the 12-episode, no-model gate and refuse to reuse an evidence directory."""

    if traces_dir.exists():
        raise FileExistsError(f"Refusing to reuse traces directory: {traces_dir}")
    traces_dir.mkdir(parents=True)
    contract = default_contract()
    contract.assert_ready("scripted_smoke")
    episodes = [
        run_episode(
            template_id=template_id,
            runtime_name=runtime_name,
            condition=condition,
            trace_path=traces_dir / f"{_episode_id(template_id, runtime_name, condition)}.jsonl",
        )
        for template_id in SMOKE_TEMPLATE_IDS
        for runtime_name in RUNTIME_NAMES
        for condition in CONDITIONS
    ]
    aggregate = _aggregate(episodes)
    validity = _validity(episodes, traces_dir, contract.sha256)
    if aggregate["episode_count"] != contract.stage("scripted_smoke").episode_count:
        raise AssertionError("Smoke execution count drifted from the frozen contract")
    if not validity["all_selected_checks_passed"]:
        raise AssertionError("Main-study smoke validity failed")
    return {
        "metadata": {
            "run_id": RUN_ID,
            "package_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.system().lower(),
            "project_root_name": project_root.name,
            "environment_seed": SMOKE_ENVIRONMENT_SEED,
            "policy": "scripted semantic plan",
            "result_scope": "offline harness gate; not a model benchmark result",
        },
        "contract": {**contract.as_dict(), "sha256": contract.sha256},
        "aggregate": aggregate,
        "validity": validity,
        "episodes": episodes,
        "limitations": [
            "Only two existing task templates are executable in this smoke gate.",
            "The remaining 18 catalog entries are explicit planned blueprints, not runnable tasks.",
            (
                "The scripted policy makes zero model calls and cannot support a "
                "model-performance claim."
            ),
            (
                "Only post-commit response loss is exercised; the other five fault families "
                "remain pending."
            ),
        ],
    }
