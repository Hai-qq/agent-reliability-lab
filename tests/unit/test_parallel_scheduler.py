from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from arl.core.types import digest_value
from arl_parallel.scheduler import (
    ParallelStudyScheduler,
    ParallelStudyStateError,
    StaleLeaseError,
    file_sha256,
)
from arl_study.scheduler import StudyJob, StudyManifest


def manifest(job_count: int = 8) -> StudyManifest:
    return StudyManifest(
        study_id="parallel-unit-study",
        experiment_version="parallel-unit-v1",
        jobs=tuple(
            StudyJob.from_payload(f"job-{index}", {"value": index}) for index in range(job_count)
        ),
    )


def executor(
    calls: list[str] | None = None,
    *,
    barrier: threading.Barrier | None = None,
    thread_names: set[str] | None = None,
):
    def execute(job: StudyJob, trace_path: Path) -> dict[str, object]:
        if calls is not None:
            calls.append(job.job_id)
        if thread_names is not None:
            thread_names.add(threading.current_thread().name)
        if barrier is not None:
            barrier.wait(timeout=5)
        trace_path.write_text(
            f'{{"event_id":"{job.job_id}:0001","event_type":"completed"}}\n',
            encoding="utf-8",
        )
        return {
            "job_id": job.job_id,
            "payload_digest": digest_value(job.payload()),
            "trace_sha256": file_sha256(trace_path),
        }

    return execute


