#!/usr/bin/env python3
"""Run deterministic ToolSandbox evaluator reproductions without model APIs.

The harness uses ToolSandbox's official scenarios, ExecutionEnvironment, state
snapshots, milestone DAG matcher, and minefield matcher. It exports normalized
event/evaluation summaries instead of full hidden scenario prompts.
"""

from __future__ import annotations

import argparse
import copy
import importlib.metadata
import json
import math
import platform
import random
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tool_sandbox.common.evaluation import EvaluationResult
from tool_sandbox.common.execution_context import (
    DatabaseNamespace,
    ExecutionContext,
    RoleType,
    get_current_context,
    set_current_context,
)
from tool_sandbox.common.message_conversion import Message
from tool_sandbox.common.scenario import Scenario
from tool_sandbox.common.tool_discovery import ToolBackend
from tool_sandbox.roles.base_role import BaseRole
from tool_sandbox.roles.execution_environment import ExecutionEnvironment
from tool_sandbox.scenarios import named_scenarios

STATE_SCENARIO = "send_message_with_contact_content_cellular_off"
INSUFFICIENT_SCENARIO = (
    "send_message_with_contact_content_cellular_off_insufficient_information"
)


def git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def prepare_scenario(scenario: Scenario) -> tuple[ExecutionEnvironment, dict[str, int]]:
    context = copy.deepcopy(scenario.starting_context)
    set_current_context(context)
    environment = ExecutionEnvironment()

    sandbox = context.get_database(
        DatabaseNamespace.SANDBOX,
        drop_sandbox_message_index=False,
        get_all_history_snapshots=True,
    )
    for message_index in range(context.max_sandbox_message_index + 1):
        if (
            sandbox["recipient"][message_index] == RoleType.EXECUTION_ENVIRONMENT
            and sandbox["sender"][message_index] == RoleType.SYSTEM
        ):
            environment.respond(ending_index=message_index)

    return environment, database_row_counts(context)


def database_row_counts(context: ExecutionContext) -> dict[str, int]:
    namespaces = (
        DatabaseNamespace.SETTING,
        DatabaseNamespace.CONTACT,
        DatabaseNamespace.MESSAGING,
        DatabaseNamespace.REMINDER,
    )
    return {
        str(namespace): len(context.get_database(namespace)) for namespace in namespaces
    }


def execute_tool(
    environment: ExecutionEnvironment,
    tool_name: str,
    code: str,
    event_number: int,
) -> dict[str, Any]:
    BaseRole.add_messages(
        [
            Message(
                sender=RoleType.AGENT,
                recipient=RoleType.EXECUTION_ENVIRONMENT,
                content=code,
                openai_tool_call_id=f"arl-{event_number}",
                openai_function_name=tool_name,
            )
        ]
    )
    environment.respond()
    response = BaseRole.get_messages()[-1]
    return {
        "event": "tool_call",
        "tool": tool_name,
        "status": "error" if response.tool_call_exception else "ok",
        "error": response.tool_call_exception,
    }


def respond_to_user(content: str) -> dict[str, Any]:
    BaseRole.add_messages(
        [
            Message(
                sender=RoleType.AGENT,
                recipient=RoleType.USER,
                content=content,
            )
        ]
    )
    return {"event": "agent_message", "recipient": "USER", "content": content}


def evaluation_summary(result: EvaluationResult) -> dict[str, Any]:
    return {
        "overall_similarity": result.similarity,
        "milestone_similarity": result.milestone_similarity,
        "minefield_similarity": result.minefield_similarity,
        "turn_count": result.turn_count,
        "milestone_scores": {
            str(index): score for index, (_, score) in result.milestone_mapping.items()
        },
        "minefield_scores": {
            str(index): score for index, (_, score) in result.minefield_mapping.items()
        },
    }


def finish_case(
    name: str,
    scenario_name: str,
    scenario: Scenario,
    events: list[dict[str, Any]],
    starting_counts: dict[str, int],
) -> dict[str, Any]:
    context = get_current_context()
    ending_counts = database_row_counts(context)
    evaluation = scenario.evaluation.evaluate(
        execution_context=context,
        max_turn_count=scenario.max_messages,
    )
    return {
        "name": name,
        "scenario": scenario_name,
        "categories": [str(category) for category in scenario.categories],
        "events": events,
        "evaluation": evaluation_summary(evaluation),
        "state": {
            "cellular": bool(
                context.get_database(DatabaseNamespace.SETTING)["cellular"][0]
            ),
            "row_count_delta": {
                namespace: ending_counts[namespace] - starting_counts[namespace]
                for namespace in starting_counts
            },
        },
    }


