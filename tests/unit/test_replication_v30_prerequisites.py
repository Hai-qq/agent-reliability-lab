from __future__ import annotations

import unittest

from arl_replication_v30.contract import MODEL_BINDINGS
from arl_replication_v30.preflight import RUN_ID
from arl_replication_v30.prerequisites import (
    validate_canary_summary,
    validate_preflight_summary,
    validate_protocol_probe,
)
from arl_replication_v30.specs import replication_catalog_audit


def sources() -> dict[str, object]:
    return {"sha256": "a" * 64, "files": {"synthetic.py": "b" * 64}}


class ReplicationV30PrerequisiteTests(unittest.TestCase):
    def test_preflight_requires_current_source_and_catalog(self) -> None:
        current = sources()
        artifact = {
            "metadata": {
                "run_id": RUN_ID,
                "package_version": "0.30.0",
                "provider_content_persisted": False,
                "source_manifest": current,
            },
            "scripted_preflight": {"episode_count": 432},
            "aggregate": {"episode_count": 432},
            "validity": {"all_selected_checks_passed": True},
            "readiness": {"ready_for_provider_probe": True},
            "replication_catalog": {
                "catalog_sha256": replication_catalog_audit()["catalog_sha256"]
            },
        }
        self.assertTrue(
            validate_preflight_summary(artifact, current_source_manifest=current)["passed"]
        )
        artifact["metadata"]["source_manifest"] = {"sha256": "c" * 64}
        self.assertFalse(
            validate_preflight_summary(artifact, current_source_manifest=current)["passed"]
        )

    def test_probe_and_canary_require_exact_two_model_artifacts(self) -> None:
        current = sources()
        two_calls = [
            {"request_sha256": "1" * 64, "response_sha256": "2" * 64},
            {"request_sha256": "3" * 64, "response_sha256": "4" * 64},
        ]
        calls = two_calls * 3
        probe = {
            "passed": True,
            "metadata": {
                "provider_content_persisted": False,
                "source_manifest": current,
            },
            "catalog_attestation": {"passed": True},
            "preflight_attestation": {"passed": True},
            "repetitions_per_model": 3,
            "logical_call_count": 12,
            "external_attempt_count": 12,
            "by_model": {
                slot: {"binding": MODEL_BINDINGS[slot].as_dict(), "provider_calls": calls}
                for slot in ("flash", "pro")
            },
        }
        self.assertTrue(validate_protocol_probe(probe, current_source_manifest=current)["passed"])
        probe["by_model"]["pro"]["provider_calls"][0]["content"] = "not allowed"
        self.assertFalse(validate_protocol_probe(probe, current_source_manifest=current)["passed"])

        canary = {
            "metadata": {
                "run_id": "arl-opencode-go-replication-canary-v0.30.0",
                "package_version": "0.30.0",
                "provider_content_persisted": False,
                "source_manifest": current,
            },
            "experiment": {
                "episode_count": 36,
                "bindings": {slot: MODEL_BINDINGS[slot].as_dict() for slot in ("flash", "pro")},
            },
            "aggregate": {"episode_count": 36},
            "validity": {
                "all_selected_checks_passed": True,
                "credential_audit": {"passed": True},
            },
            "readiness": {"ready_for_2592_episode_replication": True},
        }
        self.assertTrue(validate_canary_summary(canary, current_source_manifest=current)["passed"])


if __name__ == "__main__":
    unittest.main()
