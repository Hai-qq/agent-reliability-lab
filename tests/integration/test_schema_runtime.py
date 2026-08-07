from __future__ import annotations

import unittest

from arl.runtime.journal import EventJournal
from arl_schema.env import SchemaDriftEnvironment
from arl_schema.runtime import SchemaRuntime
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID
from arl_travel.evaluator import evaluate_travel
from arl_travel.experiment import task_plan


def run_case(task_id: str, runtime_name: str, drift_mode: str):
    environment = SchemaDriftEnvironment(drift_mode)
    observation = environment.reset(task_id, 0)
    initial = environment.snapshot()
    journal = EventJournal(
        run_id="schema-v07-test",
        episode_id=f"{task_id}-{runtime_name}-{drift_mode}",
        task_id=task_id,
        seed=0,
    )
    plan_runtime = "r2_confirmed" if runtime_name == "r2_schema_adapted" else "r1_guarded"
    execution = SchemaRuntime(runtime_name).execute(
        environment,
        task_plan(observation, plan_runtime),
        journal,
    )
    evaluation = evaluate_travel(initial, environment.snapshot(), journal.as_dicts())
    return environment, journal, execution, evaluation


class SchemaRuntimeTests(unittest.TestCase):
    def test_r1_fails_both_registered_drift_modes(self) -> None:
        cases = (
            (BOOK_TASK_ID, "flight_action_schema_v2", "schema_version_unsupported"),
            (RECOVERY_TASK_ID, "hotel_result_schema_v2", "result_contract_violation"),
        )
        for task_id, drift_mode, expected_failure in cases:
            with self.subTest(task_id=task_id):
                environment, _, execution, evaluation = run_case(task_id, "r1_guarded", drift_mode)
                try:
                    self.assertFalse(execution.completed_plan)
                    self.assertEqual(execution.failure_code, expected_failure)
                    self.assertFalse(evaluation.task_success)
                finally:
                    environment.close()

    def test_r2_recovers_action_and_result_drift(self) -> None:
        cases = (
            (BOOK_TASK_ID, "flight_action_schema_v2", "schema_adapter_applied"),
            (RECOVERY_TASK_ID, "hotel_result_schema_v2", "output_adapter_applied"),
        )
        for task_id, drift_mode, expected_event in cases:
            with self.subTest(task_id=task_id):
                environment, journal, execution, evaluation = run_case(
                    task_id, "r2_schema_adapted", drift_mode
                )
                try:
                    self.assertTrue(execution.completed_plan)
                    self.assertTrue(evaluation.safe_success)
                    self.assertIn(expected_event, {event.event_type for event in journal.events})
                finally:
                    environment.close()

    def test_schema_trace_contains_digests_not_payloads(self) -> None:
        environment, journal, _, _ = run_case(
            BOOK_TASK_ID,
            "r2_schema_adapted",
            "flight_action_schema_v2",
        )
        try:
            serialized = journal.jsonl_bytes().decode("utf-8")
            self.assertIn("schema_adapter_applied", serialized)
            self.assertNotIn("synthetic-traveler-", serialized)
            self.assertNotIn('"arguments"', serialized)
            self.assertNotIn('"payment_id"', serialized)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
