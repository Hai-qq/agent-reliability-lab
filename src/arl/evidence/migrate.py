"""Fail-closed migration from reviewed private synthetic records to public evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arl.evidence.bundle import EvidenceBundleBuilder
from arl.evidence.redaction import EvidenceRedactor

PRIVATE_INPUT_FILES = frozenset({"study.json", "episodes.jsonl", "provider-calls.jsonl"})


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line:
            raise ValueError(f"blank private record at {path.name}:{line_number}")
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"private record must be an object at {path.name}:{line_number}")
        values.append(value)
    return values


def build_public_bundle(
    private_study_dir: Path,
    public_output: Path,
    *,
    public_state_fields: list[str],
) -> Path:
    """Build a bundle only from the reviewed normalized private interchange format.

    Legacy full summaries and raw provider directories are deliberately unsupported:
    they require an explicit study-specific adapter and review before publication.
    """

    root = private_study_dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"private study directory does not exist: {root}")
    files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    if files != set(PRIVATE_INPUT_FILES):
        raise ValueError(
            "private input file set is not the reviewed interchange format; "
            f"missing={sorted(PRIVATE_INPUT_FILES - files)}, "
            f"extra={sorted(files - PRIVATE_INPUT_FILES)}"
        )
    study = json.loads((root / "study.json").read_text(encoding="utf-8"))
    if not isinstance(study, dict):
        raise ValueError("private study.json must be an object")
    episodes = _read_jsonl(root / "episodes.jsonl")
    events = _read_jsonl(root / "provider-calls.jsonl")
    builder = EvidenceBundleBuilder(
        redactor=EvidenceRedactor(public_state_fields=public_state_fields)
    )
    return builder.build(
        output=public_output,
        study=study,
        episodes=episodes,
        provider_events=events,
    )


def v029_public_evidence_status(project_root: Path) -> dict[str, Any]:
    """Report materialization without reading or reconstructing provider content."""

    root = project_root.resolve()
    required = [
        root / "artifacts/opencode_go_holdout_v29/full-summary.json",
        root / "artifacts/opencode_go_holdout_v29/study",
    ]
    present = [path.exists() for path in required]
    return {
        "study_id": "opencode-go-holdout-v0.29",
        "public_episode_evidence": (
            "MATERIALIZABLE_LOCAL_ONLY" if all(present) else "NOT_MATERIALIZED"
        ),
        "required_local_inputs": [path.relative_to(root).as_posix() for path in required],
        "present": present,
        "generated": False,
        "reason": (
            "All ignored local inputs are present; publication still requires reviewed migration."
            if all(present)
            else "The public checkout lacks the ignored full summary and/or study ledger."
        ),
    }
