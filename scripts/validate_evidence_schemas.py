#!/usr/bin/env python3
"""Validate published schemas and the public smoke bundle with jsonschema."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from arl.evidence.bundle import load_bundle


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    schema_root = root / "schemas/arl-evidence-v1"
    schemas = {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in schema_root.glob("*.schema.json")
    }
    if set(schemas) != {
        "manifest.schema.json",
        "study.schema.json",
        "episode.schema.json",
        "provider-call.schema.json",
        "analysis.schema.json",
    }:
        raise AssertionError("schema file set is incomplete")
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    public = load_bundle(root / "evidence/arl-smoke-v1")
    Draft202012Validator(schemas["manifest.schema.json"]).validate(public["manifest"])
    Draft202012Validator(schemas["study.schema.json"]).validate(public["study"])
    analysis_validator = Draft202012Validator(schemas["analysis.schema.json"])
    analysis_validator.validate(public["analysis"])
    episode_validator = Draft202012Validator(schemas["episode.schema.json"])
    for episode in public["episodes"]:
        episode_validator.validate(episode)
    provider_validator = Draft202012Validator(schemas["provider-call.schema.json"])
    for event in public["provider_events"]:
        provider_validator.validate(event)
    print(f"Validated five schemas and {len(public['episodes'])} public episodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
