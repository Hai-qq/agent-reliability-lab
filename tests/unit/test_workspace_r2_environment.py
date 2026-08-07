from __future__ import annotations

import unittest

from arl.core.types import ToolAction
from arl.envs.workspace import WORKSPACE_TASK_ID
from arl_r2.env import ReliableWorkspaceEnvironment
from arl_r2.experiment import workspace_actions


class ReliableWorkspaceEnvironmentTests(unittest.TestCase):
    def test_postcommit_timeout_returns_error_after_atomic_commit(self) -> None:
        environment = ReliableWorkspaceEnvironment(fault_mode="event_postcommit_timeout_once")
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            before_hash = environment.state_hash()
            result = environment.step(workspace_actions(observation, "r2_confirmed")[0])
            world = environment.export_world()
            self.assertEqual(result.status, "retryable_error")
            self.assertEqual(result.error_code, "tool_timeout_postcommit")
            self.assertNotEqual(before_hash, environment.state_hash())
            self.assertEqual(environment.state_version, 1)
            self.assertEqual(len(world["calendar_events"]), 1)
            self.assertEqual(len(world["idempotency_records"]), 1)
            self.assertEqual(
                environment.last_fault_id,
                "fault.workspace.event.postcommit_timeout_once",
            )
        finally:
            environment.close()

    def test_identical_idempotent_replay_returns_cached_result_without_write(self) -> None:
        environment = ReliableWorkspaceEnvironment()
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            action = workspace_actions(observation, "r2_confirmed")[0]
            first = environment.step(action)
            before_replay_hash = environment.state_hash()
            replay = environment.step(action)
            world = environment.export_world()
            self.assertTrue(first.ok)
            self.assertTrue(replay.ok)
            self.assertEqual(first.value, replay.value)
            self.assertEqual(environment.state_hash(), before_replay_hash)
            self.assertEqual(environment.state_version, 1)
            self.assertEqual(len(world["calendar_events"]), 1)
            self.assertEqual(len(world["idempotency_records"]), 1)
        finally:
            environment.close()

    def test_reusing_key_for_different_request_is_typed_conflict(self) -> None:
        environment = ReliableWorkspaceEnvironment()
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            action = workspace_actions(observation, "r2_confirmed")[0]
            self.assertTrue(environment.step(action).ok)
            changed_arguments = dict(action.arguments)
            changed_arguments["title"] = "Different synthetic title"
            before_hash = environment.state_hash()
            result = environment.step(
                ToolAction(
                    tool_name=action.tool_name,
                    schema_version=action.schema_version,
                    arguments=changed_arguments,
                    idempotency_key=action.idempotency_key,
                    expected_state_version=0,
                )
            )
            self.assertEqual(result.status, "conflict")
            self.assertEqual(result.error_code, "idempotency_key_reused")
            self.assertEqual(environment.state_hash(), before_hash)
        finally:
            environment.close()

    def test_snapshot_restore_includes_idempotency_state(self) -> None:
        environment = ReliableWorkspaceEnvironment()
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            initial_snapshot = environment.snapshot()
            initial_hash = environment.state_hash()
            self.assertTrue(environment.step(workspace_actions(observation, "r2_confirmed")[0]).ok)
            self.assertNotEqual(environment.state_hash(), initial_hash)
            environment.restore(initial_snapshot)
            self.assertEqual(environment.state_hash(), initial_hash)
            self.assertEqual(environment.export_world()["idempotency_records"], [])
        finally:
            environment.close()

    def test_observation_does_not_expose_fault_or_idempotency_metadata(self) -> None:
        environment = ReliableWorkspaceEnvironment(fault_mode="event_postcommit_timeout_once")
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            serialized = str(observation.as_dict()).lower()
            self.assertNotIn("fault_id", serialized)
            self.assertNotIn("postcommit", serialized)
            self.assertNotIn("idempotency_key", serialized)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
