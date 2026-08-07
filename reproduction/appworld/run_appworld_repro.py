#!/usr/bin/env python3
"""Run a small, evaluator-focused AppWorld reproduction.

This script deliberately does not expose or copy AppWorld's private ground-truth
implementation. It executes the official oracle inside an installed AppWorld
checkout and exports only aggregate pass/fail counts and state-diff counts.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from appworld.collections.models import ModelCollectionPair
from appworld.environment import AppWorld
from appworld.task import Task


DEFAULT_TASK_IDS = [
    "6c2c621_2",  # Simple Note -> file system export.
    "530b157_1",  # Phone evidence -> Venmo payment -> phone confirmation.
    "37a8675_1",  # Phone identity lookup -> Venmo transfer.
    "4fab96f_2",  # Identify stale payment requests -> send reminders.
    "383cbac_1",  # Read-only cross-app numerical answer.
]

VARIANTS = ("oracle", "no_op", "collateral_add", "collateral_delete")


def git_commit() -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def tracker_summary(tracker: Any) -> dict[str, Any]:
    data = tracker.to_dict(stats_only=False)
    failure_labels = Counter(item.get("label") or "unlabeled" for item in data["failures"])
    pass_labels = Counter(item.get("label") or "unlabeled" for item in data["passes"])
    return {
        "success": data["success"],
        "difficulty": data["difficulty"],
        "num_tests": data["num_tests"],
        "pass_count": len(data["passes"]),
        "fail_count": len(data["failures"]),
        "pass_labels": dict(sorted(pass_labels.items())),
        "failure_labels": dict(sorted(failure_labels.items())),
    }


def state_diff_summary(world: AppWorld) -> dict[str, dict[str, int]]:
    if world.models is None:
        raise RuntimeError("AppWorld end-state models are unavailable.")
    start_models = world.task.model_collection
    end_models = world.models
    pair = ModelCollectionPair(
        start_db_home_path=start_models.from_db_home_path,
        start_model_collection=start_models,
        end_db_home_path=world.models_to_db_home_path,
        end_model_collection=end_models,
    )
    changed_models = sorted(pair.changed_model_names())
    summary: dict[str, dict[str, int]] = {}
    for model_name in changed_models:
        added, updated, removed = pair.changed_records(model_name)
        summary[model_name] = {
            "added": len(added),
            "updated": len(updated),
            "removed": len(removed),
        }
    return summary


def execute_official_oracle(world: AppWorld) -> None:
    ground_truth = world.task.ground_truth
    if ground_truth is None or not ground_truth.compiled_solution_code:
        raise RuntimeError(f"Full oracle is unavailable for task {world.task_id}.")
    code = ground_truth.compiled_solution_code + "\nsolution(apis, requester)"
    output = world.execute(code)
    if "Execution failed." in output:
        raise RuntimeError(f"Official oracle execution failed for {world.task_id}.")


def execute_no_op(world: AppWorld) -> None:
    output = world.execute("apis.supervisor.complete_task(status='success')")
    if "Execution failed." in output:
        raise RuntimeError(f"No-op completion failed to execute for {world.task_id}.")


def simple_note_access_token(world: AppWorld) -> str:
    """Log in to the benchmark's simulated Simple Note account."""
    supervisor = world.apis.supervisor.show_profile()
    passwords = {
        item["account_name"]: item["password"]
        for item in world.apis.supervisor.show_account_passwords()
    }
    response = world.apis.simple_note.login(
        username=supervisor["email"],
        password=passwords["simple_note"],
    )
    if not isinstance(response, dict) or "access_token" not in response:
        raise RuntimeError(f"Simple Note login failed for {world.task_id}.")
    return response["access_token"]


