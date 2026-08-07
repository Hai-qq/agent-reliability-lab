from __future__ import annotations

import unittest

from arl.core.types import ToolAction
from arl.envs.workspace import SCHEMA_VERSION, WORKSPACE_TASK_ID
from arl_multitask.env import RESCHEDULE_TASK_ID, MultiTaskWorkspaceEnvironment
from arl_multitask.experiment import task_actions


class MultiTaskWorkspaceEnvironmentTests(unittest.TestCase):
    def test_reschedule_reset_and_snapshot_restore_are_deterministic(self) -> None:
        environment = MultiTaskWorkspaceEnvironment()
        try:
            observation = environment.reset(RESCHEDULE_TASK_ID, 0)
            initial_hash = environment.state_hash()
            snapshot = environment.snapshot()
            world = environment.export_world()
            self.assertEqual(len(world["calendar_events"]), 1)
            self.assertEqual(world["change_requests"][0]["status"], "pending")
            self.assertEqual(observation.state_version, 0)
            self.assertTrue(environment.step(task_actions(observation, "r2_confirmed")[0]).ok)
            environment.restore(snapshot)
            self.assertEqual(environment.state_hash(), initial_hash)
            self.assertEqual(environment.state_version, 0)
        finally:
            environment.close()

    def test_notification_idempotent_replay_does_not_write_twice(self) -> None:
        environment = MultiTaskWorkspaceEnvironment()
        try:
            observation = environment.reset(RESCHEDULE_TASK_ID, 0)
            actions = task_actions(observation, "r2_confirmed")
            self.assertTrue(environment.step(actions[0]).ok)
            first = environment.step(actions[1])
            before_replay_hash = environment.state_hash()
            replay = environment.step(actions[1])
            self.assertTrue(first.ok)
            self.assertTrue(replay.ok)
            self.assertEqual(environment.state_hash(), before_replay_hash)
            self.assertEqual(
                len(environment.export_world()["reschedule_notifications"]),
                2,
            )
        finally:
            environment.close()

    def test_notification_key_reuse_with_different_request_is_conflict(self) -> None:
        environment = MultiTaskWorkspaceEnvironment()
        try:
            observation = environment.reset(RESCHEDULE_TASK_ID, 0)
            actions = task_actions(observation, "r2_confirmed")
            self.assertTrue(environment.step(actions[0]).ok)
            self.assertTrue(environment.step(actions[1]).ok)
            changed = dict(actions[1].arguments)
            changed["recipients"] = changed["recipients"][:1]
            before_hash = environment.state_hash()
            result = environment.step(
                ToolAction(
                    tool_name=actions[1].tool_name,
                    schema_version=actions[1].schema_version,
                    arguments=changed,
                    idempotency_key=actions[1].idempotency_key,
                    expected_state_version=1,
                )
            )
            self.assertEqual(result.status, "conflict")
            self.assertEqual(result.error_code, "idempotency_key_reused")
            self.assertEqual(environment.state_hash(), before_hash)
        finally:
            environment.close()

    def test_duplicate_notification_batch_rolls_back(self) -> None:
        environment = MultiTaskWorkspaceEnvironment()
        try:
            observation = environment.reset(RESCHEDULE_TASK_ID, 0)
            update = task_actions(observation, "r1_guarded")[0]
            self.assertTrue(environment.step(update).ok)
            recipient = observation.visible_task["recipients"][0]
            before_hash = environment.state_hash()
            result = environment.step(
                ToolAction(
                    tool_name="messages.send_reschedule_notifications",
                    schema_version=SCHEMA_VERSION,
                    arguments={
                        "event_id": observation.visible_task["event_id"],
                        "recipients": [recipient, recipient],
                        "target_start_at": observation.visible_task["new_start_at"],
                    },
                    expected_state_version=1,
                )
            )
            self.assertEqual(result.error_code, "duplicate_reschedule_notification")
            self.assertEqual(environment.state_hash(), before_hash)
            self.assertEqual(environment.export_world()["reschedule_notifications"], [])
        finally:
            environment.close()

    def test_invitation_write_is_idempotent_in_v03(self) -> None:
        environment = MultiTaskWorkspaceEnvironment()
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            actions = task_actions(observation, "r2_confirmed")
            self.assertTrue(environment.step(actions[0]).ok)
            self.assertTrue(environment.step(actions[1]).ok)
            before_hash = environment.state_hash()
            self.assertTrue(environment.step(actions[1]).ok)
            self.assertEqual(environment.state_hash(), before_hash)
            self.assertEqual(len(environment.export_world()["invitations"]), 2)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
