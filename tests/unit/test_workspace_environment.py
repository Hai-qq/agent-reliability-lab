from __future__ import annotations

import unittest

from arl.core.types import ToolAction
from arl.envs.workspace import (
    SCHEMA_VERSION,
    WORKSPACE_TASK_ID,
    WorkspaceEnvironment,
)
from arl.experiments.workspace_paired import oracle_actions


class WorkspaceEnvironmentTests(unittest.TestCase):
    def test_reset_hash_is_stable_over_twenty_resets(self) -> None:
        environment = WorkspaceEnvironment()
        try:
            for seed in range(3):
                hashes = {environment.reset(WORKSPACE_TASK_ID, seed).state_hash for _ in range(20)}
                self.assertEqual(len(hashes), 1)
        finally:
            environment.close()

    def test_snapshot_restore_returns_to_initial_state(self) -> None:
        environment = WorkspaceEnvironment()
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            initial_hash = environment.state_hash()
            snapshot = environment.snapshot()
            result = environment.step(oracle_actions(observation)[0])
            self.assertTrue(result.ok)
            self.assertNotEqual(environment.state_hash(), initial_hash)
            environment.restore(snapshot)
            self.assertEqual(environment.state_hash(), initial_hash)
            self.assertEqual(environment.state_version, 0)
            self.assertEqual(environment.logical_time, 0)
        finally:
            environment.close()

    def test_duplicate_invitation_transaction_rolls_back(self) -> None:
        environment = WorkspaceEnvironment()
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            create_result = environment.step(oracle_actions(observation)[0])
            self.assertTrue(create_result.ok)
            before_hash = environment.state_hash()
            recipient = observation.visible_task["recipients"][0]
            result = environment.step(
                ToolAction(
                    tool_name="messages.send_invitations",
                    schema_version=SCHEMA_VERSION,
                    arguments={
                        "event_id": observation.visible_task["event_id"],
                        "recipients": [recipient, recipient],
                    },
                    expected_state_version=1,
                )
            )
            self.assertEqual(result.status, "fatal_error")
            self.assertEqual(result.error_code, "duplicate_invitation")
            self.assertEqual(environment.state_hash(), before_hash)
            self.assertEqual(environment.export_world()["invitations"], [])
        finally:
            environment.close()

    def test_stale_state_version_returns_typed_conflict(self) -> None:
        environment = WorkspaceEnvironment()
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            action = oracle_actions(observation)[0]
            stale_action = ToolAction(
                tool_name=action.tool_name,
                schema_version=action.schema_version,
                arguments=action.arguments,
                expected_state_version=99,
            )
            before_hash = environment.state_hash()
            result = environment.step(stale_action)
            self.assertEqual(result.status, "conflict")
            self.assertEqual(result.error_code, "state_version_conflict")
            self.assertEqual(result.state_hash_before, before_hash)
            self.assertEqual(result.state_hash_after, before_hash)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
