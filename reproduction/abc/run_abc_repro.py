#!/usr/bin/env python3
"""Reproduce ABC's deterministic tau-bench validity counterexamples.

The experiment executes the historical tau-bench reward function directly. It
does not call an LLM or user simulator and does not export benchmark database
contents or task instructions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_ORIGINAL = {
    "airline": {"no_op": 19, "dump_all": 20, "tasks": 50},
    "retail": {"no_op": 7, "dump_all": 11, "tasks": 115},
}


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def git_commit(repo: Path) -> str | None:
    completed = run_command(["git", "rev-parse", "HEAD"], repo)
    return completed.stdout.strip() if completed.returncode == 0 else None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def install_offline_litellm_stub() -> None:
    """Satisfy tau-bench's import without allowing a model call."""
    module = types.ModuleType("litellm")

    def completion(*_: Any, **__: Any) -> Any:
        raise RuntimeError("LLM calls are disabled in this deterministic reproduction.")

    module.completion = completion  # type: ignore[attr-defined]
    sys.modules["litellm"] = module


def worker(tau_repo: Path) -> dict[str, Any]:
    install_offline_litellm_stub()
    sys.path.insert(0, str(tau_repo.resolve()))

    from tau_bench.envs.airline.env import MockAirlineDomainEnv
    from tau_bench.envs.retail.env import MockRetailDomainEnv
    from tau_bench.envs.user import UserStrategy
    from tau_bench.types import Action, RESPOND_ACTION_NAME

    domains = {
        "airline": (MockAirlineDomainEnv, 50),
        "retail": (MockRetailDomainEnv, 115),
    }
    result: dict[str, Any] = {}

    for domain, (env_class, task_count) in domains.items():
        no_op_passed: list[int] = []
        dump_all_passed: list[int] = []
        required_action_ids: list[int] = []

        for task_id in range(task_count):
            no_op_env = env_class(
                user_strategy=UserStrategy.HUMAN,
                task_index=task_id,
            )
            if getattr(no_op_env.task, "required_actions", None):
                required_action_ids.append(task_id)
            if no_op_env.calculate_reward().reward == 1.0:
                no_op_passed.append(task_id)

            dump_env = env_class(
                user_strategy=UserStrategy.HUMAN,
                task_index=task_id,
            )
            database_dump = json.dumps(dump_env.data)
            dump_env.actions = [
                Action(
                    name=RESPOND_ACTION_NAME,
                    kwargs={"content": database_dump},
                )
            ]
            if dump_env.calculate_reward().reward == 1.0:
                dump_all_passed.append(task_id)

        result[domain] = {
            "task_count": task_count,
            "no_op": {
                "passed": len(no_op_passed),
                "rate": len(no_op_passed) / task_count,
                "task_ids": no_op_passed,
            },
            "dump_all": {
                "passed": len(dump_all_passed),
                "rate": len(dump_all_passed) / task_count,
                "task_ids": dump_all_passed,
            },
            "required_action_task_ids": required_action_ids,
        }
    return result


def run_worker(script: Path, tau_repo: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--worker",
            "--tau-repo",
            str(tau_repo),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Worker failed for {tau_repo}:\n{completed.stdout}\n{completed.stderr}"
        )
    return json.loads(completed.stdout)


def normalize_git_error(stderr: str) -> str | None:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else None


def patch_checks(tau_repo: Path, patch: Path) -> dict[str, Any]:
    standard = run_command(["git", "apply", "--check", str(patch)], tau_repo)
    recount = run_command(
        ["git", "apply", "--recount", "--check", str(patch)],
        tau_repo,
    )
    return {
        "standard_git_apply_check": {
            "returncode": standard.returncode,
            "last_error": normalize_git_error(standard.stderr),
        },
        "git_apply_recount_check": {
            "returncode": recount.returncode,
            "last_error": normalize_git_error(recount.stderr),
        },
    }


def checklist_items(abc_markdown: Path) -> list[str]:
    items: list[str] = []
    pattern = re.compile(r"^(I(?:I|II)?\.[A-Za-z0-9.]+)\s")
    for line in abc_markdown.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match:
            items.append(match.group(1))
    return items


