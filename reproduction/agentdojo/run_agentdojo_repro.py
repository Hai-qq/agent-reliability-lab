#!/usr/bin/env python3
"""Run a deterministic, utility-only AgentDojo evaluator reproduction.

The experiment uses AgentDojo's official synthetic ``workspace`` suite and
does not construct attacks, load injection tasks, call a model, or access the
network. It compares three fixed pipelines on two read-only tasks and one
state-changing task:

* ``oracle`` executes the task's official ground-truth tool calls;
* ``empty`` returns an empty answer and performs no tool calls;
* ``claim_only`` returns the task's public ground-truth answer without tools.

Only task IDs, aggregate booleans, tool-call counts, and environment hashes are
exported. Prompts, simulated records, tool outputs, and full traces are omitted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import tempfile
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentdojo.agent_pipeline import BasePipelineElement, GroundTruthPipeline
from agentdojo.benchmark import aggregate_results, benchmark_suite_without_injections
from agentdojo.functions_runtime import EmptyEnv, Env, FunctionsRuntime
from agentdojo.logging import OutputLogger
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import (
    ChatAssistantMessage,
    ChatMessage,
    text_content_block_from_string,
)

EXPECTED_AGENTDOJO_COMMIT = "089ed468cf3ed0322acc66b0211f26d9d90dbf60"
BENCHMARK_VERSION = "v1.2.2"
SUITE_NAME = "workspace"
TASK_KINDS = {
    "user_task_0": "read_only",
    "user_task_1": "read_only",
    "user_task_6": "state_change",
}
VARIANTS = ("oracle", "empty", "claim_only")


def git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def canonical_environment_hash(environment: Any) -> str:
    serialized = json.dumps(
        environment.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class FixedPipeline(BasePipelineElement):
    """A local pipeline with no model or external I/O."""

    def __init__(self, tasks: Sequence[Any], variant: str) -> None:
        if variant not in VARIANTS:
            raise ValueError(f"Unknown variant: {variant}")
        self._tasks_by_prompt = {task.PROMPT: task for task in tasks}
        self._variant = variant
        self.name = f"arl-agentdojo-{variant}"

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Env = EmptyEnv(),
        messages: Sequence[ChatMessage] = (),
        extra_args: dict[str, Any] | None = None,
    ) -> tuple[str, FunctionsRuntime, Env, Sequence[ChatMessage], dict[str, Any]]:
        task = self._tasks_by_prompt[query]
        forwarded_args = extra_args or {}
        if self._variant == "oracle":
            return GroundTruthPipeline(task).query(
                query,
                runtime,
                env,
                messages,
                forwarded_args,
            )

        output = task.GROUND_TRUTH_OUTPUT if self._variant == "claim_only" else ""
        response = ChatAssistantMessage(
            role="assistant",
            content=[text_content_block_from_string(output)],
            tool_calls=None,
        )
        return query, runtime, env, [*messages, response], forwarded_args


def default_logger_probe(suite: Any, tasks: Sequence[Any]) -> dict[str, Any]:
    """Capture the 0.1.35 helper behavior without changing upstream source."""
    pipeline = FixedPipeline(tasks, "empty")
    try:
        benchmark_suite_without_injections(
            pipeline,
            suite,
            logdir=None,
            force_rerun=True,
            user_tasks=("user_task_0",),
            benchmark_version=BENCHMARK_VERSION,
        )
    except AttributeError as error:
        return {
            "works": False,
            "error_type": type(error).__name__,
            "error": str(error),
        }
    return {"works": True, "error_type": None, "error": None}


def configured_logger_probe(suite: Any, tasks: Sequence[Any]) -> dict[str, Any]:
    """Exercise the official helper with the logger context used by its CLI."""
    pipeline = FixedPipeline(tasks, "empty")
    with tempfile.TemporaryDirectory(prefix="arl-agentdojo-") as temporary_logdir:
        with OutputLogger(temporary_logdir):
            result = benchmark_suite_without_injections(
                pipeline,
                suite,
                logdir=None,
                force_rerun=True,
                user_tasks=("user_task_0",),
                benchmark_version=BENCHMARK_VERSION,
            )
        utility = result["utility_results"][("user_task_0", "")]
        saved_logs = sorted(str(path.relative_to(temporary_logdir)) for path in Path(temporary_logdir).rglob("*.json"))
    return {
        "works": True,
        "utility": utility,
        "temporary_log_count": len(saved_logs),
        "temporary_logs_removed": True,
    }


def run_episode(
    suite: Any,
    tasks: Sequence[Any],
    task: Any,
    variant: str,
    repeat: int,
) -> dict[str, Any]:
    initial_environment = suite.load_and_inject_default_environment({})
    initial_hash = canonical_environment_hash(initial_environment)
    expected_tool_calls = len(task.ground_truth(initial_environment.model_copy(deep=True)))
    utility, framework_security = suite.run_task_with_pipeline(
        FixedPipeline(tasks, variant),
        task,
        injection_task=None,
        injections={},
    )
    return {
        "task_id": task.ID,
        "task_kind": TASK_KINDS[task.ID],
        "variant": variant,
        "repeat": repeat,
        "utility": utility,
        "framework_security_placeholder": framework_security,
        "expected_oracle_tool_call_count": expected_tool_calls,
        "initial_environment_sha256": initial_hash,
    }


def aggregate(episodes: Sequence[dict[str, Any]], repeats: int) -> list[dict[str, Any]]:
    aggregates: list[dict[str, Any]] = []
    for variant in VARIANTS:
        selected = [episode for episode in episodes if episode["variant"] == variant]
        utility_results = {(episode["task_id"], str(episode["repeat"])): episode["utility"] for episode in selected}
        task_pass_k = {
            task_id: all(episode["utility"] for episode in selected if episode["task_id"] == task_id)
            for task_id in TASK_KINDS
        }
        aggregates.append(
            {
                "variant": variant,
                "episode_count": len(selected),
                "utility_successes": sum(utility_results.values()),
                "utility_rate": aggregate_results([utility_results]),
                f"pass^{repeats}_tasks": sum(task_pass_k.values()),
                "task_count": len(task_pass_k),
                f"pass^{repeats}_rate": sum(task_pass_k.values()) / len(task_pass_k),
                "task_results": task_pass_k,
            }
        )
    return aggregates


def validate(
    episodes: Sequence[dict[str, Any]],
    aggregates: Sequence[dict[str, Any]],
    default_probe: dict[str, Any],
    configured_probe: dict[str, Any],
    repeats: int,
) -> None:
    assert len(episodes) == len(TASK_KINDS) * len(VARIANTS) * repeats
    assert len({episode["initial_environment_sha256"] for episode in episodes}) == 1
    assert all(episode["framework_security_placeholder"] for episode in episodes)

    by_variant = {item["variant"]: item for item in aggregates}
    assert by_variant["oracle"]["utility_successes"] == len(TASK_KINDS) * repeats
    assert by_variant["empty"]["utility_successes"] == 0
    assert by_variant["claim_only"]["utility_successes"] == 2 * repeats
    assert by_variant["claim_only"]["task_results"] == {
        "user_task_0": True,
        "user_task_1": True,
        "user_task_6": False,
    }

    assert default_probe == {
        "works": False,
        "error_type": "AttributeError",
        "error": "'NullLogger' object has no attribute 'logdir'",
    }
    assert configured_probe["works"] is True
    assert configured_probe["utility"] is False
    assert configured_probe["temporary_log_count"] == 1
    assert configured_probe["temporary_logs_removed"] is True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repeats", type=int, default=3)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.repeats < 1:
        raise SystemExit("--repeats must be at least 1")
    if not Path("src/agentdojo").is_dir():
        raise SystemExit("Run this script from the AgentDojo repository root.")

    commit = git_commit()
    if commit != EXPECTED_AGENTDOJO_COMMIT:
        raise SystemExit(f"AgentDojo commit mismatch: expected {EXPECTED_AGENTDOJO_COMMIT}, got {commit or 'unknown'}")

    suite = get_suite(BENCHMARK_VERSION, SUITE_NAME)
    tasks = [suite.get_user_task_by_id(task_id) for task_id in TASK_KINDS]
    default_probe = default_logger_probe(suite, tasks)
    configured_probe = configured_logger_probe(suite, tasks)

    episodes = [
        run_episode(suite, tasks, task, variant, repeat)
        for repeat in range(1, args.repeats + 1)
        for variant in VARIANTS
        for task in tasks
    ]
    aggregates = aggregate(episodes, args.repeats)
    validate(
        episodes,
        aggregates,
        default_probe,
        configured_probe,
        args.repeats,
    )

    result = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "agentdojo_version": importlib.metadata.version("agentdojo"),
            "agentdojo_commit": commit,
            "benchmark_version": BENCHMARK_VERSION,
            "suite": SUITE_NAME,
            "task_ids": list(TASK_KINDS),
            "variants": list(VARIANTS),
            "repeats": args.repeats,
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_injection_tasks": False,
            "generates_attack_material": False,
            "security_metric_applicable": False,
            "note": (
                "The framework returns security=True when injection_task=None; "
                "those placeholder values are retained per episode but are not "
                "reported as a security result."
            ),
        },
        "compatibility": {
            "default_null_logger": default_probe,
            "configured_output_logger": configured_probe,
            "workaround": (
                "Use the OutputLogger context employed by the official CLI, or call "
                "TaskSuite.run_task_with_pipeline directly for no-log evaluation."
            ),
        },
        "episodes": episodes,
        "aggregates": aggregates,
        "validation": {
            "all_assertions_passed": True,
            "initial_environment_hash_unique_count": len(
                {episode["initial_environment_sha256"] for episode in episodes}
            ),
            "repeat_results_deterministic": True,
            "raw_prompts_or_environment_records_exported": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
