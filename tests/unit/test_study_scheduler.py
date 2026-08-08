from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl.core.types import digest_value
from arl_study.scheduler import (
    StudyJob,
    StudyManifest,
    StudyScheduler,
    StudyStateError,
    file_sha256,
    write_json_atomic,
)


def manifest(version: str = "test-v1") -> StudyManifest:
    return StudyManifest(
        study_id="unit-study",
        experiment_version=version,
        jobs=tuple(StudyJob.from_payload(f"job-{index}", {"value": index}) for index in range(3)),
    )


class StudySchedulerTests(unittest.TestCase):
    @staticmethod
    def executor(calls: list[str]):
        def execute(job: StudyJob, trace_path: Path) -> dict[str, object]:
            calls.append(job.job_id)
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

    def test_manifest_rejects_unsafe_and_duplicate_job_ids(self) -> None:
        with self.assertRaises(ValueError):
            StudyJob.from_payload("../unsafe", {"value": 1})
        duplicate = StudyJob.from_payload("same", {"value": 1})
        with self.assertRaises(ValueError):
            StudyManifest(
                study_id="duplicate-study",
                experiment_version="v1",
                jobs=(duplicate, duplicate),
            )

    def test_interruption_resume_skips_and_preserves_completed_job(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-unit-") as temporary:
            workspace = Path(temporary) / "study"
            first_calls: list[str] = []
            scheduler = StudyScheduler.create(workspace, manifest())
            interrupted = scheduler.run(self.executor(first_calls), max_new_jobs=1)
            result_before = (workspace / "results/job-0.json").read_bytes()
            trace_before = (workspace / "traces/job-0.jsonl").read_bytes()

            second_calls: list[str] = []
            resumed = StudyScheduler.resume(workspace, manifest())
            completed = resumed.run(self.executor(second_calls))

            self.assertEqual(interrupted.status, "interrupted")
            self.assertEqual(first_calls, ["job-0"])
            self.assertEqual(second_calls, ["job-1", "job-2"])
            self.assertEqual(completed.status, "complete")
            self.assertTrue(completed.preexisting_results_preserved)
            self.assertEqual(completed.preexisting_completed_count, 1)
            self.assertEqual(result_before, (workspace / "results/job-0.json").read_bytes())
            self.assertEqual(trace_before, (workspace / "traces/job-0.jsonl").read_bytes())
            self.assertTrue(
                all(entry["attempt_count"] == 1 for entry in resumed.state["jobs"].values())
            )
            with self.assertRaises(StudyStateError):
                StudyScheduler.resume(workspace, manifest())

    def test_resume_rejects_manifest_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-manifest-") as temporary:
            workspace = Path(temporary) / "study"
            StudyScheduler.create(workspace, manifest()).run(self.executor([]), max_new_jobs=1)
            with self.assertRaises(StudyStateError):
                StudyScheduler.resume(workspace, manifest("test-v2"))

    def test_resume_rejects_tampered_completed_trace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-tamper-") as temporary:
            workspace = Path(temporary) / "study"
            StudyScheduler.create(workspace, manifest()).run(self.executor([]), max_new_jobs=1)
            with (workspace / "traces/job-0.jsonl").open("a", encoding="utf-8") as handle:
                handle.write('{"event_type":"tampered"}\n')
            with self.assertRaises(StudyStateError):
                StudyScheduler.resume(workspace, manifest())

    def test_failed_running_attempt_is_requeued_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-requeue-") as temporary:
            workspace = Path(temporary) / "study"
            scheduler = StudyScheduler.create(workspace, manifest())

            def fail(job: StudyJob, trace_path: Path) -> dict[str, object]:
                trace_path.write_text('{"event_type":"partial"}\n', encoding="utf-8")
                raise RuntimeError(job.job_id)

            with self.assertRaises(RuntimeError):
                scheduler.run(fail)
            resumed = StudyScheduler.resume(workspace, manifest())
            completed = resumed.run(self.executor([]))
            self.assertEqual(completed.status, "complete")
            self.assertEqual(resumed.state["jobs"]["job-0"]["attempt_count"], 2)
            self.assertTrue((workspace / "attempts/job-0.attempt-1.jsonl").is_file())
            self.assertTrue((workspace / "traces/job-0.jsonl").is_file())

    def test_resume_rejects_unlinked_inflight_result(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-inflight-") as temporary:
            workspace = Path(temporary) / "study"
            scheduler = StudyScheduler.create(workspace, manifest())

            def fail(job: StudyJob, trace_path: Path) -> dict[str, object]:
                trace_path.write_text('{"event_type":"partial"}\n', encoding="utf-8")
                raise RuntimeError(job.job_id)

            with self.assertRaises(RuntimeError):
                scheduler.run(fail)
            attempt = workspace / "attempts/job-0.attempt-1.jsonl"
            write_json_atomic(
                workspace / "results/job-0.json",
                {
                    "job_id": "job-0",
                    "payload_sha256": "not-the-manifest-payload",
                    "result": {},
                    "trace_sha256": file_sha256(attempt),
                },
            )
            with self.assertRaises(StudyStateError):
                StudyScheduler.resume(workspace, manifest())

    def test_create_refuses_existing_workspace(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-study-existing-") as temporary:
            workspace = Path(temporary) / "study"
            workspace.mkdir()
            with self.assertRaises(FileExistsError):
                StudyScheduler.create(workspace, manifest())


if __name__ == "__main__":
    unittest.main()
