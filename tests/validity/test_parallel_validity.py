from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_parallel.experiment import (
    CRASH_JOB_ID,
    EXPIRE_JOB_ID,
    HEARTBEAT_JOB_ID,
    LEASE_DURATION_TICKS,
    LEAVE_LEASES,
    STOP_AFTER,
    WORKER_COUNT,
    build_parallel_summary,
    execute_parallel_resilience_job,
    parallel_resilience_manifest,
)
from arl_parallel.scheduler import ParallelStudyScheduler

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ParallelStudyValidityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory(prefix="arl-v11-validity-")
        cls.workspace = Path(cls._temporary.name) / "study"
        manifest = parallel_resilience_manifest()
        initial = ParallelStudyScheduler.create(
            cls.workspace,
            manifest,
            worker_count=WORKER_COUNT,
            lease_duration_ticks=LEASE_DURATION_TICKS,
        )
        cls.interrupted_report = initial.run(
            execute_parallel_resilience_job,
            max_new_jobs=STOP_AFTER,
            leave_leases=LEAVE_LEASES,
            expire_once_job_ids=(EXPIRE_JOB_ID,),
            heartbeat_once_job_ids=(HEARTBEAT_JOB_ID,),
        )
        cls.interrupted_summary = build_parallel_summary(
            initial,
            cls.interrupted_report,
            PROJECT_ROOT,
        )
        resumed = ParallelStudyScheduler.resume(
            cls.workspace,
            manifest,
            worker_count=WORKER_COUNT,
            lease_duration_ticks=LEASE_DURATION_TICKS,
        )
        cls.reclaimed = resumed.reclaim_all_leases()
        cls.final_report = resumed.run(
            execute_parallel_resilience_job,
            expire_once_job_ids=(EXPIRE_JOB_ID,),
            heartbeat_once_job_ids=(HEARTBEAT_JOB_ID,),
        )
        cls.final_summary = build_parallel_summary(resumed, cls.final_report, PROJECT_ROOT)
        cls.state = resumed.state

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def test_formal_checkpoint_leaves_four_active_leases(self) -> None:
        self.assertEqual(self.interrupted_report.status, "interrupted")
        self.assertEqual(self.interrupted_report.completed_count, STOP_AFTER)
        self.assertEqual(self.interrupted_report.leased_count, LEAVE_LEASES)
        self.assertEqual(self.interrupted_report.pending_count, 36 - STOP_AFTER - LEAVE_LEASES)
        self.assertTrue(self.interrupted_summary["validity"]["all_selected_checks_passed"])

    def test_resume_reclaims_crash_leases_and_preserves_prior_results(self) -> None:
        self.assertEqual(len(self.reclaimed), LEAVE_LEASES)
        self.assertEqual(self.final_report.status, "complete")
        self.assertEqual(self.final_report.completed_count, 36)
        self.assertTrue(self.final_report.preexisting_results_preserved)
        self.assertEqual(self.final_report.preexisting_completed_count, STOP_AFTER)

    def test_fault_protocol_has_exact_expected_counts(self) -> None:
        report = self.final_report
        self.assertEqual(report.lease_acquisition_count, 42)
        self.assertEqual(report.lease_expiration_count, 5)
        self.assertEqual(report.stale_commit_rejection_count, 1)
        self.assertEqual(report.worker_failure_count, 1)
        self.assertEqual(report.heartbeat_count, 1)
        self.assertEqual(report.max_leased_count, WORKER_COUNT)
        self.assertEqual(self.state["jobs"][CRASH_JOB_ID]["attempt_count"], 2)
        self.assertEqual(self.state["jobs"][EXPIRE_JOB_ID]["attempt_count"], 2)
        self.assertTrue(all(entry["commit_count"] == 1 for entry in self.state["jobs"].values()))
        self.assertEqual(len(list((self.workspace / "attempts").glob("*.jsonl"))), 2)

    def test_final_evidence_matches_v09_and_historical_manifests(self) -> None:
        validity = self.final_summary["validity"]
        self.assertTrue(validity["all_selected_checks_passed"])
        self.assertTrue(validity["complete_matrix"]["passed"])
        self.assertTrue(validity["reference_equivalence"]["passed"])
        self.assertTrue(validity["digest_only_traces"]["passed"])
        self.assertTrue(validity["historical_source_manifests"]["passed"])
        self.assertEqual(len(validity["historical_source_manifests"]["increments"]), 10)


if __name__ == "__main__":
    unittest.main()
