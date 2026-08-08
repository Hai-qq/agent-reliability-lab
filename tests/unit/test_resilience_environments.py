from __future__ import annotations

import unittest
from dataclasses import replace

from arl_resilience.env import (
    RETAIL_METADATA_CONFLICT_FAULT_ID,
    RETAIL_ORDER_CONFLICT_FAULT_ID,
    TRAVEL_METADATA_CONFLICT_FAULT_ID,
    TRAVEL_RESERVATION_CONFLICT_FAULT_ID,
    ResilientRetailEnvironment,
    ResilientTravelEnvironment,
)
from arl_resilience.experiment import retail_resilience_plan
from arl_retail.env import PURCHASE_TASK_ID
from arl_travel.env import RECOVERY_TASK_ID
from arl_travel.experiment import task_plan as travel_task_plan


def advance_retail(environment: ResilientRetailEnvironment):
    observation = environment.reset(PURCHASE_TASK_ID, 0)
    plan = retail_resilience_plan(observation)
    for item in plan[:-1]:
        assert environment.step(item.action).ok
    return observation, plan[-1].action


def advance_travel(environment: ResilientTravelEnvironment):
    observation = environment.reset(RECOVERY_TASK_ID, 0)
    plan = travel_task_plan(observation, "r2_confirmed")
    assert environment.step(plan.primary_actions[0]).ok
    failure = environment.step(plan.primary_actions[1])
    assert failure.error_code == "flight_unavailable"
    return observation, plan.recovery_actions[0]


class ResilienceEnvironmentTests(unittest.TestCase):
    def test_retail_compatible_change_is_atomic_and_typed(self) -> None:
        environment = ResilientRetailEnvironment("compatible_conflict")
        try:
            _, action = advance_retail(environment)
            before = environment.state_hash()
            result = environment.step(action)
            world = environment.export_world()
            self.assertEqual(result.error_code, "state_version_conflict")
            self.assertEqual(result.state_hash_before, before)
            self.assertEqual(environment.last_fault_id, RETAIL_METADATA_CONFLICT_FAULT_ID)
            self.assertEqual(world["orders"][0]["status"], "placed")
            self.assertEqual(world["purchase_requests"][0]["status"], "pending")
        finally:
            environment.close()

    def test_retail_incompatible_change_restores_from_snapshot(self) -> None:
        environment = ResilientRetailEnvironment("incompatible_conflict")
        try:
            _, action = advance_retail(environment)
            snapshot = environment.snapshot()
            before = environment.state_hash()
            self.assertEqual(environment.step(action).error_code, "state_version_conflict")
            self.assertEqual(environment.last_fault_id, RETAIL_ORDER_CONFLICT_FAULT_ID)
            self.assertEqual(
                environment.export_world()["orders"][0]["status"],
                "externally_changed",
            )
            environment.restore(snapshot)
            self.assertEqual(environment.state_hash(), before)
            self.assertEqual(environment.export_world()["orders"][0]["status"], "placed")
        finally:
            environment.close()

    def test_travel_compatible_change_is_injected_once(self) -> None:
        environment = ResilientTravelEnvironment("compatible_conflict")
        try:
            _, action = advance_travel(environment)
            first = environment.step(action)
            self.assertEqual(environment.last_fault_id, TRAVEL_METADATA_CONFLICT_FAULT_ID)
            second = environment.step(
                replace(action, expected_state_version=environment.state_version)
            )
            self.assertEqual(first.error_code, "state_version_conflict")
            self.assertEqual(environment.last_fault_id, None)
            self.assertTrue(second.ok)
            self.assertEqual(
                environment.export_world()["hotel_reservations"][0]["status"],
                "cancelled",
            )
        finally:
            environment.close()

    def test_travel_incompatible_change_updates_target_status(self) -> None:
        environment = ResilientTravelEnvironment("incompatible_conflict")
        try:
            _, action = advance_travel(environment)
            result = environment.step(action)
            self.assertEqual(result.error_code, "state_version_conflict")
            self.assertEqual(environment.last_fault_id, TRAVEL_RESERVATION_CONFLICT_FAULT_ID)
            self.assertEqual(
                environment.export_world()["hotel_reservations"][0]["status"],
                "externally_changed",
            )
        finally:
            environment.close()

    def test_unknown_conflict_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ResilientRetailEnvironment("unknown")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            ResilientTravelEnvironment("unknown")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
