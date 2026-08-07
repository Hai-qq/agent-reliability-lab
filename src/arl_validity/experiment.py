"""Aggregate the independent ARL v0.4 validity-gate experiment."""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any

from arl_multitask.env import ENV_VERSION, TASK_IDS
from arl_validity import __version__
from arl_validity.baselines import run_dump_state_baseline, run_random_valid_tool_baseline
from arl_validity.golden import verify_golden_suite


def run_workspace_validity_experiment(project_root: Path) -> dict[str, Any]:
    first_random = run_random_valid_tool_baseline()
    second_random = run_random_valid_tool_baseline()
    random_repeat_deterministic = first_random == second_random
    first_random["repeat_deterministic"] = random_repeat_deterministic
    first_random["passed"] = first_random["passed"] and random_repeat_deterministic

    dump_state = run_dump_state_baseline()
    golden = verify_golden_suite(
        project_root,
        project_root / "tests/golden/workspace_multitask_v03.json",
    )
    validity = {
        "random_valid_tool": first_random,
        "dump_state": dump_state,
        "golden_trace": golden,
    }
    validity["all_selected_checks_passed"] = all(check["passed"] for check in validity.values())
    assert validity["all_selected_checks_passed"]
    return {
        "metadata": {
            "increment_version": __version__,
            "root_project_version": "0.3.0",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "environment_version": ENV_VERSION,
            "task_ids": list(TASK_IDS),
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "artifact_payload_policy": "digests and typed metadata only",
        },
        "validity": validity,
        "limitations": [
            "One Workspace domain with two fixed task templates.",
            "Random-valid-tool is a deterministic open-loop baseline, not a model agent.",
            "Dump-state is a local evaluator probe; full snapshot content is never exported.",
            "Golden traces cover four selected v0.3 R2 traces, not every historical trace.",
            "No model, API, external network, scheduler, viewer, Retail, or Travel domain.",
        ],
    }
