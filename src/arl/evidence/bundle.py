"""Deterministic construction and loading of public evidence bundles."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json, digest_value
from arl.evidence.events import validate_provider_event_ledger
from arl.evidence.redaction import EvidenceRedactor
from arl.evidence.schema import (
    SCHEMA_VERSION,
    schema_documents,
    validate_analysis,
    validate_episode,
    validate_manifest,
    validate_provider_event,
    validate_study,
)

BUNDLE_VERSION = "arl-public-bundle-v1"
REQUIRED_BUNDLE_FILES = frozenset(
    {
        "study.json",
        "episodes.jsonl.gz",
        "provider-calls.jsonl.gz",
        "aggregate.json",
        "analysis.json",
        "redaction-policy.json",
        "README.md",
        "schemas/manifest.schema.json",
        "schemas/study.schema.json",
        "schemas/episode.schema.json",
        "schemas/provider-call.schema.json",
        "schemas/analysis.schema.json",
    }
)


def sha256_bytes(value: bytes) -> str:
    """Return a lowercase SHA-256 digest."""

    return hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize canonical JSON with one terminal LF."""

    return (canonical_json(value) + "\n").encode("utf-8")


def canonical_jsonl_bytes(values: Iterable[Mapping[str, Any]]) -> bytes:
    """Serialize canonical JSON Lines with LF on every platform."""

    return b"".join(canonical_json_bytes(value) for value in values)


def deterministic_gzip(value: bytes) -> bytes:
    """Compress bytes with a fixed header, timestamp, level, and filename."""

    output = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", compresslevel=9, fileobj=output, mtime=0) as handle:
        handle.write(value)
    return output.getvalue()


