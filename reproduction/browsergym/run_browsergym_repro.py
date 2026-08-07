#!/usr/bin/env python3
"""Run a deterministic, offline BrowserGym/MiniWoB harness reproduction.

The harness exercises BrowserGym's real reset/step/evaluator path against
official MiniWoB++ files. It does not call a model or open an HTTP(S) target.
The browser context is forced offline and service workers are blocked.

Three tasks are run over three fixed seeds. One job first executes a benign,
short-timeout locator miss and then recovers in the same environment. A JSON
state file is updated after every completed job so an intentional interruption
can be resumed without rerunning completed jobs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import gymnasium as gym

import browsergym.miniwob  # noqa: F401  # register environments

EXPECTED_BROWSERGYM_COMMIT = "9e779f087de9a65668b6974d11f9ce9816026e96"
EXPECTED_MINIWOB_COMMIT = "7fd85d71a4b60325c6585396ec4f48377d049838"
EXPECTED_VERSIONS = {
    "browsergym-core": "0.14.3",
    "browsergym-miniwob": "0.14.3",
    "gymnasium": "1.3.0",
    "playwright": "1.44.0",
}
EXPECTED_BROWSER_REVISION = "1117"
TASKS = ("click-scroll-list", "click-menu-2", "use-colorwheel-2")
SEEDS = (0, 1, 2)
RECOVERY_JOB_ID = "click-scroll-list::seed-0"
STATE_SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--miniwob-repo", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--stop-after",
        type=int,
        help="Intentionally stop once this many total jobs are complete.",
    )
    return parser.parse_args()


def git_commit(repo: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def count_tree_nodes(value: Any) -> int:
    if isinstance(value, dict):
        return 1 + sum(count_tree_nodes(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return 1 + sum(count_tree_nodes(item) for item in value)
    return 1


def step_record(
    ordinal: int,
    action_kind: str,
    observation: dict[str, Any],
    reward: float,
    terminated: bool,
    truncated: bool,
) -> dict[str, Any]:
    error = observation["last_action_error"]
    return {
        "ordinal": ordinal,
        "action_kind": action_kind,
        "reward": float(reward),
        "terminated": bool(terminated),
        "truncated": bool(truncated),
        "has_error": bool(error),
        "error_type": error.split(":", 1)[0] if error else None,
    }


def actions_for(task: str, goal: str) -> list[tuple[str, str]]:
    if task == "click-scroll-list":
        match = re.fullmatch(
            r"Select (.+) from the scroll list and click Submit\.",
            goal,
        )
        if not match:
            raise ValueError("Unexpected click-scroll-list goal shape")
        options = match.group(1).split(", ")
        return [
            (
                "select_options_and_submit",
                f'page.locator("#options").select_option({options!r})\n'
                'page.get_by_role("button", name="Submit").click()',
            )
        ]

    if task == "use-colorwheel-2":
        match = re.fullmatch(
            r"Select the following color #(.+) with the color picker and hit Submit\.",
            goal,
        )
        if not match:
            raise ValueError("Unexpected use-colorwheel-2 goal shape")
        color = match.group(1).upper()
        return [
            (
                "fill_color_and_submit",
                f'page.locator("#col").fill("{color}")\n'
                'page.get_by_role("button", name="Submit").click()',
            )
        ]

    if task == "click-menu-2":
        label_match = re.fullmatch(
            r'Click the "Menu" button, and then find and click on the item labeled "(.+)"\.',
            goal,
        )
        icon_match = re.fullmatch(
            r'Click the "Menu" button, and then find and click on the item with the "(.+)" icon\.',
            goal,
        )
        if not (label_match or icon_match):
            raise ValueError("Unexpected click-menu-2 goal shape")
        if label_match:
            item_class = {
                "Save": "ui-icon-disk",
                "Prev": "ui-icon-seek-start",
                "Stop": "ui-icon-stop",
                "Play": "ui-icon-play",
                "Next": "ui-icon-seek-end",
                "Zoom In": "ui-icon-zoomin",
                "Zoom Out": "ui-icon-zoomout",
            }[label_match.group(1)]
        else:
            item_class = icon_match.group(1)

        actions = [("open_menu", 'page.get_by_text("Menu").click()')]
        playback_classes = {
            "ui-icon-seek-start",
            "ui-icon-stop",
            "ui-icon-play",
            "ui-icon-seek-end",
        }
        if item_class in playback_classes:
            actions.append(
                ("open_playback_submenu", 'page.get_by_text("Playback").click()')
            )
        actions.append(("click_menu_item", f'page.locator(".{item_class}").click()'))
        return actions

    raise ValueError(f"Unknown task: {task}")


def run_episode(task: str, seed: int) -> dict[str, Any]:
    job_id = f"{task}::seed-{seed}"
    environment = gym.make(
        f"browsergym/miniwob.{task}",
        headless=True,
        action_mapping=None,
        pre_observation_delay=0.05,
        pw_context_kwargs={"offline": True, "service_workers": "block"},
    )
    action_phase_requests: list[str] = []
    steps: list[dict[str, Any]] = []
    try:
        observation, _ = environment.reset(seed=seed)
        initial_url = urlparse(observation["url"])
        if initial_url.scheme != "file":
            raise AssertionError(f"Expected file URL, got {initial_url.scheme!r}")

        unwrapped = environment.unwrapped
        chromium_version = unwrapped.browser.version
        unwrapped.context.on(
            "request",
            lambda request: action_phase_requests.append(request.url),
        )

        if job_id == RECOVERY_JOB_ID:
            observation, reward, terminated, truncated, _ = environment.step(
                'page.locator("#arl-missing-recovery-probe").click(timeout=100)'
            )
            steps.append(
                step_record(
                    len(steps) + 1,
                    "expected_locator_timeout_probe",
                    observation,
                    reward,
                    terminated,
                    truncated,
                )
            )
            probe = steps[-1]
            assert probe == {
                "ordinal": 1,
                "action_kind": "expected_locator_timeout_probe",
                "reward": 0.0,
                "terminated": False,
                "truncated": False,
                "has_error": True,
                "error_type": "TimeoutError",
            }

        goal = observation["goal"]
        initial_fingerprint = {
            "url_scheme": initial_url.scheme,
            "url_file": Path(unquote(initial_url.path)).name,
            "goal_sha256": hashlib.sha256(goal.encode("utf-8")).hexdigest(),
            "observation_key_count": len(observation),
            "accessibility_tree_node_count": count_tree_nodes(
                observation["axtree_object"]
            ),
            "screenshot_shape": list(observation["screenshot"].shape),
        }

        final_reward = 0.0
        final_terminated = False
        final_truncated = False
        for action_kind, action in actions_for(task, goal):
            observation, reward, terminated, truncated, _ = environment.step(action)
            steps.append(
                step_record(
                    len(steps) + 1,
                    action_kind,
                    observation,
                    reward,
                    terminated,
                    truncated,
                )
            )
            final_reward = float(reward)
            final_terminated = bool(terminated)
            final_truncated = bool(truncated)
            if terminated or truncated:
                break

        http_requests = [
            url
            for url in action_phase_requests
            if urlparse(url).scheme in {"http", "https"}
        ]
        success = (
            final_reward == 1.0
            and final_terminated
            and not final_truncated
            and not observation["last_action_error"]
        )
        return {
            "job_id": job_id,
            "task": task,
            "seed": seed,
            "initial_observation": initial_fingerprint,
            "chromium_version": chromium_version,
            "steps": steps,
            "action_phase_request_count": len(action_phase_requests),
            "action_phase_http_request_count": len(http_requests),
            "recovery_probe_triggered": job_id == RECOVERY_JOB_ID,
            "recovered_after_expected_error": (job_id == RECOVERY_JOB_ID and success),
            "success": success,
        }
    finally:
        environment.close()


def validate_environment(miniwob_repo: Path) -> tuple[dict[str, str], str, str]:
    browsergym_repo = Path.cwd().resolve()
    if not (browsergym_repo / "browsergym/core/src/browsergym/core").is_dir():
        raise SystemExit("Run this script from the BrowserGym repository root.")

    browsergym_commit = git_commit(browsergym_repo)
    miniwob_commit = git_commit(miniwob_repo)
    if browsergym_commit != EXPECTED_BROWSERGYM_COMMIT:
        raise SystemExit(
            "BrowserGym commit mismatch: expected "
            f"{EXPECTED_BROWSERGYM_COMMIT}, got {browsergym_commit or 'unknown'}"
        )
    if miniwob_commit != EXPECTED_MINIWOB_COMMIT:
        raise SystemExit(
            "MiniWoB++ commit mismatch: expected "
            f"{EXPECTED_MINIWOB_COMMIT}, got {miniwob_commit or 'unknown'}"
        )

    versions = {name: importlib.metadata.version(name) for name in EXPECTED_VERSIONS}
    if versions != EXPECTED_VERSIONS:
        raise SystemExit(
            f"Runtime version mismatch: expected {EXPECTED_VERSIONS}, got {versions}"
        )

    miniwob_url = os.environ.get("MINIWOB_URL")
    if not miniwob_url:
        raise SystemExit("MINIWOB_URL must point to the local MiniWoB task directory.")
    parsed_url = urlparse(miniwob_url)
    if parsed_url.scheme != "file":
        raise SystemExit("MINIWOB_URL must use file://, not a network scheme.")
    configured_path = Path(unquote(parsed_url.path)).resolve()
    expected_path = (miniwob_repo / "miniwob/html/miniwob").resolve()
    if configured_path != expected_path:
        raise SystemExit(
            f"MINIWOB_URL mismatch: expected {expected_path}, got {configured_path}"
        )
    for task in TASKS:
        if not (configured_path / f"{task}.html").is_file():
            raise SystemExit(f"Missing local MiniWoB task: {task}.html")

    browser_path = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""))
    if not browser_path.is_dir():
        raise SystemExit("PLAYWRIGHT_BROWSERS_PATH must name the pinned local cache.")
    if not (browser_path / f"chromium-{EXPECTED_BROWSER_REVISION}").is_dir():
        raise SystemExit(
            f"Missing Playwright Chromium revision {EXPECTED_BROWSER_REVISION}."
        )
    return versions, browsergym_commit, miniwob_commit


def job_specs() -> list[dict[str, Any]]:
    return [
        {
            "job_id": f"{task}::seed-{seed}",
            "task": task,
            "seed": seed,
        }
        for task in TASKS
        for seed in SEEDS
    ]


def new_state(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "config": config,
        "completed": {},
        "history": [],
    }


def load_state(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("schema_version") != STATE_SCHEMA_VERSION:
        raise SystemExit("State schema version mismatch.")
    if state.get("config") != config:
        raise SystemExit("State configuration does not match the current run.")
    if not isinstance(state.get("completed"), dict):
        raise SystemExit("State completed-job map is invalid.")
    if not isinstance(state.get("history"), list):
        raise SystemExit("State history is invalid.")
    return state


def completed_in_order(
    state: dict[str, Any], specifications: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [
        state["completed"][specification["job_id"]]
        for specification in specifications
        if specification["job_id"] in state["completed"]
    ]


def aggregate(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    by_task = {
        task: {
            "completed": sum(episode["task"] == task for episode in episodes),
            "successes": sum(
                episode["task"] == task and episode["success"] for episode in episodes
            ),
        }
        for task in TASKS
    }
    return {
        "completed_episodes": len(episodes),
        "successful_episodes": sum(episode["success"] for episode in episodes),
        "success_rate": (
            sum(episode["success"] for episode in episodes) / len(episodes)
            if episodes
            else 0.0
        ),
        "by_task": by_task,
        "tasks_passing_all_three_seeds": sum(
            item["completed"] == len(SEEDS) and item["successes"] == len(SEEDS)
            for item in by_task.values()
        ),
        "recovery_probes": sum(
            episode["recovery_probe_triggered"] for episode in episodes
        ),
        "successful_recoveries": sum(
            episode["recovered_after_expected_error"] for episode in episodes
        ),
        "action_phase_http_request_count": sum(
            episode["action_phase_http_request_count"] for episode in episodes
        ),
    }


def build_summary(
    *,
    state: dict[str, Any],
    specifications: Sequence[dict[str, Any]],
    versions: dict[str, str],
    browsergym_commit: str,
    miniwob_commit: str,
    status: str,
    resume_used: bool,
    resume_baseline_ids: Sequence[str],
    resume_baseline_before: str | None,
    resume_baseline_after: str | None,
) -> dict[str, Any]:
    episodes = completed_in_order(state, specifications)
    completed_ids = {episode["job_id"] for episode in episodes}
    pending_ids = [
        specification["job_id"]
        for specification in specifications
        if specification["job_id"] not in completed_ids
    ]
    all_success = all(episode["success"] for episode in episodes)
    all_file_urls = all(
        episode["initial_observation"]["url_scheme"] == "file" for episode in episodes
    )
    aggregate_result = aggregate(episodes)
    final = status == "complete"
    validation = {
        "partial_invariants_passed": all_success and all_file_urls,
        "final_assertions_applicable": final,
        "all_assertions_passed": False,
        "all_episode_successes": all_success,
        "all_initial_urls_use_file_scheme": all_file_urls,
        "browser_context_offline": True,
        "service_workers_blocked": True,
        "configured_external_targets": 0,
        "model_calls": 0,
        "action_phase_http_request_count": aggregate_result[
            "action_phase_http_request_count"
        ],
        "recovery_probe_count": aggregate_result["recovery_probes"],
        "successful_recovery_count": aggregate_result["successful_recoveries"],
        "resume_preserved_preexisting_results": (
            resume_baseline_before == resume_baseline_after if resume_used else None
        ),
        "raw_goals_screenshots_or_dom_exported": False,
    }
    if final:
        assert len(episodes) == len(specifications) == 9
        assert not pending_ids
        assert all_success
        assert all_file_urls
        assert aggregate_result["successful_episodes"] == 9
        assert aggregate_result["tasks_passing_all_three_seeds"] == 3
        assert aggregate_result["recovery_probes"] == 1
        assert aggregate_result["successful_recoveries"] == 1
        assert aggregate_result["action_phase_http_request_count"] == 0
        if resume_used:
            assert len(resume_baseline_ids) == 4
            assert resume_baseline_before == resume_baseline_after
        validation["all_assertions_passed"] = True

    return {
        "metadata": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "browsergym_commit": browsergym_commit,
            "miniwob_commit": miniwob_commit,
            "versions": versions,
            "playwright_browser_revision": EXPECTED_BROWSER_REVISION,
            "script_sha256": file_sha256(Path(__file__).resolve()),
            "tasks": list(TASKS),
            "seeds": list(SEEDS),
            "job_count": len(specifications),
            "model_calls": 0,
            "configured_external_targets": 0,
            "browser_context_offline": True,
            "service_workers_blocked": True,
        },
        "status": status,
        "progress": {
            "completed": len(episodes),
            "pending": len(pending_ids),
            "total": len(specifications),
            "pending_job_ids": pending_ids,
        },
        "resume": {
            "used": resume_used,
            "preexisting_completed_count": len(resume_baseline_ids),
            "skipped_preexisting_job_ids": list(resume_baseline_ids),
            "preexisting_results_sha256_before": resume_baseline_before,
            "preexisting_results_sha256_after": resume_baseline_after,
            "preserved": (
                resume_baseline_before == resume_baseline_after if resume_used else None
            ),
        },
        "episodes": episodes,
        "aggregate": aggregate_result,
        "state_history": state["history"],
        "validation": validation,
    }


def main() -> None:
    args = parse_args()
    specifications = job_specs()
    if args.stop_after is not None and not 1 <= args.stop_after <= len(specifications):
        raise SystemExit(f"--stop-after must be between 1 and {len(specifications)}")

    miniwob_repo = args.miniwob_repo.resolve()
    versions, browsergym_commit, miniwob_commit = validate_environment(miniwob_repo)
    config = {
        "browsergym_commit": browsergym_commit,
        "miniwob_commit": miniwob_commit,
        "versions": versions,
        "browser_revision": EXPECTED_BROWSER_REVISION,
        "jobs": specifications,
        "recovery_job_id": RECOVERY_JOB_ID,
        "browser_context_offline": True,
        "service_workers_blocked": True,
    }

    if args.resume:
        if not args.state.is_file():
            raise SystemExit("--resume requires an existing state file.")
        state = load_state(args.state, config)
    else:
        if args.state.exists():
            raise SystemExit(
                "State file already exists; use --resume or choose a new state path."
            )
        state = new_state(config)

    valid_job_ids = {specification["job_id"] for specification in specifications}
    unknown_job_ids = set(state["completed"]) - valid_job_ids
    if unknown_job_ids:
        raise SystemExit(f"State contains unknown jobs: {sorted(unknown_job_ids)}")

    resume_baseline_ids: list[str] = []
    resume_baseline_before: str | None = None
    if args.resume:
        resume_baseline_ids = [
            specification["job_id"]
            for specification in specifications
            if specification["job_id"] in state["completed"]
        ]
        resume_baseline_before = canonical_sha256(
            [state["completed"][job_id] for job_id in resume_baseline_ids]
        )
        state["history"].append(
            {
                "event": "resume_started",
                "preexisting_completed_count": len(resume_baseline_ids),
                "preexisting_results_sha256": resume_baseline_before,
            }
        )
        write_json_atomic(args.state, state)

    for specification in specifications:
        job_id = specification["job_id"]
        if job_id in state["completed"]:
            continue
        episode = run_episode(specification["task"], specification["seed"])
        state["completed"][job_id] = episode
        state["history"].append(
            {
                "event": "episode_completed",
                "job_id": job_id,
                "success": episode["success"],
                "completed_count": len(state["completed"]),
            }
        )
        write_json_atomic(args.state, state)

        if (
            args.stop_after is not None
            and len(state["completed"]) >= args.stop_after
            and len(state["completed"]) < len(specifications)
        ):
            state["history"].append(
                {
                    "event": "intentional_stop",
                    "completed_count": len(state["completed"]),
                    "pending_count": len(specifications) - len(state["completed"]),
                }
            )
            write_json_atomic(args.state, state)
            summary = build_summary(
                state=state,
                specifications=specifications,
                versions=versions,
                browsergym_commit=browsergym_commit,
                miniwob_commit=miniwob_commit,
                status="interrupted",
                resume_used=args.resume,
                resume_baseline_ids=resume_baseline_ids,
                resume_baseline_before=resume_baseline_before,
                resume_baseline_after=None,
            )
            assert summary["validation"]["partial_invariants_passed"]
            write_json_atomic(args.output, summary)
            print(
                "Intentional stop: "
                f"{summary['progress']['completed']}/{summary['progress']['total']} "
                f"jobs complete; wrote {args.output} and {args.state}"
            )
            return

    resume_baseline_after: str | None = None
    if args.resume:
        resume_baseline_after = canonical_sha256(
            [state["completed"][job_id] for job_id in resume_baseline_ids]
        )
        state["history"].append(
            {
                "event": "resume_completed",
                "preexisting_completed_count": len(resume_baseline_ids),
                "preexisting_results_sha256_before": resume_baseline_before,
                "preexisting_results_sha256_after": resume_baseline_after,
                "preserved": resume_baseline_before == resume_baseline_after,
            }
        )
        write_json_atomic(args.state, state)

    summary = build_summary(
        state=state,
        specifications=specifications,
        versions=versions,
        browsergym_commit=browsergym_commit,
        miniwob_commit=miniwob_commit,
        status="complete",
        resume_used=args.resume,
        resume_baseline_ids=resume_baseline_ids,
        resume_baseline_before=resume_baseline_before,
        resume_baseline_after=resume_baseline_after,
    )
    write_json_atomic(args.output, summary)
    print(
        f"Complete: {summary['aggregate']['successful_episodes']}/"
        f"{summary['aggregate']['completed_episodes']} successful; "
        f"wrote {args.output} and {args.state}"
    )


if __name__ == "__main__":
    main()
