from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl.core.types import canonical_json
from arl_modelpilot.experiment import (
    bound_pilot_contract,
    compact_model_pilot_summary,
    model_pilot_manifest,
)
from scripts.run_model_pilot import validate_paths


class ModelPilotContractTests(unittest.TestCase):
    def test_manifest_freezes_exact_144_episode_matrix_without_raw_payloads(self) -> None:
        manifest = model_pilot_manifest()
        self.assertEqual(len(manifest.jobs), 144)
        payloads = [job.payload() for job in manifest.jobs]
        matrix = {
            (
                payload["template_id"],
                payload["runtime"],
                payload["condition"],
                payload["sampling_trial"],
            )
            for payload in payloads
        }
        self.assertEqual(len(matrix), 144)
        serialized = canonical_json(manifest.as_dict()).lower()
        self.assertNotIn("user_request", serialized)
        self.assertNotIn("arguments", serialized)
        self.assertNotIn("api_key", serialized)

    def test_bound_contract_opens_pilot_but_not_two_model_main(self) -> None:
        contract = bound_pilot_contract()
        contract.assert_ready("pilot")
        with self.assertRaisesRegex(RuntimeError, "requires 2 exact model binding"):
            contract.assert_ready("main")
        self.assertTrue(contract.model_slots[0].bound)
        self.assertFalse(contract.model_slots[1].bound)

    def test_cli_refuses_overwrite_and_unsafe_layout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-model-pilot-cli-") as temporary:
            root = Path(temporary)
            workspace = root / "study"
            summary = root / "summary.json"
            validate_paths(workspace, summary, resume=False)

            workspace.mkdir()
            with self.assertRaises(SystemExit):
                validate_paths(workspace, summary, resume=False)
            validate_paths(workspace, summary, resume=True)

            with self.assertRaises(SystemExit):
                validate_paths(root / "missing", summary, resume=True)
            with self.assertRaises(SystemExit):
                validate_paths(workspace, workspace / "summary.json", resume=True)

    def test_public_summary_replaces_episode_records_with_digest_link(self) -> None:
        full = {
            "metadata": {"result_scope": "test model pilot"},
            "aggregate": {"episode_count": 2},
            "episodes": [{"episode_id": "a"}, {"episode_id": "b"}],
        }
        compact = compact_model_pilot_summary(full, full_summary_sha256="f" * 64)
        self.assertNotIn("episodes", compact)
        self.assertIn("episodes", full)
        self.assertEqual(compact["episode_evidence"]["episode_count"], 2)
        self.assertEqual(compact["episode_evidence"]["full_summary_sha256"], "f" * 64)
        self.assertEqual(len(compact["episode_evidence"]["episodes_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
