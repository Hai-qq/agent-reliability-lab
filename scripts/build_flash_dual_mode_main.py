#!/usr/bin/env python3
"""Build full and public evidence for the 864-episode amended dual-mode main."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_dualmode.analysis import MODE_IDS, analyze_dual_mode
from arl_dualmode.contract import amendment_record, dual_mode_contract
from arl_study.scheduler import file_sha256, write_json_atomic

_CREDENTIAL_LIKE = re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}(?![A-Za-z0-9])")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--non-thinking", required=True, type=Path)
    parser.add_argument("--thinking-high", required=True, type=Path)
    parser.add_argument("--full-output", required=True, type=Path)
    parser.add_argument("--public-output", required=True, type=Path)
    parser.add_argument("--iterations", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20_260_809)
    return parser.parse_args()


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "src/arl/core/types.py",
            project_root / "src/arl_analysis/__init__.py",
            project_root / "src/arl_analysis/bootstrap.py",
            *project_root.glob("src/arl_dualmode/**/*.py"),
            project_root / "scripts/build_flash_dual_mode_main.py",
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


def recorded_source_manifest_check(
    summary: dict[str, Any],
    project_root: Path,
) -> dict[str, Any]:
    recorded = summary.get("metadata", {}).get("source_manifest", {}).get("files")
    if not isinstance(recorded, dict) or not recorded:
        return {"passed": False, "mismatches": ["missing recorded source manifest"]}
    mismatches: list[str] = []
    for relative, expected in sorted(recorded.items()):
        path = project_root / relative
        actual = file_sha256(path) if path.is_file() else None
        if actual != expected:
            mismatches.append(relative)
    return {
        "passed": not mismatches,
        "file_count": len(recorded),
        "mismatches": mismatches,
    }


def _binding(summary: dict[str, Any], mode_id: str) -> dict[str, Any] | None:
    if mode_id == "flash_non_thinking":
        return summary.get("single_slot_preflight", {}).get("binding")
    return summary.get("inference_configuration", {}).get("binding")


def build_outputs(
    summaries: dict[str, dict[str, Any]],
    *,
    input_paths: dict[str, Path],
    project_root: Path,
    iterations: int,
    seed: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    analysis = analyze_dual_mode(summaries, iterations=iterations, seed=seed)
    bindings = {mode_id: _binding(summaries[mode_id], mode_id) for mode_id in MODE_IDS}
    source_checks = {
        mode_id: recorded_source_manifest_check(summaries[mode_id], project_root)
        for mode_id in MODE_IDS
    }
    binding_checks = {
        "same_provider": len({value["provider"] for value in bindings.values() if value}) == 1,
        "same_model_id": len({value["model_id"] for value in bindings.values() if value}) == 1,
        "distinct_inference_revisions": len(
            {value["revision"] for value in bindings.values() if value}
        )
        == 2,
    }
    integrity_checks = {
        "both_recorded_source_manifests_match_current_checkout": all(
            check["passed"] for check in source_checks.values()
        ),
        "bindings_are_same_model_distinct_modes": all(binding_checks.values()),
        "dual_mode_analysis_valid": analysis["validity"]["all_selected_checks_passed"],
    }
    metadata = {
        "run_id": "arl-deepseek-flash-dual-mode-main-v0.26.0",
        "result_scope": "864-episode amended main across two DeepSeek V4 Flash modes",
        "result_label": "same-model dual-inference-mode evidence",
        "provider_content_persisted": False,
        "input_summaries": {
            mode_id: {
                "path": str(input_paths[mode_id].relative_to(project_root)),
                "sha256": file_sha256(input_paths[mode_id]),
                "run_id": summaries[mode_id].get("metadata", {}).get("run_id"),
                "binding": bindings[mode_id],
            }
            for mode_id in MODE_IDS
        },
        "source_manifest": source_manifest(project_root),
    }
    aggregate = {
        "episode_count": 864,
        "configuration_count": 2,
        "same_provider_model_id": True,
        "inference_modes": {mode_id: summaries[mode_id]["aggregate"] for mode_id in MODE_IDS},
        "combined_usage": {
            key: sum(summaries[mode_id]["aggregate"]["model_usage"][key] for mode_id in MODE_IDS)
            for key in (
                "model_calls",
                "external_network_calls",
                "input_tokens",
                "cache_hit_tokens",
                "cache_miss_tokens",
                "output_tokens",
                "reasoning_tokens",
                "total_tokens",
                "estimated_cost_usd",
            )
        },
    }
    validity = {
        "source_manifest_checks": source_checks,
        "binding_checks": binding_checks,
        "checks": integrity_checks,
        "all_selected_checks_passed": all(integrity_checks.values()),
    }
    shared = {
        "metadata": metadata,
        "contract_amendment": amendment_record(),
        "main_study_contract": dual_mode_contract().as_dict(),
        "aggregate": aggregate,
        "analysis": analysis,
        "validity": validity,
        "limitations": [
            "This is same-model, not cross-model or cross-provider, evidence.",
            "The amendment and thinking-high slot followed observation of the non-thinking slot.",
            "No raw provider response content, credentials, or synthetic payload values persist.",
        ],
    }
    episodes = [
        {"inference_configuration": mode_id, **episode}
        for mode_id in MODE_IDS
        for episode in summaries[mode_id]["episodes"]
    ]
    full = {**shared, "episodes": episodes}
    public = {
        **shared,
        "analysis": {
            **analysis,
            "paired_dual_mode_bootstrap": {
                key: value
                for key, value in analysis["paired_dual_mode_bootstrap"].items()
                if key != "task_clusters"
            },
            "per_mode_bootstrap": {
                mode_id: {
                    key: value
                    for key, value in analysis["per_mode_bootstrap"][mode_id].items()
                    if key != "task_clusters"
                }
                for mode_id in MODE_IDS
            },
        },
    }
    return full, public


def main() -> None:
    args = parse_args()
    paths = {
        "flash_non_thinking": args.non_thinking,
        "flash_thinking_high": args.thinking_high,
    }
    for path in (*paths.values(),):
        if not path.is_file():
            raise SystemExit(f"Input summary does not exist: {path}")
    for output in (args.full_output, args.public_output):
        if output.exists():
            raise SystemExit(f"Refusing to overwrite output: {output}")
    summaries = {
        mode_id: json.loads(path.read_text(encoding="utf-8")) for mode_id, path in paths.items()
    }
    project_root = Path(__file__).resolve().parents[1]
    full, public = build_outputs(
        summaries,
        input_paths=paths,
        project_root=project_root,
        iterations=args.iterations,
        seed=args.seed,
    )
    if not full["validity"]["all_selected_checks_passed"]:
        raise RuntimeError("Dual-mode aggregate validity gate failed")
    if _CREDENTIAL_LIKE.search(canonical_json(full)) or _CREDENTIAL_LIKE.search(
        canonical_json(public)
    ):
        raise RuntimeError("Credential-like marker rejected from aggregate evidence")
    write_json_atomic(args.full_output, full, refuse_overwrite=True)
    write_json_atomic(args.public_output, public, refuse_overwrite=True)
    print(
        f"Wrote 864-episode full evidence to {args.full_output} and public evidence to "
        f"{args.public_output}; hypothesis_supported="
        f"{full['analysis']['outcome_gates']['amended_primary_hypothesis_supported']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
