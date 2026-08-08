from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arl_study.experiment import execute_resilience_job, resilience_study_manifest
from arl_study.scheduler import StudyManifest, StudyScheduler

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class StudyRuntimeIntegrationTests(unittest.TestCase):
    def test_real_resilience_jobs_resume_and_match_v09_evidence(self) -> None:
        full_manifest = resilience_study_manifest()
        manifest = StudyManifest(
            study_id="integration-study",
            experiment_version=full_manifest.experiment_version,
            jobs=full_manifest.jobs[:3],
        )
        with tempfile.TemporaryDirectory(prefix="arl-study-integration-") as temporary:
            workspace = Path(temporary) / "study"
            first = StudyScheduler.create(workspace, manifest)
            interrupted = first.run(execute_resilience_job, max_new_jobs=1)
            resumed = StudyScheduler.resume(workspace, manifest)
            completed = resumed.run(execute_resilience_job)
            results = resumed.completed_results()
            state = resumed.state

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

        self.assertEqual(interrupted.completed_count, 1)
        self.assertEqual(completed.completed_count, 3)
        self.assertTrue(completed.preexisting_results_preserved)
        self.assertTrue(all(entry["attempt_count"] == 1 for entry in state["jobs"].values()))


if __name__ == "__main__":
    unittest.main()