def assessment_summary(assessment_dir: Path, abc_markdown: Path) -> dict[str, Any]:
    files: dict[str, Any] = {}
    key_pattern = re.compile(r"^([A-Z]\.[A-Za-z0-9.]+):\s*$")
    score_pattern = re.compile(r"^\s+score:\s*([01])\s*$")
    for path in sorted(assessment_dir.glob("*.yaml")):
        text = path.read_text(encoding="utf-8")
        keys = [
            match.group(1)
            for line in text.splitlines()
            if (match := key_pattern.match(line))
        ]
        scores = [
            int(match.group(1))
            for line in text.splitlines()
            if (match := score_pattern.match(line))
        ]
        files[path.stem] = {
            "check_count": len(keys),
            "score_1": sum(scores),
            "score_0": len(scores) - sum(scores),
            "key_prefixes": sorted({key.split(".", 1)[0] for key in keys}),
        }

    tau_text = (assessment_dir / "tau-bench.yaml").read_text(encoding="utf-8")
    current_items = checklist_items(abc_markdown)
    return {
        "assessment_file_count": len(files),
        "files": files,
        "current_checklist_item_count": len(current_items),
        "current_checklist_prefixes": ["I", "II", "III"],
        "tau_assessment_uses_legacy_prefixes": files["tau-bench"]["key_prefixes"],
        "tau_assessment_claims_no_exploitable_vulnerability": (
            "T.10:" in tau_text
            and "score: 1" in tau_text.split("T.10:", 1)[1].split("R.1:", 1)[0]
            and "No vulnerabilities are found" in tau_text
        ),
    }


def validate(original: dict[str, Any], fixed: dict[str, Any], checks: dict[str, Any]) -> None:
    for domain, expected in EXPECTED_ORIGINAL.items():
        assert original[domain]["task_count"] == expected["tasks"]
        assert original[domain]["no_op"]["passed"] == expected["no_op"]
        assert original[domain]["dump_all"]["passed"] == expected["dump_all"]

    original_airline_no_op = original["airline"]["no_op"]["task_ids"]
    fixed_required = fixed["airline"]["required_action_task_ids"]
    assert fixed_required == original_airline_no_op
    assert fixed["airline"]["no_op"]["passed"] == 0
    assert fixed["airline"]["dump_all"]["passed"] == 1
    assert fixed["retail"]["no_op"] == original["retail"]["no_op"]
    assert fixed["retail"]["dump_all"] == original["retail"]["dump_all"]
    assert checks["standard_git_apply_check"]["returncode"] != 0
    assert checks["git_apply_recount_check"]["returncode"] == 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--tau-repo", type=Path)
    parser.add_argument("--tau-original", type=Path)
    parser.add_argument("--tau-fixed", type=Path)
    parser.add_argument("--abc-repo", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker:
        if args.tau_repo is None:
            raise SystemExit("--worker requires --tau-repo")
        print(json.dumps(worker(args.tau_repo), sort_keys=True))
        return

    required = {
        "--tau-original": args.tau_original,
        "--tau-fixed": args.tau_fixed,
        "--abc-repo": args.abc_repo,
        "--output": args.output,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise SystemExit(f"Missing required arguments: {', '.join(missing)}")

    tau_original = args.tau_original.resolve()
    tau_fixed = args.tau_fixed.resolve()
    abc_repo = args.abc_repo.resolve()
    output = args.output.resolve()
    patch = abc_repo / "benchmarks/tau-bench/tau-bench-issue-1-fix.patch"
    script = Path(__file__).resolve()

    original = run_worker(script, tau_original)
    fixed = run_worker(script, tau_fixed)
    checks = patch_checks(tau_original, patch)
    validate(original, fixed, checks)

    license_files = sorted(
        path.name
        for pattern in ("LICENSE*", "COPYING*")
        for path in abc_repo.glob(pattern)
        if path.is_file()
    )
    result = {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "abc_commit": git_commit(abc_repo),
            "tau_original_commit": git_commit(tau_original),
            "tau_fixed_base_commit": git_commit(tau_fixed),
            "fix_patch_sha256": sha256(patch),
            "model_or_user_simulator_calls": 0,
            "abc_repository_license_files": license_files,
        },
        "original": original,
        "fixed": fixed,
        "fix_patch": checks,
        "assessment_audit": assessment_summary(
            abc_repo / "assessments",
            abc_repo / "ABC.md",
        ),
        "validation": {
            "all_assertions_passed": True,
            "airline_required_actions_exactly_cover_original_no_op_passes": True,
            "retail_unmodified_by_fix_patch": True,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
