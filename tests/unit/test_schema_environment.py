from __future__ import annotations

import unittest

from arl_schema.env import (
    FLIGHT_ACTION_FAULT_ID,
    HOTEL_RESULT_FAULT_ID,
    SchemaDriftEnvironment,
)
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID
from arl_travel.experiment import task_plan


class SchemaEnvironmentTests(unittest.TestCase):
    def test_unadapted_v1_action_is_rejected_without_state_mutation(self) -> None:
        environment = SchemaDriftEnvironment("flight_action_schema_v2")
        try:
            observation = environment.reset(BOOK_TASK_ID, 0)
            before_hash = environment.state_hash()
            action = task_plan(observation, "r1_guarded").primary_actions[0]
            result = environment.step(action)
            self.assertEqual(result.error_code, "schema_version_unsupported")
            self.assertEqual(environment.state_hash(), before_hash)
            self.assertEqual(environment.last_fault_id, FLIGHT_ACTION_FAULT_ID)
        finally:
            environment.close()

    def test_result_drift_changes_contract_not_committed_state(self) -> None:
        clean = SchemaDriftEnvironment()
        drift = SchemaDriftEnvironment("hotel_result_schema_v2")
        try:
            clean_observation = clean.reset(RECOVERY_TASK_ID, 1)
            drift_observation = drift.reset(RECOVERY_TASK_ID, 1)
            self.assertEqual(clean_observation.state_hash, drift_observation.state_hash)
            clean_action = task_plan(clean_observation, "r1_guarded").primary_actions[0]
            drift_action = task_plan(drift_observation, "r1_guarded").primary_actions[0]
            clean_result = clean.step(clean_action)
            drift_result = drift.step(drift_action)
            self.assertTrue(clean_result.ok and drift_result.ok)
            self.assertEqual(clean.state_hash(), drift.state_hash())
            self.assertNotEqual(clean_result.value, drift_result.value)
            self.assertEqual(drift.last_fault_id, HOTEL_RESULT_FAULT_ID)
        finally:
            clean.close()
            drift.close()

    def test_descriptor_is_deterministic_and_non_oracular(self) -> None:
        environment = SchemaDriftEnvironment("flight_action_schema_v2")
        try:
            environment.reset(BOOK_TASK_ID, 2)
            first = environment.describe_tool("flights.book")
            second = environment.describe_tool("flights.book")
            self.assertEqual(first, second)
            self.assertIsNot(first, second)
            serialized = str(first).lower()
            for forbidden in ("fault", "target", "seed", "oracle", "evaluator"):
                self.assertNotIn(forbidden, serialized)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
