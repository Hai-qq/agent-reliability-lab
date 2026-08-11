#!/usr/bin/env python3
"""Build the public 24-task analysis for a valid single-slot model run."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json, digest_value
from arl_analysis.bootstrap import task_cluster_bootstrap
from arl_study.scheduler import file_sha256, write_json_atomic

RUNTIMES = ("r0_raw", "r1_guarded", "r2_reliable")
CONDITIONS = ("clean", "recoverable_fault")
TRIALS = (0, 1, 2)
MECHANISM_COUNTERS = (
    "retry_count",
    "confirmation_count",
    "schema_adaptation_count",
    "result_normalization_count",
    "conflict_rebase_count",
    "compensation_action_count",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20_260_808)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "src/arl/core/types.py",
            project_root / "src/arl_analysis/__init__.py",
            project_root / "src/arl_analysis/bootstrap.py",
            project_root / "scripts/build_main_single_slot_analysis.py",
        }
    )
    files = {
        str(path.relative_to(project_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    return {
        "algorithm": "sha256(canonical_json({relative_path: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest(),
        "files": files,
    }


def _task_rows(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    descriptors: dict[str, tuple[str, str]] = {}
    cells: dict[tuple[str, str, str], dict[int, bool]] = defaultdict(dict)
    for episode in episodes:
        template_id = episode.get("template_id")
        domain = episode.get("domain")
        fault_family = episode.get("fault_family")
        runtime = episode.get("runtime")
        condition = episode.get("condition")
        trial = episode.get("sampling_trial")
        evaluation = episode.get("evaluation")
        if not all(isinstance(value, str) for value in (template_id, domain, fault_family)):
            raise ValueError("Episode is missing its task descriptor")
        if runtime not in RUNTIMES or condition not in CONDITIONS or trial not in TRIALS:
            raise ValueError("Episode has an invalid runtime, condition, or sampling trial")
        if not isinstance(evaluation, dict) or not isinstance(evaluation.get("safe_success"), bool):
            raise ValueError("Episode is missing a boolean SafeSuccess outcome")
        assert isinstance(template_id, str)
        descriptor = (str(domain), str(fault_family))
        if template_id in descriptors and descriptors[template_id] != descriptor:
            raise ValueError(f"Task descriptor drifted within the run: {template_id}")
        descriptors[template_id] = descriptor
        key = (template_id, runtime, condition)
        if trial in cells[key]:
            raise ValueError(f"Duplicate sampling trial in {key}")
        cells[key][trial] = evaluation["safe_success"]

    rows: list[dict[str, Any]] = []
    for template_id in sorted(descriptors):
        runtime_cells: dict[str, Any] = {}
        for runtime in RUNTIMES:
            condition_cells: dict[str, bool] = {}
            for condition in CONDITIONS:
                trials = cells.get((template_id, runtime, condition), {})
                if set(trials) != set(TRIALS):
                    raise ValueError(
                        f"Incomplete SafePass@3 cell: {template_id}/{runtime}/{condition}"
                    )
                condition_cells[condition] = all(trials[trial] for trial in TRIALS)
            runtime_cells[runtime] = {
                "clean_safe_pass_at_3": condition_cells["clean"],
                "fault_safe_pass_at_3": condition_cells["recoverable_fault"],
                "recovered_fault": (
                    condition_cells["clean"] and condition_cells["recoverable_fault"]
                ),
            }
        domain, fault_family = descriptors[template_id]
        rows.append(
            {
                "template_id": template_id,
                "domain": domain,
                "fault_family": fault_family,
                "runtimes": runtime_cells,
            }
        )
    return rows


def _group_breakdown(rows: list[dict[str, Any]], dimension: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row[dimension]].append(row)
    result: dict[str, Any] = {}
    for label, selected in sorted(grouped.items()):
        by_runtime: dict[str, Any] = {}
        for runtime in RUNTIMES:
            clean = sum(item["runtimes"][runtime]["clean_safe_pass_at_3"] for item in selected)
            fault = sum(item["runtimes"][runtime]["fault_safe_pass_at_3"] for item in selected)
            recovered = sum(item["runtimes"][runtime]["recovered_fault"] for item in selected)
            by_runtime[runtime] = {
                "task_count": len(selected),
                "clean_safe_pass_at_3_tasks": clean,
                "clean_safe_pass_at_3_rate": clean / len(selected),
                "fault_safe_pass_at_3_tasks": fault,
                "fault_safe_pass_at_3_rate": fault / len(selected),
                "recovered_fault_tasks_at_3": recovered,
                "fault_recovery_rate_at_3": recovered / clean if clean else None,
            }
        r1 = by_runtime["r1_guarded"]["fault_recovery_rate_at_3"]
        r2 = by_runtime["r2_reliable"]["fault_recovery_rate_at_3"]
        result[label] = {
            "by_runtime": by_runtime,
            "fault_recovery_rate_at_3_delta_r2_minus_r1": (
                r2 - r1 if r1 is not None and r2 is not None else None
            ),
        }
    return result


def analyze_main_single_slot(
    summary: dict[str, Any],
    *,
    iterations: int = 10_000,
    seed: int = 20_260_808,
) -> dict[str, Any]:
    episodes = summary.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("Full summary is missing episode records")
    rows = _task_rows(episodes)
    bootstrap = task_cluster_bootstrap(episodes, iterations=iterations, seed=seed)
    fault_counts = Counter(row["fault_family"] for row in rows)
    domain_counts = Counter(row["domain"] for row in rows)
    aggregate_primary = summary.get("aggregate", {}).get("primary_effects", {})
    bootstrap_primary = bootstrap["estimates"]
    observed_matches = all(
        bootstrap_primary[name]["observed"] == aggregate_primary.get(name)
        for name in (
            "fault_recovery_rate_at_3_delta_r2_minus_r1",
            "clean_safe_pass_at_3_delta_r2_minus_r1",
        )
    )

    mechanisms: dict[str, Any] = {}
    failure_codes: dict[str, Any] = {}
    for runtime in RUNTIMES:
        selected = [
            episode
            for episode in episodes
            if episode["runtime"] == runtime and episode["condition"] == "recoverable_fault"
        ]
        mechanisms[runtime] = {
            counter: sum(episode["execution"][counter] for episode in selected)
            for counter in MECHANISM_COUNTERS
        }
        failure_codes[runtime] = dict(
            sorted(
                Counter(
                    episode["execution"]["failure_code"] or "none" for episode in selected
                ).items()
            )
        )

    all_runtime_unsolved = [
        row["template_id"]
        for row in rows
        if not any(row["runtimes"][runtime]["clean_safe_pass_at_3"] for runtime in RUNTIMES)
    ]
    r2_unsolved = [
        row["template_id"]
        for row in rows
        if not row["runtimes"]["r2_reliable"]["clean_safe_pass_at_3"]
    ]
    checks = {
        "input_infrastructure_valid": bool(
            summary.get("validity", {}).get("all_selected_checks_passed")
        ),
        "exact_432_episode_input": len(episodes) == 432,
        "exact_24_task_rows": len(rows) == 24,
        "six_fault_families_with_four_tasks_each": (
            len(fault_counts) == 6 and set(fault_counts.values()) == {4}
        ),
        "three_domains_with_eight_tasks_each": (
            len(domain_counts) == 3 and set(domain_counts.values()) == {8}
        ),
        "bootstrap_valid": bootstrap["validity"]["all_selected_checks_passed"],
        "bootstrap_observed_matches_frozen_aggregate": observed_matches,
    }
    return {
        "analysis_contract": {
            "analysis_id": "arl-main-single-slot-analysis-v1",
            "primary_unit": "task template",
            "safe_pass_at_3": "all three sampling trials must be SafeSuccess",
            "bootstrap": bootstrap["analysis_contract"],
        },
        "task_count": len(rows),
        "task_rows_sha256": digest_value(rows),
        "task_rows": rows,
        "by_fault_family": _group_breakdown(rows, "fault_family"),
        "by_domain": _group_breakdown(rows, "domain"),
        "clean_capability": {
            "all_runtime_unsolved_task_count": len(all_runtime_unsolved),
            "all_runtime_unsolved_tasks": all_runtime_unsolved,
            "r2_unsolved_task_count": len(r2_unsolved),
            "r2_unsolved_tasks": r2_unsolved,
        },
        "recoverable_fault_mechanism_counts": mechanisms,
        "recoverable_fault_failure_codes": failure_codes,
        "bootstrap": bootstrap,
        "validity": {
            "checks": checks,
            "all_selected_checks_passed": all(checks.values()),
        },
        "limitations": [
            "This analysis covers one exact model binding and is not the two-model main study.",
            "Six tasks fail SafePass@3 under clean conditions for all three runtimes.",
            "Fault-family and domain subgroups contain only four and eight tasks, respectively.",
            "Bootstrap probability-above-zero is descriptive and is not a p-value.",
        ],
    }


def main() -> None:
    args = parse_args()
    if not args.input.is_file():
        raise SystemExit(f"Input summary does not exist: {args.input}")
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite output: {args.output}")
    summary = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise RuntimeError("Input summary must be a JSON object")
    if not summary.get("validity", {}).get("all_selected_checks_passed"):
        raise RuntimeError("Analysis input must pass the frozen infrastructure validity gate")
    analysis = analyze_main_single_slot(
        summary,
        iterations=args.iterations,
        seed=args.seed,
    )
    if not analysis["validity"]["all_selected_checks_passed"]:
        raise RuntimeError("Main single-slot analysis validity gate failed")
    project_root = Path(__file__).resolve().parents[1]
    result = {
        "metadata": {
            "input_summary_sha256": file_sha256(args.input),
            "input_run_id": summary.get("metadata", {}).get("run_id"),
            "input_binding": summary.get("single_slot_preflight", {}).get("binding"),
            "source_manifest": source_manifest(project_root),
            "raw_model_content_persisted": False,
        },
        **analysis,
    }
    write_json_atomic(args.output, result, refuse_overwrite=True)
    print(
        f"Wrote {args.iterations} paired 24-task bootstrap samples to {args.output}",
        flush=True,
    )


if __name__ == "__main__":
    main()
