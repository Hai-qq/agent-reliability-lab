from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_study.experiment import (
    INTERRUPT_AFTER,
    build_study_summary,
    execute_resilience_job,
    resilience_study_manifest,
)
from arl_study.scheduler import StudyScheduler
from arl_study.viewer import build_trace_viewer

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StudyValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-v10-validity-")
        cls.workspace = Path(cls._temporary.name) / "study"
        manifest = resilience_study_manifest()
        initial = StudyScheduler.create(cls.workspace, manifest)
        cls.interrupted_report = initial.run(
            execute_resilience_job,
            max_new_jobs=INTERRUPT_AFTER,
        )
        cls.interrupted_summary = build_study_summary(
            initial,
            cls.interrupted_report,
            PROJECT_ROOT,
        )
        resumed = StudyScheduler.resume(cls.workspace, manifest)
        cls.final_report = resumed.run(execute_resilience_job)
        cls.final_summary = build_study_summary(resumed, cls.final_report, PROJECT_ROOT)
        cls.viewer = build_trace_viewer(cls.final_summary, cls.workspace / "traces")
        cls.state = resumed.state

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_interrupted_checkpoint_is_complete_and_reference_equivalent(self) -> None:
        self.assertEqual(self.interrupted_report.status, "interrupted")
        self.assertEqual(self.interrupted_report.completed_count, INTERRUPT_AFTER)
        self.assertEqual(self.interrupted_report.pending_count, 36 - INTERRUPT_AFTER)
        self.assertTrue(self.interrupted_summary["validity"]["all_selected_checks_passed"])
        self.assertEqual(len(self.interrupted_summary["episodes"]), INTERRUPT_AFTER)

    def test_resume_preserves_completed_jobs_and_finishes_once(self) -> None:
        report = self.final_report
        self.assertEqual(report.status, "complete")
        self.assertEqual(report.completed_count, 36)
        self.assertEqual(report.new_jobs_completed, 36 - INTERRUPT_AFTER)
        self.assertTrue(report.preexisting_results_preserved)
        self.assertEqual(report.preexisting_completed_count, INTERRUPT_AFTER)
        self.assertEqual(
            report.preexisting_results_sha256_before, report.preexisting_results_sha256_after
        )
        self.assertTrue(all(entry["attempt_count"] == 1 for entry in self.state["jobs"].values()))
        self.assertEqual(len(self.state["history"]), 77)

    def test_final_validity_and_historical_manifests(self) -> None:
        validity = self.final_summary["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(validity["complete_matrix"]["passed"])
        self.assertTrue(validity["reference_equivalence"]["passed"])
        self.assertTrue(validity["historical_source_manifests"]["passed"])
        self.assertEqual(len(validity["historical_source_manifests"]["increments"]), 9)
        self.assertEqual(len(list((self.workspace / "traces").glob("*.jsonl"))), 36)

    def test_viewer_is_self_contained_and_digest_only(self) -> None:
        self.assertIn('id="arl-data"', self.viewer)
        self.assertIn("state_conflict_rebased", self.viewer)
        self.assertNotIn("<script src=", self.viewer)
        self.assertNotIn("fetch(", self.viewer)
        self.assertNotIn('"arguments"', self.viewer)
        self.assertNotIn("external-observer:", self.viewer)


if __name__ == "__main__":
    unittest.main()
