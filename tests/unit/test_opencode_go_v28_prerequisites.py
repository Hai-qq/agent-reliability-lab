from __future__ import annotations

import unittest

from arl_opencode_v28.contract import MODEL_BINDINGS, QWEN_BINDING
from arl_opencode_v28.prerequisites import (
    PROBE_SOURCE_PATHS,
    validate_canary_summary,
    validate_protocol_probe,
)


def source_manifest() -> dict[str, object]:
    return {
        "sha256": "a" * 64,
        "files": {path: f"{index:064x}" for index, path in enumerate(PROBE_SOURCE_PATHS)},
    }


class OpenCodeGoV28PrerequisiteTests(unittest.TestCase):
    def test_protocol_probe_requires_current_digest_only_evidence(self) -> None:
        sources = source_manifest()
        artifact = {
            "passed": True,
            "binding": QWEN_BINDING.as_dict(),
            "catalog_attestation": {"passed": True},
            "metadata": {
                "provider_content_persisted": False,
                "source_manifest": sources,
            },
            "provider_calls": [
                {"request_sha256": "1" * 64, "response_sha256": "2" * 64},
                {"request_sha256": "3" * 64, "response_sha256": "4" * 64},
            ],
        }
        self.assertTrue(
            validate_protocol_probe(artifact, current_source_manifest=sources)["passed"]
        )
        artifact["provider_calls"][0]["content"] = "not allowed"
        self.assertFalse(
            validate_protocol_probe(artifact, current_source_manifest=sources)["passed"]
        )

    def test_formal_requires_current_valid_canary(self) -> None:
        sources = source_manifest()
        artifact = {
            "metadata": {
                "run_id": "arl-opencode-go-flash-qwen-canary-v0.28.0",
                "package_version": "0.28.0",
                "provider_content_persisted": False,
                "source_manifest": sources,
            },
            "experiment": {
                "episode_count": 12,
                "bindings": {slot: MODEL_BINDINGS[slot].as_dict() for slot in ("flash", "qwen")},
            },
            "aggregate": {"episode_count": 12},
            "validity": {
                "all_selected_checks_passed": True,
                "credential_audit": {"passed": True},
            },
            "readiness": {"ready_for_864_episode_main": True},
        }
        self.assertTrue(
            validate_canary_summary(artifact, current_source_manifest=sources)["passed"]
        )
        artifact["readiness"]["ready_for_864_episode_main"] = False
        self.assertFalse(
            validate_canary_summary(artifact, current_source_manifest=sources)["passed"]
        )


if __name__ == "__main__":
    unittest.main()