class ParallelStudySchedulerTests(unittest.TestCase):
    def test_four_workers_execute_one_wave_concurrently(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-concurrency-") as temporary:
            workspace = Path(temporary) / "study"
            barrier = threading.Barrier(4)
            thread_names: set[str] = set()
            scheduler = ParallelStudyScheduler.create(
                workspace,
                manifest(4),
                worker_count=4,
                lease_duration_ticks=100,
            )

            report = scheduler.run(
                executor(barrier=barrier, thread_names=thread_names),
            )

        self.assertEqual(report.status, "complete")
        self.assertEqual(report.max_leased_count, 4)
        self.assertEqual(len(thread_names), 4)

    def test_interruption_leaves_leases_and_resume_reclaims_them(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-resume-") as temporary:
            workspace = Path(temporary) / "study"
            scheduler = ParallelStudyScheduler.create(
                workspace,
                manifest(),
                worker_count=4,
                lease_duration_ticks=100,
            )
            interrupted = scheduler.run(executor(), max_new_jobs=2, leave_leases=2)
            result_before = (workspace / "results/job-0.json").read_bytes()
            trace_before = (workspace / "traces/job-0.jsonl").read_bytes()

            resumed = ParallelStudyScheduler.resume(
                workspace,
                manifest(),
                worker_count=4,
                lease_duration_ticks=100,
            )
            reclaimed = resumed.reclaim_all_leases()
            completed = resumed.run(executor())

            self.assertEqual(interrupted.status, "interrupted")
            self.assertEqual(interrupted.completed_count, 2)
            self.assertEqual(interrupted.leased_count, 2)
            self.assertEqual(reclaimed, ("job-2", "job-3"))
            self.assertEqual(completed.status, "complete")
            self.assertTrue(completed.preexisting_results_preserved)
            self.assertEqual(completed.preexisting_completed_count, 2)
            self.assertEqual(result_before, (workspace / "results/job-0.json").read_bytes())
            self.assertEqual(trace_before, (workspace / "traces/job-0.jsonl").read_bytes())
            self.assertEqual(resumed.state["jobs"]["job-2"]["attempt_count"], 2)
            self.assertEqual(resumed.state["jobs"]["job-3"]["attempt_count"], 2)

    def test_crash_expiry_stale_commit_and_heartbeat_recover_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-faults-") as temporary:
            workspace = Path(temporary) / "study"
            scheduler = ParallelStudyScheduler.create(
                workspace,
                manifest(4),
                worker_count=4,
                lease_duration_ticks=100,
            )

            def faulting(job: StudyJob, trace_path: Path) -> dict[str, object]:
                trace_path.write_text(
                    f'{{"event_id":"{job.job_id}:0001","event_type":"attempted"}}\n',
                    encoding="utf-8",
                )
                if job.job_id == "job-0" and trace_path.name.endswith("lease-1.jsonl"):
                    raise RuntimeError("planned crash")
                return {
                    "job_id": job.job_id,
                    "trace_sha256": file_sha256(trace_path),
                }

            report = scheduler.run(
                faulting,
                expire_once_job_ids=("job-1",),
                heartbeat_once_job_ids=("job-2",),
            )
            state = scheduler.state

            self.assertEqual(report.status, "complete")
            self.assertEqual(report.lease_acquisition_count, 6)
            self.assertEqual(report.lease_expiration_count, 1)
            self.assertEqual(report.stale_commit_rejection_count, 1)
            self.assertEqual(report.worker_failure_count, 1)
            self.assertEqual(report.heartbeat_count, 1)
            self.assertEqual(state["jobs"]["job-0"]["attempt_count"], 2)
            self.assertEqual(state["jobs"]["job-1"]["attempt_count"], 2)
            self.assertTrue(all(entry["commit_count"] == 1 for entry in state["jobs"].values()))
            self.assertTrue((workspace / "attempts/job-0.lease-1.jsonl").is_file())
            self.assertTrue((workspace / "attempts/job-1.lease-1.jsonl").is_file())

    def test_stale_lease_cannot_commit_after_expiry(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-stale-") as temporary:
            workspace = Path(temporary) / "study"
            scheduler = ParallelStudyScheduler.create(
                workspace,
                manifest(2),
                worker_count=2,
                lease_duration_ticks=20,
            )
            lease = scheduler.acquire_pending(1)[0]
            result = executor()(manifest(2).jobs[0], lease.attempt_path)
            scheduler.force_expire(lease)

            with self.assertRaises(StaleLeaseError):
                scheduler.commit_lease(lease, result)

            self.assertFalse((workspace / "results/job-0.json").exists())
            self.assertEqual(scheduler.state["jobs"]["job-0"]["status"], "pending")

    def test_resume_reconciles_commit_files_after_state_write_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-reconcile-") as temporary:
            workspace = Path(temporary) / "study"
            study_manifest = manifest(2)
            scheduler = ParallelStudyScheduler.create(
                workspace,
                study_manifest,
                worker_count=2,
                lease_duration_ticks=20,
            )
            lease = scheduler.acquire_pending(1)[0]
            result = executor()(study_manifest.jobs[0], lease.attempt_path)

            with (
                patch.object(scheduler, "_persist", side_effect=OSError("planned fsync gap")),
                self.assertRaises(OSError),
            ):
                scheduler.commit_lease(lease, result)

            resumed = ParallelStudyScheduler.resume(
                workspace,
                study_manifest,
                worker_count=2,
                lease_duration_ticks=20,
            )
            self.assertEqual(resumed.state["jobs"]["job-0"]["status"], "completed")
            self.assertEqual(resumed.state["jobs"]["job-0"]["commit_count"], 1)
            self.assertTrue((workspace / "traces/job-0.jsonl").is_file())

    def test_resume_rejects_tampered_completed_trace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-parallel-tamper-") as temporary:
            workspace = Path(temporary) / "study"
            scheduler = ParallelStudyScheduler.create(
                workspace,
                manifest(2),
                worker_count=2,
                lease_duration_ticks=20,
            )
            scheduler.run(executor(), max_new_jobs=1)
            with (workspace / "traces/job-0.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"event_type":"tampered"}\n')

            with self.assertRaises(ParallelStudyStateError):
                ParallelStudyScheduler.resume(
                    workspace,
                    manifest(2),
                    worker_count=2,
                    lease_duration_ticks=20,
                )


if __name__ == "__main__":
    unittest.main()
