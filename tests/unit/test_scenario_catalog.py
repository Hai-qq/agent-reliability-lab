from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from arl.core.types import ToolAction, canonical_json, digest_value
from arl_scenarios.catalog import TASK_TEMPLATES, TEMPLATES_BY_ID
from arl_scenarios.env import ScenarioTravelEnvironment
from arl_scenarios.workflow import (
    build_travel_scenario_plan,
)
from arl_travel.env import RECOVERY_TASK_ID, SCHEMA_VERSION
from scripts.run_scenario_pack import validate_paths


class ScenarioCatalogTests(unittest.TestCase):
    def test_catalog_has_four_digest_linked_templates(self) -> None:
        self.assertEqual(len(TASK_TEMPLATES), 4)
        self.assertEqual(len(TEMPLATES_BY_ID), 4)
        self.assertEqual(len({item.task_id for item in TASK_TEMPLATES}), 4)
        self.assertEqual(len({item.conflict_tool for item in TASK_TEMPLATES}), 4)
        for template in TASK_TEMPLATES:
            descriptor = template.audit_descriptor()
            expected = {key: value for key, value in descriptor.items() if key != "template_digest"}
            self.assertEqual(descriptor["template_digest"], digest_value(expected))

    def test_workflow_has_four_idempotent_steps_and_digest_only_descriptor(self) -> None:
        template = next(item for item in TASK_TEMPLATES if item.task_id == RECOVERY_TASK_ID)
        environment = ScenarioTravelEnvironment(template, "none")
        try:
            observation = environment.reset(template.task_id, 0)
            workflow = build_travel_scenario_plan(observation).workflow
        finally:
            environment.close()
        self.assertIsNotNone(workflow)
        assert workflow is not None
        self.assertEqual(len(workflow.steps), 4)
        self.assertTrue(all(item.action.idempotency_key for item in workflow.steps))
        self.assertEqual(len(workflow.terminal_postconditions), 6)
        self.assertNotIn("synthetic-", canonical_json(workflow.audit_descriptor()))

    def test_workflow_rejects_unbounded_or_non_idempotent_mutations(self) -> None:
        template = next(item for item in TASK_TEMPLATES if item.task_id == RECOVERY_TASK_ID)
        environment = ScenarioTravelEnvironment(template, "none")
        try:
            workflow = build_travel_scenario_plan(environment.reset(template.task_id, 0)).workflow
        finally:
            environment.close()
        assert workflow is not None
        with self.assertRaises(ValueError):
            replace(workflow, max_attempts=2)
        with self.assertRaises(ValueError):
            replace(workflow, terminal_postconditions=())
        with self.assertRaises(ValueError):
            replace(
                workflow.steps[0],
                action=replace(workflow.steps[0].action, idempotency_key=None),
            )

    def test_booking_request_read_is_typed_and_version_guarded(self) -> None:
        template = next(item for item in TASK_TEMPLATES if item.task_id == RECOVERY_TASK_ID)
        environment = ScenarioTravelEnvironment(template, "none")
        try:
            observation = environment.reset(template.task_id, 0)
            result = environment.step(
                ToolAction(
                    tool_name=environment.REQUEST_READ_TOOL,
                    schema_version=SCHEMA_VERSION,
                    arguments={"request_id": observation.visible_task["request_id"]},
                    expected_state_version=0,
                )
            )
            stale = environment.step(
                ToolAction(
                    tool_name=environment.REQUEST_READ_TOOL,
                    schema_version=SCHEMA_VERSION,
                    arguments={"request_id": observation.visible_task["request_id"]},
                    expected_state_version=1,
                )
            )
        finally:
            environment.close()
        self.assertTrue(result.ok)
        self.assertEqual(result.value["request"]["status"], "pending")
        self.assertEqual(stale.error_code, "state_version_conflict")

    def test_runner_paths_refuse_overwrite_and_nested_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-scenario-cli-") as temporary:
            root = Path(temporary)
            validate_paths(root / "summary.json", root / "traces")
            with self.assertRaises(SystemExit):
                validate_paths(root / "traces/summary.json", root / "traces")
            output = root / "summary.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_paths(output, root / "traces")


if __name__ == "__main__":
    unittest.main()
