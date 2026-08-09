from __future__ import annotations

import unittest

from arl.core.types import canonical_json
from arl_pilot.env import PilotEnvironment
from arl_pilot.specs import PILOT_TASK_SPECS, SPECS_BY_TEMPLATE_ID, pilot_catalog_audit


class PilotTaskSpecTests(unittest.TestCase):
    def test_catalog_has_eight_tasks_and_all_six_fault_families(self) -> None:
        audit = pilot_catalog_audit()
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["task_count"], 8)
        self.assertEqual(audit["domain_counts"], {"retail": 3, "travel": 2, "workspace": 3})
        self.assertEqual(
            audit["source_blueprint_status_counts"],
            {"existing_core": 5, "planned": 3},
        )
        self.assertEqual(len(audit["fault_family_counts"]), 6)

    def test_reset_is_deterministic_for_every_task_and_condition(self) -> None:
        for spec in PILOT_TASK_SPECS:
            hashes = set()
            for condition in ("clean", "recoverable_fault"):
                environment = PilotEnvironment(spec, condition)
                try:
                    hashes.add(environment.reset(spec.task_id, 0).state_hash)
                finally:
                    environment.close()
            with self.subTest(template_id=spec.template_id):
                self.assertEqual(len(hashes), 1)

    def test_model_visible_contract_has_inputs_without_hidden_fault_or_oracle(self) -> None:
        for spec in PILOT_TASK_SPECS:
            visible = spec.visible_task
            payload = canonical_json(visible)
            tool_names = {tool.tool_name for tool in spec.model_tools}
            with self.subTest(template_id=spec.template_id):
                self.assertTrue(visible["user_request"])
                self.assertTrue(visible["context"])
                self.assertEqual(set(visible["allowed_tools"]), tool_names)
                self.assertNotIn(spec.fault_id, payload)
                self.assertNotIn("clean_expected", payload)
                self.assertNotIn("fault_expected", payload)

    def test_input_schema_drift_requires_exact_registered_adapter(self) -> None:
        spec = SPECS_BY_TEMPLATE_ID["travel.book-itinerary.main-v1"]
        raw_environment = PilotEnvironment(spec, "recoverable_fault")
        try:
            raw_environment.reset(spec.task_id, 0)
            raw_result = raw_environment.step(spec.semantic_actions[0])
            self.assertEqual(raw_result.error_code, "schema_version_unsupported")
        finally:
            raw_environment.close()

        adapted_environment = PilotEnvironment(spec, "recoverable_fault")
        try:
            adapted_environment.reset(spec.task_id, 0)
            adapted = adapted_environment.adapt_input_action(spec.semantic_actions[0])
            result = adapted_environment.step(adapted)
            self.assertTrue(result.ok)
            self.assertEqual(adapted.schema_version, "2.0")
            self.assertEqual(set(adapted.arguments), {"segment_id"})
        finally:
            adapted_environment.close()

    def test_output_schema_drift_normalizes_to_canonical_contract(self) -> None:
        spec = SPECS_BY_TEMPLATE_ID["workspace.clarify-attendees.main-v1"]
        environment = PilotEnvironment(spec, "recoverable_fault")
        try:
            environment.reset(spec.task_id, 0)
            semantic = spec.semantic_actions[0]
            drifted = environment.step(semantic)
            self.assertTrue(drifted.ok)
            self.assertFalse(environment.result_contract_valid(semantic, drifted))
            normalized = environment.normalize_result(semantic, drifted)
            self.assertTrue(environment.result_contract_valid(semantic, normalized))
            self.assertEqual(
                normalized.value,
                {"attendee_ids": ["person-alex", "person-sam"]},
            )
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