def read_gzip_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a gzip JSONL ledger, rejecting blank lines and non-object entries."""

    try:
        payload = gzip.decompress(path.read_bytes())
        text = payload.decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise ValueError(f"invalid gzip JSONL: {path.name}") from error
    if text and not text.endswith("\n"):
        raise ValueError(f"JSONL must end with LF: {path.name}")
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise ValueError(f"blank JSONL record at {path.name}:{line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON at {path.name}:{line_number}") from error
        if not isinstance(value, dict):
            raise ValueError(f"JSONL record must be an object at {path.name}:{line_number}")
        if canonical_json(value) != line:
            raise ValueError(f"non-canonical JSON at {path.name}:{line_number}")
        values.append(value)
    return values


def episode_cell(episode: Mapping[str, Any]) -> str:
    """Return the unique frozen cell identifier for one episode."""

    dimensions = {
        "condition": episode["condition"],
        "environment_seed": episode["environment_seed"],
        "model_binding": episode["model_binding"],
        "runtime": episode["runtime"],
        "sampling_trial": episode["sampling_trial"],
        "task_template_id": episode["task_template_id"],
    }
    return canonical_json(dimensions)


def public_trace_digest(episode: Mapping[str, Any]) -> str:
    """Digest the normalized public trace that is materialized in an episode."""

    return digest_value(
        {
            "episode_id": episode["episode_id"],
            "request_digest": episode["request_digest"],
            "policy_digest": episode["policy_digest"],
            "initial_state_digest": episode["initial_state_digest"],
            "final_state_digest": episode["final_state_digest"],
            "semantic_decisions": episode["semantic_decisions"],
            "tool_calls": episode["tool_calls"],
            "tool_results": episode["tool_results"],
            "fault_injection_events": episode["fault_injection_events"],
            "runtime_recovery_events": episode["runtime_recovery_events"],
            "evaluator_clause_outcomes": episode["evaluator_clause_outcomes"],
            "terminal_reason": episode["terminal_reason"],
        }
    )


def public_schedule_digest(episodes: Sequence[Mapping[str, Any]]) -> str:
    """Recompute the frozen schedule digest from ledger order and public cells."""

    return digest_value(
        [
            {
                "task_template_id": episode["task_template_id"],
                "environment_seed": episode["environment_seed"],
                "sampling_trial": episode["sampling_trial"],
                "runtime": episode["runtime"],
                "condition": episode["condition"],
                "model_slot": episode["model_binding"],
            }
            for episode in episodes
        ]
    )


def public_task_catalog_digest(
    study: Mapping[str, Any], episodes: Sequence[Mapping[str, Any]]
) -> str:
    """Bind the declared catalog version to every task identifier in the ledger."""

    return digest_value(
        {
            "task_catalog_version": study["task_catalog_version"],
            "task_template_ids": sorted({episode["task_template_id"] for episode in episodes}),
        }
    )


def compute_aggregate(episodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Recompute public aggregate counts exclusively from the episode ledger."""

    by_cell: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    by_safe_pass_group: dict[tuple[str, int, str, str, str], list[Mapping[str, Any]]] = defaultdict(
        list
    )
    for episode in episodes:
        aggregate_key = (
            str(episode["runtime"]),
            str(episode["condition"]),
            str(episode["model_binding"]),
            str(episode["domain"]),
        )
        counts = by_cell[aggregate_key]
        counts["episodes"] += 1
        counts["task_success"] += int(bool(episode["task_success"]))
        counts["safe_success"] += int(bool(episode["safe_success"]))
        counts["severe_side_effects"] += int(episode["severe_side_effect_count"])
        safe_pass_key = (
            str(episode["task_template_id"]),
            int(episode["environment_seed"]),
            str(episode["runtime"]),
            str(episode["condition"]),
            str(episode["model_binding"]),
        )
        by_safe_pass_group[safe_pass_key].append(episode)
    rows = []
    for aggregate_key in sorted(by_cell):
        counts = by_cell[aggregate_key]
        denominator = counts["episodes"]
        rows.append(
            {
                "runtime": aggregate_key[0],
                "condition": aggregate_key[1],
                "model_binding": aggregate_key[2],
                "domain": aggregate_key[3],
                "episode_count": denominator,
                "task_success_count": counts["task_success"],
                "safe_success_count": counts["safe_success"],
                "severe_side_effect_count": counts["severe_side_effects"],
                "task_success_rate": counts["task_success"] / denominator,
                "safe_success_rate": counts["safe_success"] / denominator,
            }
        )
    safe_pass_rows = []
    for safe_pass_key in sorted(by_safe_pass_group):
        group = by_safe_pass_group[safe_pass_key]
        trials = sorted(int(item["sampling_trial"]) for item in group)
        complete = trials == [0, 1, 2]
        safe_pass_rows.append(
            {
                "task_template_id": safe_pass_key[0],
                "environment_seed": safe_pass_key[1],
                "runtime": safe_pass_key[2],
                "condition": safe_pass_key[3],
                "model_binding": safe_pass_key[4],
                "sampling_trials": trials,
                "complete": complete,
                "safe_pass_at_3": (
                    all(bool(item["safe_success"]) for item in group) if complete else None
                ),
            }
        )
    eligible_safe_pass_rows = [item for item in safe_pass_rows if item["complete"]]
    return {
        "schema_version": SCHEMA_VERSION,
        "episode_count": len(episodes),
        "unique_episode_count": len({str(item["episode_id"]) for item in episodes}),
        "unique_cell_count": len({episode_cell(item) for item in episodes}),
        "rows": rows,
        "safe_pass_at_3_definition": (
            "all sampling trials 0, 1, and 2 within a task-template, environment-seed, "
            "runtime, condition, and model-binding group must be SafeSuccess"
        ),
        "safe_pass_at_3_eligible_group_count": len(eligible_safe_pass_rows),
        "safe_pass_at_3_pass_count": sum(
            item["safe_pass_at_3"] is True for item in eligible_safe_pass_rows
        ),
        "safe_pass_at_3_rows": safe_pass_rows,
    }


