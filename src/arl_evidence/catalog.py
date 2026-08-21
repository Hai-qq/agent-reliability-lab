"""Normalize frozen ARL artifacts into a compact, auditable evidence catalog."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl.history import verify_recorded_source_manifest
from arl_evidence import __version__


@dataclass(frozen=True)
class IncrementSpec:
    version: str
    title: str
    category: str
    focus: str
    claim: str
    artifact_dir: str
    repeat_dir: str
    trace_subdir: str
    docs_href: str


INCREMENTS = (
    IncrementSpec(
        version="v0.10",
        title="Resumable Study Runtime",
        category="harness",
        focus="Atomic checkpoint and fail-closed resume",
        claim="A stopped 36-job study resumes without rerunning or changing the first 13 results.",
        artifact_dir="artifacts/study_runtime_v10",
        repeat_dir="artifacts/study_runtime_v10_repeat",
        trace_subdir="study/traces",
        docs_href="../../docs/study-runtime-v10.md",
    ),
    IncrementSpec(
        version="v0.11",
        title="Parallel Lease Coordinator",
        category="harness",
        focus="Four-worker lease, expiry and commit fencing",
        claim="Crash and expiry retries still produce exactly one final commit for every job.",
        artifact_dir="artifacts/parallel_study_v11",
        repeat_dir="artifacts/parallel_study_v11_repeat",
        trace_subdir="study/traces",
        docs_href="../../docs/parallel-study-v11.md",
    ),
    IncrementSpec(
        version="v0.12",
        title="Audited Scenario Pack",
        category="runtime",
        focus="Task templates, exact guards and bounded workflow",
        claim=(
            "Template guards recover compatible conflicts and classify changed targets "
            "without unsafe rebasing."
        ),
        artifact_dir="artifacts/scenario_pack_v12",
        repeat_dir="artifacts/scenario_pack_v12_repeat",
        trace_subdir="traces",
        docs_href="../../docs/scenario-pack-v12.md",
    ),
    IncrementSpec(
        version="v0.13",
        title="Stateful Authorization",
        category="authorization",
        focus="Clarification, revision and token freshness",
        claim=(
            "Revision-aware authorization removes unsafe commits and safely stops when "
            "the user disengages."
        ),
        artifact_dir="artifacts/symbolic_user_v13",
        repeat_dir="artifacts/symbolic_user_v13_repeat",
        trace_subdir="traces",
        docs_href="../../docs/symbolic-user-v13.md",
    ),
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _summary(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _source_manifest_check(project_root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    expected = summary["metadata"]["source_manifest"]
    result = verify_recorded_source_manifest(project_root, expected)
    return {**result, "sha256": result.get("recorded_sha256", expected.get("sha256"))}


def _trace_manifest_check(
    formal_trace_dir: Path,
    repeat_trace_dir: Path,
    summary: dict[str, Any],
) -> dict[str, Any]:
    expected = summary["metadata"]["trace_manifest"]
    formal = {path.name: sha256_file(path) for path in sorted(formal_trace_dir.glob("*.jsonl"))}
    repeat = {path.name: sha256_file(path) for path in sorted(repeat_trace_dir.glob("*.jsonl"))}
    formal_sha = hashlib.sha256(canonical_json(formal).encode("utf-8")).hexdigest()
    passed = (
        bool(formal)
        and formal == repeat
        and formal == expected["files"]
        and formal_sha == expected["sha256"]
    )
    return {
        "file_count": len(formal),
        "sha256": formal_sha,
        "formal_repeat_identical": formal == repeat,
        "recorded_manifest_matched": formal == expected["files"],
        "passed": passed,
    }


def _metrics_v10(summary: dict[str, Any]) -> list[dict[str, Any]]:
    progress = summary["progress"]
    resume = summary["resume"]
    preserved = resume["preexisting_completed_count"]
    return [
        {
            "label": "Completed jobs",
            "value": f"{progress['completed_count']} / {progress['total_count']}",
        },
        {
            "label": "Preserved before resume",
            "value": f"{preserved} / {preserved}",
        },
        {"label": "New after resume", "value": str(progress["new_jobs_completed"])},
        {
            "label": "Resume integrity",
            "value": "PASS" if resume["preexisting_results_preserved"] else "FAIL",
        },
    ]


def _metrics_v11(summary: dict[str, Any]) -> list[dict[str, Any]]:
    progress = summary["progress"]
    parallel = summary["parallel"]
    commits = summary["validity"]["exactly_one_final_commit"]["commit_counts"]
    return [
        {
            "label": "Final commits",
            "value": f"{sum(value == 1 for value in commits.values())} / {len(commits)}",
        },
        {"label": "Lease acquisitions", "value": str(parallel["lease_acquisition_count"])},
        {
            "label": "Expiry / crash",
            "value": f"{parallel['lease_expiration_count']} / {parallel['worker_failure_count']}",
        },
        {"label": "Max active leases", "value": str(parallel["max_leased_count"])},
        {
            "label": "Completed jobs",
            "value": f"{progress['completed_count']} / {progress['total_count']}",
        },
    ]


def _metrics_v12(summary: dict[str, Any]) -> list[dict[str, Any]]:
    aggregate = summary["aggregate"]
    guarded = aggregate["by_runtime"]["r2_template_guarded"]
    compatible = guarded["by_condition"]["compatible_conflict"]
    incompatible = guarded["by_condition"]["incompatible_conflict"]
    workflow = summary["validity"]["compensation_workflow_audit"]
    return [
        {"label": "Episodes", "value": str(aggregate["episode_count"])},
        {
            "label": "Compatible recovery",
            "value": f"{compatible['safe_successes']} / {compatible['total']}",
        },
        {
            "label": "Classified target change",
            "value": f"{incompatible['total']} / {incompatible['total']}",
        },
        {"label": "Workflow success", "value": f"{workflow['successes']} / {workflow['attempts']}"},
        {
            "label": "Terminal probes",
            "value": f"{workflow['terminal_probes']} / {workflow['terminal_probes']}",
        },
    ]


def _metrics_v13(summary: dict[str, Any]) -> list[dict[str, Any]]:
    statistics = summary["statistics"]
    guarded = statistics["by_policy"]["revision_aware"]
    non_direct_safe = (
        guarded["clarification_required"]["safe_successes"]
        + guarded["precommit_revision"]["safe_successes"]
    )
    non_direct_total = (
        guarded["clarification_required"]["sessions"] + guarded["precommit_revision"]["sessions"]
    )
    unsafe = sum(item["unsafe_commits"] for item in guarded.values())
    aborts = sum(item["safe_aborts"] for item in guarded.values())
    return [
        {"label": "Paired sessions", "value": str(statistics["session_count"])},
        {"label": "Non-direct SafeSuccess", "value": f"{non_direct_safe} / {non_direct_total}"},
        {"label": "Unsafe commits", "value": str(unsafe)},
        {"label": "Safe aborts", "value": str(aborts)},
        {"label": "Repeated cohorts", "value": str(statistics["repeat_count"])},
    ]


def _headline_rate(spec: IncrementSpec, summary: dict[str, Any]) -> float:
    if spec.version == "v0.10":
        return float(summary["resume"]["preexisting_results_preserved"])
    if spec.version == "v0.11":
        return float(summary["validity"]["exactly_one_final_commit"]["passed"])
    if spec.version == "v0.12":
        return summary["aggregate"]["by_runtime"]["r2_template_guarded"][
            "compatible_conflict_recovery_rate"
        ]
    guarded = summary["statistics"]["by_policy"]["revision_aware"]
    safe = sum(
        guarded[key]["safe_successes"] for key in ("clarification_required", "precommit_revision")
    )
    total = sum(
        guarded[key]["sessions"] for key in ("clarification_required", "precommit_revision")
    )
    return safe / total


def _metrics(spec: IncrementSpec, summary: dict[str, Any]) -> list[dict[str, Any]]:
    builders = {
        "v0.10": _metrics_v10,
        "v0.11": _metrics_v11,
        "v0.12": _metrics_v12,
        "v0.13": _metrics_v13,
    }
    return builders[spec.version](summary)


def collect_evidence(project_root: Path) -> dict[str, Any]:
    increments = []
    for spec in INCREMENTS:
        artifact_dir = project_root / spec.artifact_dir
        repeat_dir = project_root / spec.repeat_dir
        summary_path = artifact_dir / "summary.json"
        repeat_summary_path = repeat_dir / "summary.json"
        summary = _summary(summary_path)
        source_check = _source_manifest_check(project_root, summary)
        trace_check = _trace_manifest_check(
            artifact_dir / spec.trace_subdir,
            repeat_dir / spec.trace_subdir,
            summary,
        )
        summary_identical = summary_path.read_bytes() == repeat_summary_path.read_bytes()
        increment_validity = bool(summary["validity"]["all_selected_checks_passed"])
        increment_passed = (
            source_check["passed"]
            and trace_check["passed"]
            and summary_identical
            and increment_validity
        )
        increments.append(
            {
                "version": spec.version,
                "title": spec.title,
                "category": spec.category,
                "focus": spec.focus,
                "claim": spec.claim,
                "artifact_href": f"../{Path(spec.artifact_dir).name}/summary.json",
                "docs_href": spec.docs_href,
                "headline_rate": _headline_rate(spec, summary),
                "metrics": _metrics(spec, summary),
                "integrity": {
                    "summary_sha256": sha256_file(summary_path),
                    "source_manifest": source_check,
                    "trace_manifest": trace_check,
                    "formal_repeat_summary_identical": summary_identical,
                    "saved_validity_passed": increment_validity,
                    "passed": increment_passed,
                },
                "runtime_boundary": {
                    "model_calls": summary["metadata"]["model_calls"],
                    "external_network_calls": summary["metadata"]["external_network_calls"],
                    "synthetic_only": summary["metadata"]["uses_only_synthetic_data"],
                },
            }
        )

    validity = {
        "increment_count": {
            "expected": 4,
            "actual": len(increments),
            "passed": len(increments) == 4,
        },
        "saved_validity": {
            "passed": all(item["integrity"]["saved_validity_passed"] for item in increments)
        },
        "source_manifests": {
            "passed": all(item["integrity"]["source_manifest"]["passed"] for item in increments)
        },
        "formal_repeat_summaries": {
            "passed": all(
                item["integrity"]["formal_repeat_summary_identical"] for item in increments
            )
        },
        "formal_repeat_traces": {
            "file_count": sum(
                item["integrity"]["trace_manifest"]["file_count"] for item in increments
            ),
            "passed": all(item["integrity"]["trace_manifest"]["passed"] for item in increments),
        },
        "local_synthetic_boundary": {
            "passed": all(
                item["runtime_boundary"]["model_calls"] == 0
                and item["runtime_boundary"]["external_network_calls"] == 0
                and item["runtime_boundary"]["synthetic_only"]
                for item in increments
            )
        },
    }
    validity["all_selected_checks_passed"] = all(
        item["passed"] for key, item in validity.items() if key != "all_selected_checks_passed"
    )
    if not validity["all_selected_checks_passed"]:
        failed = [
            key
            for key, item in validity.items()
            if key != "all_selected_checks_passed" and not item.get("passed", False)
        ]
        raise AssertionError(f"Evidence catalog validity gates failed: {failed}")

    return {
        "metadata": {
            "increment_version": __version__,
            "title": "Agent Reliability Lab Evidence Explorer",
            "input_versions": [item.version for item in INCREMENTS],
            "model_calls": 0,
            "external_network_calls": 0,
            "uses_only_synthetic_data": True,
            "payload_policy": "aggregate metrics, hashes, counts, and local evidence links only",
        },
        "increments": increments,
        "validity": validity,
        "limitations": [
            "Read-only aggregate view; open the linked artifact for per-episode evidence.",
            "Fixed synthetic tasks and deterministic policies, not model or real-user performance.",
            "No network request, external asset, account, credential, model, API, or real system.",
        ],
    }
