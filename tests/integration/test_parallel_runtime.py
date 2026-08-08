from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arl_parallel.scheduler import ParallelStudyScheduler
from arl_study.experiment import execute_resilience_job, resilience_study_manifest
from arl_study.scheduler import StudyManifest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ParallelRuntimeIntegrationTests(unittest.TestCase):
    def test_parallel_resume_matches_v09_results_and_traces(self) -> None:
        full_manifest = resilience_study_manifest()
        manifest = StudyManifest(
            study_id="parallel-integration-study",
            experiment_version=full_manifest.experiment_version,
            jobs=full_manifest.jobs[:6],
        )
        with tempfile.TemporaryDirectory(prefix="arl-parallel-integration-") as temporary:
            workspace = Path(temporary) / "study"
            initial = ParallelStudyScheduler.create(
                workspace,
                manifest,
                worker_count=4,
                lease_duration_ticks=100,
            )
            interrupted = initial.run(
                execute_resilience_job,
                max_new_jobs=2,
                leave_leases=2,
            )
            resumed = ParallelStudyScheduler.resume(
                workspace,
                manifest,
                worker_count=4,
                lease_duration_ticks=100,
            )
            self.assertEqual(len(resumed.reclaim_all_leases()), 2)
            completed = resumed.run(execute_resilience_job)
            results = resumed.completed_results()

            reference = json.loads(
                (PROJECT_ROOT / "artifacts/cross_domain_resilience_v09/summary.json").read_text(
                    encoding="utf-8"
                )
            )
            reference_by_id = {item["episode_id"]: item for item in reference["episodes"]}
            self.assertEqual(results, [reference_by_id[item["episode_id"]] for item in results])
            for result in results:
                name = result["trace_file"]
                self.assertEqual(
                    (workspace / "traces" / name).read_bytes(),
                    (
                        PROJECT_ROOT / "artifacts/cross_domain_resilience_v09/traces" / name
                    ).read_bytes(),
                )

        self.assertEqual(interrupted.completed_count, 2)
        self.assertEqual(interrupted.leased_count, 2)
        self.assertEqual(completed.completed_count, 6)
        self.assertTrue(completed.preexisting_results_preserved)


if __name__ == "__main__":
    unittest.main()