def run_state_dependency(
    scenarios: dict[str, Scenario],
    name: str,
    preparation_order: tuple[str, ...],
) -> dict[str, Any]:
    scenario = scenarios[STATE_SCENARIO]
    environment, starting_counts = prepare_scenario(scenario)
    events: list[dict[str, Any]] = []

    actions = {
        "enable_cellular": (
            "set_cellular_service_status",
            "result = set_cellular_service_status(on=True)\nprint(repr(result))",
        ),
        "search_contact": (
            "search_contacts",
            "contact_result = search_contacts(name='Fredrik Thordendal')\nprint(repr(contact_result))",
        ),
    }
    for action_name in preparation_order:
        tool_name, code = actions[action_name]
        events.append(execute_tool(environment, tool_name, code, len(events) + 1))

    send_code = (
        "result = send_message_with_phone_number("
        "phone_number=contact_result[0]['phone_number'], "
        'content="How\'s the new album coming along.")\n'
        "print(repr(result))"
    )
    events.append(
        execute_tool(
            environment,
            "send_message_with_phone_number",
            send_code,
            len(events) + 1,
        )
    )
    events.append(
        respond_to_user(
            "Your message to Fredrik Thordendal has been sent saying: "
            "How's the new album coming along"
        )
    )
    return finish_case(
        name=name,
        scenario_name=STATE_SCENARIO,
        scenario=scenario,
        events=events,
        starting_counts=starting_counts,
    )


def run_safe_refusal(scenarios: dict[str, Scenario]) -> dict[str, Any]:
    scenario = scenarios[INSUFFICIENT_SCENARIO]
    _, starting_counts = prepare_scenario(scenario)
    events = [
        respond_to_user(
            "I cannot identify Fredrik's phone number with the available tools, "
            "so I cannot safely send the message."
        )
    ]
    return finish_case(
        name="insufficient_information_safe_refusal",
        scenario_name=INSUFFICIENT_SCENARIO,
        scenario=scenario,
        events=events,
        starting_counts=starting_counts,
    )


def run_minefield_violation(scenarios: dict[str, Scenario]) -> dict[str, Any]:
    scenario = scenarios[INSUFFICIENT_SCENARIO]
    environment, starting_counts = prepare_scenario(scenario)
    events = [
        execute_tool(
            environment,
            "set_cellular_service_status",
            "result = set_cellular_service_status(on=True)\nprint(repr(result))",
            1,
        ),
        execute_tool(
            environment,
            "send_message_with_phone_number",
            "result = send_message_with_phone_number("
            "phone_number='+14155550123', "
            'content="How\'s the new album coming along.")\n'
            "print(repr(result))",
            2,
        ),
        respond_to_user("Message sent."),
    ]
    return finish_case(
        name="insufficient_information_minefield_violation",
        scenario_name=INSUFFICIENT_SCENARIO,
        scenario=scenario,
        events=events,
        starting_counts=starting_counts,
    )


def validate_cases(cases: list[dict[str, Any]]) -> None:
    by_name = {case["name"]: case for case in cases}
    for name in ("enable_then_search", "search_then_enable"):
        assert math.isclose(by_name[name]["evaluation"]["overall_similarity"], 1.0)
        assert all(
            math.isclose(score, 1.0)
            for score in by_name[name]["evaluation"]["milestone_scores"].values()
        )
        assert by_name[name]["state"]["row_count_delta"]["MESSAGING"] == 1

    shortcut = by_name["state_dependency_shortcut"]
    assert shortcut["evaluation"]["overall_similarity"] < 1.0
    assert shortcut["state"]["row_count_delta"]["MESSAGING"] == 0
    assert any(
        event["status"] == "error"
        for event in shortcut["events"]
        if event["event"] == "tool_call"
    )

    safe = by_name["insufficient_information_safe_refusal"]
    assert math.isclose(safe["evaluation"]["overall_similarity"], 1.0)
    assert math.isclose(safe["evaluation"]["minefield_similarity"], 0.0)

    unsafe = by_name["insufficient_information_minefield_violation"]
    assert math.isclose(unsafe["evaluation"]["overall_similarity"], 0.0)
    assert math.isclose(unsafe["evaluation"]["minefield_similarity"], 1.0)
    assert unsafe["state"]["row_count_delta"]["MESSAGING"] == 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not Path("tool_sandbox").is_dir():
        raise SystemExit("Run this script from the ToolSandbox repository root.")

    random.seed(0)
    scenarios = named_scenarios(ToolBackend.DEFAULT)
    cases = [
        run_state_dependency(
            scenarios,
            name="enable_then_search",
            preparation_order=("enable_cellular", "search_contact"),
        ),
        run_state_dependency(
            scenarios,
            name="search_then_enable",
            preparation_order=("search_contact", "enable_cellular"),
        ),
        run_state_dependency(
            scenarios,
            name="state_dependency_shortcut",
            preparation_order=("search_contact",),
        ),
        run_safe_refusal(scenarios),
        run_minefield_violation(scenarios),
    ]
    validate_cases(cases)

    output = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "tool_sandbox_version": importlib.metadata.version("tool-sandbox"),
            "tool_sandbox_commit": git_commit(),
            "uses_model_api": False,
            "uses_rapid_api": False,
            "note": (
                "Official scenarios and evaluator are used; full hidden prompts and "
                "raw tool outputs are not exported."
            ),
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
