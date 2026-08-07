from __future__ import annotations

import unittest

from arl.core.types import ToolAction
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID, SCHEMA_VERSION, TravelEnvironment
from arl_travel.experiment import task_plan


class TravelEnvironmentTests(unittest.TestCase):
    def test_reset_and_snapshot_restore_are_deterministic(self) -> None:
        environment = TravelEnvironment()
        try:
            observation = environment.reset(BOOK_TASK_ID, 0)
            initial_hash = environment.state_hash()
            snapshot = environment.snapshot()
            first_action = task_plan(observation, "r2_confirmed").primary_actions[0]
            self.assertTrue(environment.step(first_action).ok)
            environment.restore(snapshot)
            self.assertEqual(environment.state_hash(), initial_hash)
            self.assertEqual(environment.state_version, 0)
        finally:
            environment.close()

    def test_book_oracle_selects_lowest_policy_compliant_bundle(self) -> None:
        environment = TravelEnvironment()
        try:
            observation = environment.reset(BOOK_TASK_ID, 1)
            plan = task_plan(observation, "r2_confirmed")
            for action in plan.primary_actions:
                self.assertTrue(environment.step(action).ok)
            world = environment.export_world()
            task = environment.task
            self.assertEqual(world["flight_bookings"][0]["flight_id"], task.target_flight_id)
            self.assertEqual(world["hotel_reservations"][0]["hotel_id"], task.target_hotel_id)
            total = (
                world["flight_bookings"][0]["price_cents"]
                + world["hotel_reservations"][0]["price_cents"]
            )
            self.assertEqual(total, task.expected_total_cents)
            self.assertLessEqual(total, task.budget_cents)
        finally:
            environment.close()

    def test_flight_idempotent_replay_and_key_conflict(self) -> None:
        environment = TravelEnvironment()
        try:
            observation = environment.reset(BOOK_TASK_ID, 0)
            action = task_plan(observation, "r2_confirmed").primary_actions[0]
            self.assertTrue(environment.step(action).ok)
            before_hash = environment.state_hash()
            self.assertTrue(environment.step(action).ok)
            self.assertEqual(environment.state_hash(), before_hash)
            changed = dict(action.arguments)
            changed["booking_id"] += "-changed"
            conflict = environment.step(
                ToolAction(
                    tool_name=action.tool_name,
                    schema_version=action.schema_version,
                    arguments=changed,
                    idempotency_key=action.idempotency_key,
                    expected_state_version=action.expected_state_version,
                )
            )
            self.assertEqual(conflict.status, "conflict")
            self.assertEqual(conflict.error_code, "idempotency_key_reused")
            self.assertEqual(environment.state_hash(), before_hash)
        finally:
            environment.close()

    def test_duplicate_hotel_reservation_rolls_back_inventory(self) -> None:
        environment = TravelEnvironment()
        try:
            observation = environment.reset(RECOVERY_TASK_ID, 0)
            action = task_plan(observation, "r1_guarded").primary_actions[0]
            self.assertTrue(environment.step(action).ok)
            before_hash = environment.state_hash()
            duplicate = environment.step(
                ToolAction(
                    tool_name=action.tool_name,
                    schema_version=SCHEMA_VERSION,
                    arguments=action.arguments,
                    expected_state_version=1,
                )
            )
            self.assertEqual(duplicate.error_code, "hotel_booking_transaction_conflict")
            self.assertEqual(environment.state_hash(), before_hash)
            self.assertEqual(len(environment.export_world()["hotel_reservations"]), 1)
        finally:
            environment.close()

    def test_preferred_flight_unavailable_fault_does_not_mutate_state(self) -> None:
        environment = TravelEnvironment(fault_mode="preferred_flight_unavailable")
        try:
            observation = environment.reset(RECOVERY_TASK_ID, 0)
            plan = task_plan(observation, "r2_confirmed")
            self.assertTrue(environment.step(plan.primary_actions[0]).ok)
            before_hash = environment.state_hash()
            result = environment.step(plan.primary_actions[1])
            self.assertEqual(result.error_code, "flight_unavailable")
            self.assertEqual(environment.state_hash(), before_hash)
            self.assertEqual(
                environment.last_fault_id,
                "fault.travel.preferred_flight.unavailable",
            )
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
