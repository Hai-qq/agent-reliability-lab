from __future__ import annotations

import unittest
from dataclasses import replace

from arl_schema.adapter import SchemaAdapter, SchemaAdapterError
from arl_schema.env import SchemaDriftEnvironment
from arl_travel.env import BOOK_TASK_ID, RECOVERY_TASK_ID
from arl_travel.experiment import task_plan


class SchemaAdapterTests(unittest.TestCase):
    def test_action_adapter_uses_only_public_descriptor(self) -> None:
        environment = SchemaDriftEnvironment("flight_action_schema_v2")
        try:
            observation = environment.reset(BOOK_TASK_ID, 0)
            canonical = task_plan(observation, "r2_confirmed").primary_actions[0]
            descriptor = environment.describe_tool("flights.book")
            adapted, changed = SchemaAdapter.adapt_action(canonical, descriptor)
            self.assertTrue(changed)
            self.assertEqual(adapted.schema_version, "2.0")
            self.assertEqual(
                set(adapted.arguments),
                {
                    "reservation_ref",
                    "flight_ref",
                    "traveler_ref",
                    "payment_ref",
                    "fare_acknowledged",
                },
            )
            self.assertTrue(environment.step(adapted).ok)
        finally:
            environment.close()

    def test_action_adapter_rejects_missing_and_extra_fields(self) -> None:
        environment = SchemaDriftEnvironment("flight_action_schema_v2")
        try:
            observation = environment.reset(BOOK_TASK_ID, 0)
            canonical = task_plan(observation, "r2_confirmed").primary_actions[0]
            descriptor = environment.describe_tool("flights.book")
            missing = dict(canonical.arguments)
            missing.pop("payment_id")
            extra = {**canonical.arguments, "payment_ref": "alias-collision"}
            with self.assertRaises(SchemaAdapterError):
                SchemaAdapter.adapt_action(replace(canonical, arguments=missing), descriptor)
            with self.assertRaises(SchemaAdapterError):
                SchemaAdapter.adapt_action(replace(canonical, arguments=extra), descriptor)
        finally:
            environment.close()

    def test_output_adapter_normalizes_exact_v2_result(self) -> None:
        environment = SchemaDriftEnvironment("hotel_result_schema_v2")
        try:
            observation = environment.reset(RECOVERY_TASK_ID, 0)
            action = task_plan(observation, "r2_confirmed").primary_actions[0]
            result = environment.step(action)
            normalized, changed = SchemaAdapter.normalize_result(
                tool_name=action.tool_name,
                result=result,
                descriptor=environment.describe_tool(action.tool_name),
            )
            self.assertTrue(changed)
            self.assertEqual(
                normalized.value,
                {
                    "booked_hotel_id": action.arguments["hotel_id"],
                    "hotel_reservation_id": action.arguments["reservation_id"],
                    "price_cents": observation.visible_task["preferred"]["hotel"]["price_cents"],
                },
            )
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
