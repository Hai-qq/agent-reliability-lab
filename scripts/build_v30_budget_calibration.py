#!/usr/bin/env python3
"""Recompute the frozen v0.30 budget envelope from the retained v0.29 summary."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from arl_replication_v30.contract import (
    V029_FULL_SUMMARY_SHA256,
    budget_calibration_record,
)
from arl_study.scheduler import file_sha256, write_json_atomic


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def _nearest_rank(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def _rounded(value: float) -> float:
    return round(value, 12)


def _model_metrics(episodes: list[dict[str, Any]], slot: str) -> dict[str, Any]:
    selected = [item for item in episodes if item["model_slot"] == slot]
    costs = [
        sum(call["estimated_cost_usd"] for call in item["provider"]["calls"]) for item in selected
    ]
    result: dict[str, Any] = {
        "episode_count": len(selected),
        "maxima": {
            "input_tokens": max(
                sum(call["input_tokens"] for call in item["provider"]["calls"]) for item in selected
            ),
            "output_tokens": max(
                sum(call["output_tokens"] for call in item["provider"]["calls"])
                for item in selected
            ),
            "logical_calls": max(item["policy"]["model_calls"] for item in selected),
            "external_attempts": max(item["external_network_calls"] for item in selected),
            "usage_value_usd": _rounded(max(costs)),
        },
    }
    if slot == "qwen":
        result["usage_value_quantiles_usd"] = {
            "p95": _rounded(_nearest_rank(costs, 0.95)),
            "p99": _rounded(_nearest_rank(costs, 0.99)),
            "p999": _rounded(_nearest_rank(costs, 0.999)),
            "max": _rounded(max(costs)),
        }
    return result


def build_calibration(summary: dict[str, Any], *, source_sha256: str) -> dict[str, Any]:
    episodes = summary.get("episodes")
    if not isinstance(episodes, list):
        raise ValueError("v0.29 full summary is missing episode records")
    recomputed = {slot: _model_metrics(episodes, slot) for slot in ("flash", "qwen")}
    frozen = budget_calibration_record()
    expected_maxima = frozen["v029_observed_episode_maxima"]
    checks = {
        "exact_frozen_source_hash": source_sha256 == V029_FULL_SUMMARY_SHA256,
        "exact_2592_episode_source": len(episodes) == 2_592,
        "exact_1296_episodes_per_model": all(
            recomputed[slot]["episode_count"] == 1_296 for slot in ("flash", "qwen")
        ),
        "maxima_match_frozen_record": all(
            recomputed[slot]["maxima"] == expected_maxima[slot] for slot in ("flash", "qwen")
        ),
        "qwen_quantiles_match_frozen_record": (
            recomputed["qwen"]["usage_value_quantiles_usd"]
            == frozen["v029_qwen_usage_value_quantiles_usd"]
        ),
        "v029_not_reclassified": frozen["posthoc_v029_reclassification_forbidden"] is True,
    }
    return {
        "calibration": frozen,
        "recomputed_v029": recomputed,
        "checks": checks,
        "passed": all(checks.values()),
    }


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite calibration output: {args.output}")
    source_sha256 = file_sha256(args.input)
    try:
        summary = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("v0.29 calibration source could not be read") from error
    result = build_calibration(summary, source_sha256=source_sha256)
    if not result["passed"]:
        failed = [name for name, passed in result["checks"].items() if not passed]
        raise RuntimeError(f"v0.30 budget calibration failed: {failed}")
    write_json_atomic(args.output, result, refuse_overwrite=True)
    if json.loads(args.output.read_text(encoding="utf-8")) != result:
        raise RuntimeError("Written v0.30 budget calibration did not round-trip")
    print(
        f"Wrote v0.30 budget calibration to {args.output}; "
        f"source_sha256={source_sha256}; passed={result['passed']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