def add_unrelated_note(world: AppWorld) -> None:
    """Persist an unrelated record before task completion.

    AppWorld rejects later API calls after the oracle calls ``complete_task``.
    Injecting this mutation first makes it a real side effect and lets us test
    whether the evaluator notices unrelated cross-app changes.
    """
    token = simple_note_access_token(world)
    response = world.apis.simple_note.create_note(
        title=f"ARL unrelated mutation {world.task_id}",
        content="This mutation is intentionally unrelated to the requested task.",
        access_token=token,
    )
    if not isinstance(response, dict) or "note_id" not in response:
        raise RuntimeError(
            f"Unrelated Simple Note mutation was not persisted for {world.task_id}."
        )

    changed_models = state_diff_summary(world)
    note_diff = changed_models.get("simple_note.Note")
    if note_diff is None or note_diff["added"] < 1:
        raise RuntimeError(
            f"Unrelated Simple Note mutation is absent from the state diff for {world.task_id}."
        )


def delete_unrelated_note(world: AppWorld) -> None:
    """Delete one pre-existing unrelated record before task completion."""
    token = simple_note_access_token(world)
    notes = world.apis.simple_note.search_notes(page_limit=1, access_token=token)
    if not isinstance(notes, list) or not notes:
        raise RuntimeError(f"No Simple Note record is available to delete for {world.task_id}.")
    response = world.apis.simple_note.delete_note(
        note_id=notes[0]["note_id"],
        access_token=token,
    )
    if not isinstance(response, dict) or response.get("message") != "Note deleted.":
        raise RuntimeError(f"Unrelated Simple Note deletion failed for {world.task_id}.")

    changed_models = state_diff_summary(world)
    note_diff = changed_models.get("simple_note.Note")
    if note_diff is None or note_diff["removed"] < 1:
        raise RuntimeError(
            f"Unrelated Simple Note deletion is absent from the state diff for {world.task_id}."
        )


def run_variant(task_id: str, variant: str) -> dict[str, Any]:
    experiment_name = f"arl_appworld_repro_v2_{variant}"
    with AppWorld(
        task_id=task_id,
        experiment_name=experiment_name,
        ground_truth_mode="full",
        raise_on_failure=False,
    ) as world:
        if variant == "oracle":
            execute_official_oracle(world)
        elif variant == "no_op":
            execute_no_op(world)
        elif variant == "collateral_add":
            add_unrelated_note(world)
            execute_official_oracle(world)
        elif variant == "collateral_delete":
            delete_unrelated_note(world)
            execute_official_oracle(world)
        else:
            raise ValueError(f"Unknown variant: {variant}")

        tracker = world.evaluate()
        diff = state_diff_summary(world)
        return {
            "evaluation": tracker_summary(tracker),
            "changed_models": diff,
        }


def task_metadata(task_id: str) -> dict[str, Any]:
    task = Task.load(task_id, load_ground_truth=True, ground_truth_mode="full")
    if task.ground_truth is None:
        raise RuntimeError(f"Ground truth unavailable for {task_id}.")
    ground_truth = task.ground_truth
    return {
        "task_id": task_id,
        "instruction": task.instruction,
        "difficulty": ground_truth.metadata["difficulty"],
        "required_apps": sorted(ground_truth.required_apps),
        "num_api_calls_in_oracle": ground_truth.metadata.get("num_api_calls"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-id", action="append", dest="task_ids")
    parser.add_argument(
        "--variant",
        action="append",
        dest="variants",
        choices=VARIANTS,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    task_ids = args.task_ids or DEFAULT_TASK_IDS
    variants = args.variants or list(VARIANTS)

    if not Path("data/tasks").is_dir():
        raise SystemExit("Run this script from an installed AppWorld repository root.")

    result: dict[str, Any] = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "appworld_version": importlib.metadata.version("appworld"),
            "appworld_commit": git_commit(),
            "variants": variants,
            "note": (
                "Only aggregate evaluator and state-diff counts are exported; "
                "private oracle/evaluator source is not included."
            ),
        },
        "tasks": [],
    }

    for task_id in task_ids:
        item = task_metadata(task_id)
        item["variants"] = {}
        for variant in variants:
            item["variants"][variant] = run_variant(task_id, variant)
        result["tasks"].append(item)
        AppWorld.close_all()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
