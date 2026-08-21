from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from arl.core.types import canonical_json
from arl.evidence.bundle import (
    EvidenceBundleBuilder,
    canonical_json_bytes,
    deterministic_gzip,
    load_bundle,
    public_trace_digest,
)
from arl.evidence.redaction import EvidenceRedactor, RedactionError
from arl.evidence.schema import SchemaValidationError, validate_episode
from arl.evidence.verify import verify_bundle
from arl.studies.smoke import PUBLIC_STATE_FIELDS, smoke_inputs


class EvidenceV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.study, self.episodes = smoke_inputs()
        self.redactor = EvidenceRedactor(public_state_fields=PUBLIC_STATE_FIELDS)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, name: str, episodes: list[dict[str, object]] | None = None) -> Path:
        output = self.root / name
        EvidenceBundleBuilder(redactor=self.redactor).build(
            output=output,
            study=copy.deepcopy(self.study),
            episodes=copy.deepcopy(episodes or self.episodes),
        )
        return output

    def test_canonical_json_and_deterministic_gzip(self) -> None:
        value = {"z": 1, "é": [3, 2, 1], "a": True}
        self.assertEqual(canonical_json_bytes(value), (canonical_json(value) + "\n").encode())
        self.assertEqual(deterministic_gzip(b"evidence\n"), deterministic_gzip(b"evidence\n"))
        self.assertEqual(deterministic_gzip(b"evidence\n")[4:8], b"\x00\x00\x00\x00")

    def test_bundle_is_byte_reproducible_and_verifies(self) -> None:
        first = self.build("first")
        second = self.build("second")
        first_files = {
            path.relative_to(first).as_posix(): path.read_bytes()
            for path in first.rglob("*")
            if path.is_file()
        }
        second_files = {
            path.relative_to(second).as_posix(): path.read_bytes()
            for path in second.rglob("*")
            if path.is_file()
        }
        self.assertEqual(first_files, second_files)
        report = verify_bundle(first)
        self.assertTrue(report.valid, report.errors)
        loaded = load_bundle(first)
        self.assertEqual(loaded["aggregate"]["episode_count"], 54)
        self.assertEqual(loaded["aggregate"]["safe_pass_at_3_eligible_group_count"], 18)
        self.assertEqual(loaded["aggregate"]["safe_pass_at_3_pass_count"], 14)

    def test_schema_rejects_missing_and_unknown_episode_fields(self) -> None:
        missing = copy.deepcopy(self.episodes[0])
        missing.pop("episode_id")
        with self.assertRaises(SchemaValidationError):
            validate_episode(missing)
        unknown = copy.deepcopy(self.episodes[0])
        unknown["new_private_field"] = "value"
        with self.assertRaises(SchemaValidationError):
            validate_episode(unknown)

    def test_redactor_rejects_unknown_state_and_secret_mutations(self) -> None:
        unknown = copy.deepcopy(self.episodes[0])
        unknown["final_public_state"]["private_record"] = "synthetic"
        with self.assertRaises(RedactionError):
            self.redactor.validate_episode(unknown)
        unknown_nested = copy.deepcopy(self.episodes[0])
        unknown_nested["semantic_decisions"][0]["confidence"] = 0.9
        with self.assertRaises(RedactionError):
            self.redactor.validate_episode(unknown_nested)
        mutations = [
            ("api_key", "sk-example-secret-1234567890"),
            ("note", "Authorization: Bearer abcdefghijklmnop"),
            ("note", "owner@example.com"),
            ("cookie", "session=value"),
            ("note", "-----BEGIN PRIVATE KEY-----"),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                episode = copy.deepcopy(self.episodes[0])
                episode["semantic_decisions"][0][field] = value
                with self.assertRaises(RedactionError):
                    self.redactor.validate_episode(episode)

    def test_builder_rejects_missing_duplicate_and_extra_episodes(self) -> None:
        with self.assertRaises(ValueError):
            self.build("missing", self.episodes[:-1])
        duplicate = copy.deepcopy(self.episodes)
        duplicate[-1]["episode_id"] = duplicate[0]["episode_id"]
        with self.assertRaises(ValueError):
            self.build("duplicate", duplicate)
        extra = copy.deepcopy(self.episodes)
        extra.append(copy.deepcopy(extra[-1]))
        extra[-1]["episode_id"] = "extra-episode"
        extra[-1]["execution_order_index"] = len(extra) - 1
        with self.assertRaises(ValueError):
            self.build("extra", extra)

    def test_verifier_detects_manifest_hash_and_analysis_input_mutations(self) -> None:
        original = self.build("original")
        hash_mutation = self.root / "hash-mutation"
        shutil.copytree(original, hash_mutation)
        aggregate_path = hash_mutation / "aggregate.json"
        aggregate_path.write_bytes(aggregate_path.read_bytes() + b" ")
        self.assertFalse(verify_bundle(hash_mutation).valid)

        analysis_mutation = self.root / "analysis-mutation"
        shutil.copytree(original, analysis_mutation)
        analysis_path = analysis_mutation / "analysis.json"
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        analysis["episode_ledger_digest"] = "0" * 64
        analysis_path.write_text(canonical_json(analysis) + "\n", encoding="utf-8", newline="\n")
        self.assertFalse(verify_bundle(analysis_mutation).valid)

    def test_verifier_detects_evaluator_mutation_even_with_rehashed_manifest(self) -> None:
        original = self.build("original-evaluator")
        public = load_bundle(original)
        mutated = copy.deepcopy(public["episodes"])
        mutated[0]["evaluator_clause_outcomes"][0]["passed"] = not mutated[0][
            "evaluator_clause_outcomes"
        ][0]["passed"]
        mutated[0]["trace_digest"] = public_trace_digest(mutated[0])
        output = self.root / "bad-evaluator"
        EvidenceBundleBuilder(redactor=self.redactor).build(
            output=output,
            study=public["study"],
            episodes=mutated,
        )
        report = verify_bundle(output)
        self.assertFalse(report.valid)
        self.assertIn("evaluator clause outcome mismatch", report.errors[0])


if __name__ == "__main__":
    unittest.main()
