"""Golden-trace schema, chain, digest, and mutation checks."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json

TRACE_FIELDS = {
    "actor",
    "episode_id",
    "error_code",
    "event_id",
    "event_type",
    "fault_id",
    "input_digest",
    "latency_ms",
    "monetary_cost",
    "output_digest",
    "parent_event_id",
    "run_id",
    "schema_version",
    "seed",
    "state_hash_after",
    "state_hash_before",
    "task_id",
    "timestamp_logical",
    "token_usage",
    "tool_name",
}
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_PAYLOAD_MARKERS = (b"@synthetic.invalid", b'"participants"', b'"recipients"')


def _jsonl_bytes(events: list[dict[str, Any]]) -> bytes:
    return b"".join((canonical_json(event) + "\n").encode("utf-8") for event in events)


def verify_trace_bytes(data: bytes, expected: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected["sha256"]:
        errors.append("sha256_mismatch")
    try:
        events = [json.loads(line) for line in data.decode("utf-8").splitlines()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {
            "passed": False,
            "errors": [*errors, "jsonl_invalid"],
            "sha256": actual_sha256,
            "event_count": 0,
        }
    if len(events) != expected["event_count"]:
        errors.append("event_count_mismatch")
    if not events:
        errors.append("trace_empty")
    elif any(not isinstance(event, dict) for event in events):
        errors.append("event_not_object")
    else:
        if any(set(event) != TRACE_FIELDS for event in events):
            errors.append("unexpected_fields")
        event_ids = [event.get("event_id") for event in events]
        if any(not isinstance(event_id, str) for event_id in event_ids):
            errors.append("event_id_format_invalid")
        elif len(event_ids) != len(set(event_ids)):
            errors.append("event_ids_not_unique")
        if events[0].get("parent_event_id") is not None or any(
            current.get("parent_event_id") != previous.get("event_id")
            for previous, current in zip(events, events[1:], strict=False)
        ):
            errors.append("parent_chain_invalid")
        if any(
            previous.get("state_hash_after") != current.get("state_hash_before")
            for previous, current in zip(events, events[1:], strict=False)
        ):
            errors.append("state_chain_invalid")
        if events[0].get("event_type") != "episode_started":
            errors.append("first_event_invalid")
        if events[-1].get("event_type") != "evaluation_completed":
            errors.append("last_event_invalid")
        if any(event.get("episode_id") != expected["episode_id"] for event in events):
            errors.append("episode_id_mismatch")
        if any(event.get("task_id") != expected["task_id"] for event in events):
            errors.append("task_id_mismatch")
        if any(event.get("seed") != expected["seed"] for event in events):
            errors.append("seed_mismatch")
        event_type_values = [event.get("event_type") for event in events]
        if any(not isinstance(event_type, str) for event_type in event_type_values):
            errors.append("event_type_format_invalid")
        event_types = {
            event_type for event_type in event_type_values if isinstance(event_type, str)
        }
        if not set(expected["required_event_types"]).issubset(event_types):
            errors.append("required_event_type_missing")
        if set(expected["forbidden_event_types"]) & event_types:
            errors.append("forbidden_event_type_present")
        digest_fields = (
            event.get(field) for event in events for field in ("input_digest", "output_digest")
        )
        state_hashes = (
            event.get(field)
            for event in events
            for field in ("state_hash_before", "state_hash_after")
        )
        if any(
            value is not None
            and (not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value))
            for value in digest_fields
        ):
            errors.append("digest_format_invalid")
        if any(
            not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value)
            for value in state_hashes
        ):
            errors.append("state_hash_format_invalid")
    if any(marker in data for marker in _FORBIDDEN_PAYLOAD_MARKERS):
        errors.append("raw_payload_present")
    return {
        "passed": not errors,
        "errors": sorted(set(errors)),
        "sha256": actual_sha256,
        "event_count": len(events),
    }


def verify_golden_suite(project_root: Path, spec_path: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    summary_path = project_root / spec["summary_file"]
    summary_bytes = summary_path.read_bytes()
    summary_sha256 = hashlib.sha256(summary_bytes).hexdigest()
    summary = json.loads(summary_bytes)
    episode_by_trace = {episode["trace_file"]: episode for episode in summary["episodes"]}
    traces: list[dict[str, Any]] = []
    for expected in spec["traces"]:
        trace_path = project_root / expected["path"]
        result = verify_trace_bytes(trace_path.read_bytes(), expected)
        episode = episode_by_trace.get(trace_path.name)
        metadata_matches = episode is not None and all(
            episode[key] == expected[key]
            for key in ("episode_id", "task_id", "seed", "runtime", "condition")
        )
        traces.append(
            {
                "path": expected["path"],
                **result,
                "summary_metadata_matches": metadata_matches,
                "passed": result["passed"] and metadata_matches,
            }
        )

    mutation_source = project_root / spec["traces"][1]["path"]
    source_events = [json.loads(line) for line in mutation_source.read_text().splitlines()]
    expected = spec["traces"][1]

    parent_mutation = [dict(event) for event in source_events]
    parent_mutation[1]["parent_event_id"] = "tampered-parent"
    parent_result = verify_trace_bytes(_jsonl_bytes(parent_mutation), expected)

    field_mutation = [dict(event) for event in source_events]
    field_mutation[1]["arguments"] = {"forbidden": "payload"}
    field_result = verify_trace_bytes(_jsonl_bytes(field_mutation), expected)

    digest_mutation = [dict(event) for event in source_events]
    digest_mutation[-1]["output_digest"] = "0" * 64
    digest_result = verify_trace_bytes(_jsonl_bytes(digest_mutation), expected)

    mutations = {
        "parent_chain_tamper": {
            "rejected": not parent_result["passed"],
            "errors": parent_result["errors"],
            "passed": "parent_chain_invalid" in parent_result["errors"],
        },
        "raw_field_injection": {
            "rejected": not field_result["passed"],
            "errors": field_result["errors"],
            "passed": "unexpected_fields" in field_result["errors"],
        },
        "content_digest_tamper": {
            "rejected": not digest_result["passed"],
            "errors": digest_result["errors"],
            "passed": "sha256_mismatch" in digest_result["errors"],
        },
    }
    summary_matches = summary_sha256 == spec["summary_sha256"]
    return {
        "spec_file": str(spec_path.relative_to(project_root)),
        "summary_file": spec["summary_file"],
        "summary_sha256": summary_sha256,
        "summary_matches": summary_matches,
        "trace_count": len(traces),
        "traces": traces,
        "mutations": mutations,
        "passed": (
            summary_matches
            and all(trace["passed"] for trace in traces)
            and all(mutation["passed"] for mutation in mutations.values())
        ),
    }
