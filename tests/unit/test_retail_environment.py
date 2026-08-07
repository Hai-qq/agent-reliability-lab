from __future__ import annotations

import unittest

from arl.core.types import ToolAction
from arl_retail.env import (
    PURCHASE_TASK_ID,
    REFUND_TASK_ID,
    SCHEMA_VERSION,
    RetailEnvironment,
)
from arl_retail.experiment import task_actions


class RetailEnvironmentTests(unittest.TestCase):
    def test_purchase_reset_and_snapshot_restore_are_deterministic(self) -> None:
        environment = RetailEnvironment()
        try:
            observation = environment.reset(PURCHASE_TASK_ID, 0)
            initial_hash = environment.state_hash()
            snapshot = environment.snapshot()
            self.assertTrue(environment.step(task_actions(observation, "r2_confirmed")[0]).ok)
            environment.restore(snapshot)
            self.assertEqual(environment.state_hash(), initial_hash)
            self.assertEqual(environment.state_version, 0)
        finally:
            environment.close()

    def test_purchase_oracle_selects_lowest_post_coupon_offer(self) -> None:
        environment = RetailEnvironment()
        try:
            observation = environment.reset(PURCHASE_TASK_ID, 1)
            actions = task_actions(observation, "r2_confirmed")
            for action in actions:
                self.assertTrue(environment.step(action).ok)
            world = environment.export_world()
            target = min(
                observation.visible_task["offers"],
                key=lambda offer: (offer["final_unit_cents"], offer["product_id"]),
            )
            self.assertEqual(world["orders"][0]["total_cents"], target["final_unit_cents"] * 2)
            self.assertEqual(world["order_items"][0]["product_id"], target["product_id"])
            self.assertEqual(world["purchase_requests"][0]["status"], "resolved")
        finally:
            environment.close()

    def test_order_idempotent_replay_and_key_conflict(self) -> None:
        environment = RetailEnvironment()
        try:
            observation = environment.reset(PURCHASE_TASK_ID, 0)
            actions = task_actions(observation, "r2_confirmed")
            self.assertTrue(environment.step(actions[0]).ok)
            self.assertTrue(environment.step(actions[1]).ok)
            self.assertTrue(environment.step(actions[2]).ok)
            before_hash = environment.state_hash()
            self.assertTrue(environment.step(actions[2]).ok)
            self.assertEqual(environment.state_hash(), before_hash)
            changed = dict(actions[2].arguments)
            changed["order_id"] += "-changed"
            conflict = environment.step(
                ToolAction(
                    tool_name=actions[2].tool_name,
                    schema_version=actions[2].schema_version,
                    arguments=changed,
                    idempotency_key=actions[2].idempotency_key,
                    expected_state_version=actions[2].expected_state_version,
                )
            )
            self.assertEqual(conflict.status, "conflict")
            self.assertEqual(conflict.error_code, "idempotency_key_reused")
            self.assertEqual(environment.state_hash(), before_hash)
        finally:
            environment.close()

    def test_duplicate_refund_transaction_rolls_back(self) -> None:
        environment = RetailEnvironment()
        try:
            observation = environment.reset(REFUND_TASK_ID, 0)
            action = task_actions(observation, "r1_guarded")[0]
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
            self.assertEqual(duplicate.error_code, "refund_transaction_conflict")
            self.assertEqual(environment.state_hash(), before_hash)
            world = environment.export_world()
            self.assertEqual(len(world["refunds"]), 1)
            target_item = next(
                item
                for item in world["order_items"]
                if item["product_id"] == observation.visible_task["product_id"]
            )
            self.assertEqual(target_item["refunded_quantity"], 1)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
