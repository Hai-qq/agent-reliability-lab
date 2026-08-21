"""Fail-closed offline verification for ``arl-evidence-v1`` bundles."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json, digest_value
from arl.evidence.bundle import (
    REQUIRED_BUNDLE_FILES,
    canonical_jsonl_bytes,
    compute_aggregate,
    episode_cell,
    load_bundle,
    public_schedule_digest,
    public_task_catalog_digest,
    public_trace_digest,
    sha256_bytes,
)
from arl.evidence.events import count_provider_events, validate_provider_event_ledger
from arl.evidence.redaction import EvidenceRedactor
from arl.evidence.schema import (
    schema_documents,
    validate_analysis,
    validate_episode,
    validate_manifest,
    validate_provider_event,
    validate_study,
)


@dataclass(frozen=True)
class VerificationCheck:
    """One named verifier gate."""

    name: str
    passed: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VerificationReport:
    """Complete verification outcome; validity requires every gate to pass."""

    bundle: str
    valid: bool
    checks: tuple[VerificationCheck, ...]
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "bundle": self.bundle,
            "valid": self.valid,
            "checks": [item.as_dict() for item in self.checks],
            "errors": list(self.errors),
        }


def _read_canonical_object(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if not payload.endswith(b"\n"):
        raise ValueError(f"JSON file must end with LF: {path.name}")
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON file must contain an object: {path.name}")
    if payload != (canonical_json(value) + "\n").encode("utf-8"):
        raise ValueError(f"JSON file is not canonical: {path.name}")
    return value


def _resolve_state_path(state: dict[str, Any], path: str) -> Any:
    current: Any = state
    if not path:
        return current
    for component in path.split("."):
        if not isinstance(current, dict) or component not in current:
            raise ValueError(f"evaluator state path is not public: {path}")
        current = current[component]
    return current


def _verify_evaluator(episode: dict[str, Any]) -> None:
    definitions = episode["evaluator_clause_definitions"]
    outcomes = episode["evaluator_clause_outcomes"]
    by_id = {item.get("clause_id"): item for item in outcomes if isinstance(item, dict)}
    if len(by_id) != len(outcomes):
        raise ValueError(f"duplicate evaluator clause outcome: {episode['episode_id']}")
    for definition in definitions:
        if not isinstance(definition, dict) or not isinstance(definition.get("clause_id"), str):
            raise ValueError(f"invalid evaluator clause definition: {episode['episode_id']}")
        outcome = by_id.get(definition["clause_id"])
        if outcome is None:
            raise ValueError(f"missing evaluator clause outcome: {definition['clause_id']}")
        observed = _resolve_state_path(episode["final_public_state"], definition["state_path"])
        if outcome.get("observed_digest") != digest_value(observed):
            raise ValueError(f"evaluator observed digest mismatch: {definition['clause_id']}")
        operator = definition["operator"]
        if operator == "digest_equals":
            expected_pass = outcome["observed_digest"] == definition["expected_digest"]
        elif operator == "digest_not_equals":
            expected_pass = outcome["observed_digest"] != definition["expected_digest"]
        else:
            raise ValueError(f"unsupported evaluator operator: {operator}")
        if outcome.get("passed") is not expected_pass:
            raise ValueError(f"evaluator clause outcome mismatch: {definition['clause_id']}")
    clause_pass = all(bool(item["passed"]) for item in outcomes)
    expected_safe = clause_pass and episode["severe_side_effect_count"] == 0
    if bool(episode["safe_success"]) is not expected_safe:
        raise ValueError(
            f"safe_success does not match public evaluator evidence: {episode['episode_id']}"
        )


def _run_verification(root: Path) -> list[VerificationCheck]:
    checks: list[VerificationCheck] = []

    manifest = _read_canonical_object(root / "manifest.json")
    validate_manifest(manifest)
    checks.append(VerificationCheck("manifest_schema", True, "strict manifest accepted"))

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("bundle must not contain symbolic links")
    expected_paths = set(manifest["files"])
    if actual_paths != expected_paths or actual_paths != set(REQUIRED_BUNDLE_FILES):
        raise ValueError(
            f"bundle file set mismatch; missing={sorted(expected_paths - actual_paths)}, "
            f"extra={sorted(actual_paths - expected_paths)}"
        )
    for relative_path, descriptor in manifest["files"].items():
        payload = (root / relative_path).read_bytes()
        if len(payload) != descriptor["size"] or sha256_bytes(payload) != descriptor["sha256"]:
            raise ValueError(f"file digest or size mismatch: {relative_path}")
    checks.append(VerificationCheck("file_manifest", True, f"{len(actual_paths)} files verified"))

    for name, expected in schema_documents().items():
        actual = _read_canonical_object(root / "schemas" / name)
        if actual != expected:
            raise ValueError(f"published schema differs from runtime contract: {name}")
    checks.append(VerificationCheck("published_schemas", True, "five schemas match runtime"))

    loaded = load_bundle(root)
    study = loaded["study"]
    episodes = loaded["episodes"]
    provider_events = loaded["provider_events"]
    aggregate = loaded["aggregate"]
    analysis = loaded["analysis"]
    policy = loaded["redaction_policy"]
    validate_study(study)
    validate_analysis(analysis)
    for episode in episodes:
        validate_episode(episode)
    for event in provider_events:
        validate_provider_event(event)
    validate_provider_event_ledger(provider_events)
    checks.append(VerificationCheck("document_schemas", True, "study and ledgers accepted"))

    if not isinstance(policy, dict) or set(policy) != {
        "schema_version",
        "policy_id",
        "unknown_field_behavior",
        "sensitive_value_behavior",
        "synthetic_only",
        "public_state_fields",
        "episode_fields",
        "provider_event_fields",
        "list_item_fields",
        "prohibited_content",
    }:
        raise ValueError("redaction policy has an unknown or missing field")
    redactor = EvidenceRedactor(public_state_fields=policy["public_state_fields"])
    if redactor.policy() != policy:
        raise ValueError("redaction policy is not the canonical deny-by-default policy")
    redactor.validate_document(study, label="study")
    redactor.validate_document(analysis, label="analysis")
    for episode in episodes:
        redactor.validate_episode(episode)
    for event in provider_events:
        redactor.validate_provider_event(event)
    checks.append(VerificationCheck("redaction", True, "allowlists and secret scan passed"))

    if manifest["study_id"] != study["study_id"]:
        raise ValueError("manifest and study IDs differ")
    if (
        manifest["episode_count"] != len(episodes)
        or len(episodes) != study["expected_episode_count"]
    ):
        raise ValueError("episode cardinality mismatch")
    episode_ids = [item["episode_id"] for item in episodes]
    if len(set(episode_ids)) != len(episode_ids):
        raise ValueError("duplicate episode IDs")
    if episode_ids != study["execution_order"]:
        raise ValueError("episode ledger does not follow the frozen schedule")
    cells = [episode_cell(item) for item in episodes]
    if len(set(cells)) != len(cells):
        raise ValueError("duplicate episode cells")
    if sorted(cells) != sorted(study["expected_cells"]):
        raise ValueError("missing or extra episode cells")
    if any(item["trace_digest"] != public_trace_digest(item) for item in episodes):
        raise ValueError("episode trace digest does not bind its materialized public trace")
    if public_schedule_digest(episodes) != study["schedule_digest"]:
        raise ValueError("schedule digest is not reproducible from the episode ledger")
    if public_task_catalog_digest(study, episodes) != study["task_catalog_digest"]:
        raise ValueError("task catalog digest is not reproducible from the episode ledger")
    if any(item["source_manifest_digest"] != study["source_manifest_digest"] for item in episodes):
        raise ValueError("episode source manifest digest differs from the study")
    checks.append(VerificationCheck("episode_cardinality", True, f"{len(episodes)} cells unique"))

    if (
        manifest["provider_event_count"] != len(provider_events)
        or len(provider_events) != study["expected_provider_event_count"]
    ):
        raise ValueError("provider event cardinality mismatch")
    logical_ids = {item["logical_call_id"] for item in provider_events}
    episode_logical_ids = {
        call_id for episode in episodes for call_id in episode["logical_provider_call_ids"]
    }
    if logical_ids != episode_logical_ids:
        raise ValueError("provider event logical-call linkage mismatch")
    counts = count_provider_events(provider_events).as_dict()
    checks.append(VerificationCheck("provider_accounting", True, canonical_json(counts)))

    episode_bytes = canonical_jsonl_bytes(episodes)
    provider_bytes = canonical_jsonl_bytes(provider_events)
    expected_links = {
        "study_digest": digest_value(study),
        "episode_ledger_digest": sha256_bytes(episode_bytes),
        "provider_event_ledger_digest": sha256_bytes(provider_bytes),
        "aggregate_digest": digest_value(aggregate),
        "analysis_digest": digest_value(analysis),
        "redaction_policy_digest": digest_value(policy),
    }
    for field, expected_digest in expected_links.items():
        if manifest[field] != expected_digest:
            raise ValueError(f"manifest cross-file digest mismatch: {field}")
    for field in ("source_manifest_digest", "schedule_digest", "task_catalog_digest"):
        if manifest[field] != study[field]:
            raise ValueError(f"study/manifest digest mismatch: {field}")
    if analysis["episode_ledger_digest"] != manifest["episode_ledger_digest"]:
        raise ValueError("analysis input ledger digest mismatch")
    if analysis["aggregate_digest"] != manifest["aggregate_digest"]:
        raise ValueError("analysis aggregate digest mismatch")
    checks.append(VerificationCheck("cross_file_digests", True, "all digest links verified"))

    recomputed = compute_aggregate(episodes)
    if aggregate != recomputed:
        raise ValueError("aggregate is not reproducible from the public ledger")
    checks.append(VerificationCheck("aggregate_recomputation", True, "aggregate reproduced"))

    for episode in episodes:
        _verify_evaluator(episode)
    checks.append(
        VerificationCheck("evaluator_recomputation", True, f"{len(episodes)} episodes checked")
    )
    return checks


def verify_bundle(path: Path) -> VerificationReport:
    """Verify a bundle without network access and return all available evidence."""

    root = path.resolve()
    try:
        checks = _run_verification(root)
    except Exception as error:  # Fail closed at the public boundary.
        return VerificationReport(
            bundle=str(root),
            valid=False,
            checks=tuple(locals().get("checks", [])),
            errors=(f"{type(error).__name__}: {error}",),
        )
    return VerificationReport(bundle=str(root), valid=True, checks=tuple(checks), errors=())