def _default_analysis(
    study: Mapping[str, Any], episode_ledger_digest: str, aggregate: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "study_id": study["study_id"],
        "analysis_status": str(study["analysis_mode"]),
        "episode_ledger_digest": episode_ledger_digest,
        "aggregate_digest": digest_value(aggregate),
        "estimands": {},
        "limitations": [
            "Generated from the public ledger only.",
            "Scripted synthetic outcomes are not model-performance claims.",
        ],
    }


def _write_new_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


class EvidenceBundleBuilder:
    """Build a byte-reproducible, fail-closed public evidence directory."""

    def __init__(self, *, redactor: EvidenceRedactor) -> None:
        self.redactor = redactor

    def build(
        self,
        *,
        output: Path,
        study: dict[str, Any],
        episodes: Sequence[dict[str, Any]],
        provider_events: Sequence[dict[str, Any]] = (),
        analysis: dict[str, Any] | None = None,
    ) -> Path:
        """Validate and atomically materialize a new public bundle.

        ``output`` must not exist. This prevents a publication step from
        overwriting evidence that may already have been cited.
        """

        if output.exists():
            raise FileExistsError(f"refusing to overwrite evidence bundle: {output}")
        validate_study(study)
        self.redactor.validate_document(study, label="study")
        if study["provider_calls_permitted"] is not False:
            raise ValueError("public smoke/migration build must not permit provider calls")

        ordered_episodes = sorted(episodes, key=lambda item: item["execution_order_index"])
        for episode in ordered_episodes:
            validate_episode(episode)
            self.redactor.validate_episode(episode)
            if episode["study_id"] != study["study_id"]:
                raise ValueError("episode study_id does not match study")
            if episode["trace_digest"] != public_trace_digest(episode):
                raise ValueError("episode trace digest does not bind its public trace")
        expected_indices = list(range(len(ordered_episodes)))
        actual_indices = [item["execution_order_index"] for item in ordered_episodes]
        if actual_indices != expected_indices:
            raise ValueError("execution_order_index must be contiguous from zero")
        episode_ids = [item["episode_id"] for item in ordered_episodes]
        if len(set(episode_ids)) != len(episode_ids):
            raise ValueError("episode_id values must be unique")
        if len(ordered_episodes) != study["expected_episode_count"]:
            raise ValueError("episode count does not match study contract")
        actual_cells = [episode_cell(item) for item in ordered_episodes]
        if len(set(actual_cells)) != len(actual_cells):
            raise ValueError("episode cells must be unique")
        if sorted(actual_cells) != sorted(study["expected_cells"]):
            raise ValueError("episode cell set does not match study contract")
        if episode_ids != study["execution_order"]:
            raise ValueError("episode order does not match frozen execution_order")
        if public_schedule_digest(ordered_episodes) != study["schedule_digest"]:
            raise ValueError("schedule digest is not reproducible from the episode ledger")
        if public_task_catalog_digest(study, ordered_episodes) != study["task_catalog_digest"]:
            raise ValueError("task catalog digest is not reproducible from the episode ledger")
        if any(
            item["source_manifest_digest"] != study["source_manifest_digest"]
            for item in ordered_episodes
        ):
            raise ValueError("episode source manifest digest differs from the study")

        ordered_events = sorted(provider_events, key=lambda item: item["sequence_index"])
        validate_provider_event_ledger(ordered_events)
        for event in ordered_events:
            validate_provider_event(event)
            self.redactor.validate_provider_event(event)
            if event["episode_id"] not in set(episode_ids):
                raise ValueError("provider event references an unknown episode")
        if len(ordered_events) != study["expected_provider_event_count"]:
            raise ValueError("provider event count does not match study contract")
        episode_bytes = canonical_jsonl_bytes(ordered_episodes)
        provider_bytes = canonical_jsonl_bytes(ordered_events)
        episode_digest = sha256_bytes(episode_bytes)
        aggregate = compute_aggregate(ordered_episodes)
        selected_analysis = analysis or _default_analysis(study, episode_digest, aggregate)
        validate_analysis(selected_analysis)
        self.redactor.validate_document(selected_analysis, label="analysis")
        if selected_analysis["study_id"] != study["study_id"]:
            raise ValueError("analysis study_id does not match study")
        if selected_analysis["episode_ledger_digest"] != episode_digest:
            raise ValueError("analysis episode ledger digest mismatch")
        if selected_analysis["aggregate_digest"] != digest_value(aggregate):
            raise ValueError("analysis aggregate digest mismatch")

        policy = self.redactor.policy()
        documents: dict[str, bytes] = {
            "study.json": canonical_json_bytes(study),
            "episodes.jsonl.gz": deterministic_gzip(episode_bytes),
            "provider-calls.jsonl.gz": deterministic_gzip(provider_bytes),
            "aggregate.json": canonical_json_bytes(aggregate),
            "analysis.json": canonical_json_bytes(selected_analysis),
            "redaction-policy.json": canonical_json_bytes(policy),
            "README.md": (
                "# Public ARL evidence bundle\n\n"
                f"Study: `{study['study_id']}`\n\n"
                f"Schema: `{SCHEMA_VERSION}`\n\n"
                "Verify offline with `arl verify <this-directory>`. The manifest "
                "binds every public file except itself. Ledger digests refer to the "
                "canonical uncompressed JSONL bytes. No raw prompt, response, reasoning, "
                "credential, or non-allowlisted state is included.\n"
            ).encode(),
        }
        documents.update(
            {
                f"schemas/{name}": canonical_json_bytes(document)
                for name, document in schema_documents().items()
            }
        )
        if set(documents) != REQUIRED_BUNDLE_FILES:
            raise RuntimeError("internal bundle file contract is incomplete")

        descriptors = {
            name: {"sha256": sha256_bytes(payload), "size": len(payload)}
            for name, payload in sorted(documents.items())
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "bundle_version": BUNDLE_VERSION,
            "study_id": study["study_id"],
            "files": descriptors,
            "episode_count": len(ordered_episodes),
            "provider_event_count": len(ordered_events),
            "study_digest": digest_value(study),
            "episode_ledger_digest": episode_digest,
            "provider_event_ledger_digest": sha256_bytes(provider_bytes),
            "aggregate_digest": digest_value(aggregate),
            "analysis_digest": digest_value(selected_analysis),
            "redaction_policy_digest": digest_value(policy),
            "source_manifest_digest": study["source_manifest_digest"],
            "schedule_digest": study["schedule_digest"],
            "task_catalog_digest": study["task_catalog_digest"],
        }
        validate_manifest(manifest)

        output_parent = output.resolve().parent
        output_parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output_parent))
        try:
            for name, payload in sorted(documents.items()):
                _write_new_file(temporary / name, payload)
            _write_new_file(temporary / "manifest.json", canonical_json_bytes(manifest))
            os.replace(temporary, output.resolve())
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return output


def load_bundle(path: Path) -> dict[str, Any]:
    """Load the public bundle documents without treating them as verified."""

    root = path.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"bundle manifest does not exist: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("bundle manifest must be an object")
    return {
        "root": root,
        "manifest": manifest,
        "study": json.loads((root / "study.json").read_text(encoding="utf-8")),
        "episodes": read_gzip_jsonl(root / "episodes.jsonl.gz"),
        "provider_events": read_gzip_jsonl(root / "provider-calls.jsonl.gz"),
        "aggregate": json.loads((root / "aggregate.json").read_text(encoding="utf-8")),
        "analysis": json.loads((root / "analysis.json").read_text(encoding="utf-8")),
        "redaction_policy": json.loads(
            (root / "redaction-policy.json").read_text(encoding="utf-8")
        ),
    }
