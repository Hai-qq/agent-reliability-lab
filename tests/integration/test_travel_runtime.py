from __future__ import annotations

import unittest

from arl.runtime.journal import EventJournal
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID, TravelEnvironment
from arl_travel.evaluator import evaluate_travel
from arl_travel.experiment import task_plan
from arl_travel.runtime import TravelRuntime


def run_case(task_id: str, runtime_name: str, fault_mode: str):
    environment = TravelEnvironment(fault_mode=fault_mode)
    observation = environment.reset(task_id, 0)
    pre_snapshot = environment.snapshot()
    journal = EventJournal(
        run_id="travel-v06-test",
        episode_id=f"{task_id}-{runtime_name}-{fault_mode}",
        task_id=task_id,
        seed=0,
    )
    execution = TravelRuntime(runtime_name).execute(
        environment,
        task_plan(observation, runtime_name),
        journal,
    )
    evaluation = evaluate_travel(
        pre_snapshot,
        environment.snapshot(),
        journal.as_dicts(),
    )
    return environment, journal, execution, evaluation


class TravelRuntimeTests(unittest.TestCase):
    def test_r1_postcommit_timeout_stops_with_partial_itinerary(self) -> None:
        environment, _, execution, evaluation = run_case(
            BOOK_TASK_ID,
            "r1_guarded",
            "flight_postcommit_timeout_once",
        )
        try:
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "state_version_conflict")
            self.assertEqual(execution.retry_count, 1)
            self.assertFalse(evaluation.task_success)
            self.assertEqual(len(environment.export_world()["flight_bookings"]), 1)
        finally:
            environment.close()

    def test_r2_postcommit_timeout_confirms_and_finishes(self) -> None:
        environment, journal, execution, evaluation = run_case(
            BOOK_TASK_ID,
            "r2_confirmed",
            "flight_postcommit_timeout_once",
        )
        try:
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.retry_count, 0)
            self.assertEqual(execution.confirmation_count, 1)
            self.assertTrue(evaluation.safe_success)
            self.assertEqual(
                sum(event.event_type == "state_confirmation_succeeded" for event in journal.events),
                1,
            )
        finally:
            environment.close()

    def test_r1_flight_failure_leaves_orphaned_hotel(self) -> None:
        environment, _, execution, evaluation = run_case(
            RECOVERY_TASK_ID,
            "r1_guarded",
            "preferred_flight_unavailable",
        )
        try:
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "flight_unavailable")
            self.assertFalse(evaluation.task_success)
            self.assertIn(
                "orphaned_hotel_after_flight_failure",
                evaluation.minefields_triggered,
            )
            self.assertEqual(
                environment.export_world()["hotel_reservations"][0]["status"], "active"
            )
        finally:
            environment.close()

    def test_r2_flight_failure_compensates_and_uses_backup(self) -> None:
        environment, journal, execution, evaluation = run_case(
            RECOVERY_TASK_ID,
            "r2_confirmed",
            "preferred_flight_unavailable",
        )
        try:
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.recovery_branch_count, 1)
            self.assertEqual(execution.compensation_count, 1)
            self.assertTrue(evaluation.safe_success)
            world = environment.export_world()
            self.assertEqual(
                {row["status"] for row in world["hotel_reservations"]}, {"active", "cancelled"}
            )
            self.assertEqual(
                sum(event.event_type == "compensation_succeeded" for event in journal.events),
                1,
            )
        finally:
            environment.close()

    def test_travel_trace_is_digest_only(self) -> None:
        environment, journal, _, _ = run_case(
            RECOVERY_TASK_ID,
            "r2_confirmed",
            "preferred_flight_unavailable",
        )
        try:
            serialized = journal.jsonl_bytes().decode("utf-8")
            self.assertNotIn("synthetic-traveler-", serialized)
            self.assertNotIn("synthetic-flight-", serialized)
            self.assertNotIn("synthetic-hotel-", serialized)
            self.assertNotIn('"arguments"', serialized)
            self.assertIn("fault.travel.preferred_flight.unavailable", serialized)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
