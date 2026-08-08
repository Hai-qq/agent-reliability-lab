from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_scenarios.catalog import TASK_TEMPLATES
from arl_scenarios.experiment import run_episode


class ScenarioRuntimeIntegrationTests(unittest.TestCase):
    def test_all_templates_recover_compatible_and_reject_incompatible_conflicts(self) -> None:
        for template in TASK_TEMPLATES:
            with self.subTest(template=template.template_id, condition="compatible"):
                compatible = run_episode(
                    template_id=template.template_id,
                    runtime_name="r2_template_guarded",
                    condition="compatible_conflict",
                    seed=0,
                    trace_path=None,
                )
                self.assertTrue(compatible["execution"]["completed_plan"])
                self.assertEqual(compatible["execution"]["conflict_rebase_count"], 1)
                self.assertTrue(compatible["evaluation"]["safe_success"])
            with self.subTest(template=template.template_id, condition="incompatible"):
                incompatible = run_episode(
                    template_id=template.template_id,
                    runtime_name="r2_template_guarded",
                    condition="incompatible_conflict",
                    seed=0,
                    trace_path=None,
                )
                self.assertEqual(
                    incompatible["execution"]["failure_code"],
                    "conflict_precondition_changed",
                )
                self.assertEqual(
                    incompatible["final_state"]["conflict_target_status"],
                    "externally_changed",
                )

    def test_baseline_stops_on_all_registered_conflicts(self) -> None:
        for template in TASK_TEMPLATES:
            for condition in ("compatible_conflict", "incompatible_conflict"):
                with self.subTest(template=template.template_id, condition=condition):
                    result = run_episode(
                        template_id=template.template_id,
                        runtime_name="r2_confirmed",
                        condition=condition,
                        seed=0,
                        trace_path=None,
                    )
                    self.assertEqual(result["execution"]["failure_code"], "state_version_conflict")
                    self.assertFalse(result["evaluation"]["task_success"])

    def test_workflow_trace_is_digest_only_and_terminally_verified(self) -> None:
        template = next(item for item in TASK_TEMPLATES if item.compensation_type)
        with tempfile.TemporaryDirectory(prefix="arl-scenario-workflow-") as temporary:
            trace_path = Path(temporary) / "trace.jsonl"
            result = run_episode(
                template_id=template.template_id,
                runtime_name="r2_template_guarded",
                condition="compatible_conflict",
                seed=0,
                trace_path=trace_path,
            )
            serialized = trace_path.read_text(encoding="utf-8")
        execution = result["execution"]
        self.assertEqual(execution["workflow_contract_attempt_count"], 1)
        self.assertEqual(execution["workflow_contract_success_count"], 1)
        self.assertEqual(execution["workflow_terminal_probe_count"], 6)
        self.assertIn("compensation_workflow_succeeded", serialized)
        self.assertNotIn('"arguments"', serialized)
        self.assertNotIn("synthetic-", serialized)
        self.assertNotIn("scenario-observer:", serialized)


if __name__ == "__main__":
    unittest.main()
