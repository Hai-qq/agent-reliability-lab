from __future__ import annotations

import unittest
from dataclasses import replace

from arl_conflict.env import (
    ENV_VERSION,
    TARGET_CONFLICT_FAULT_ID,
    UNRELATED_CONFLICT_FAULT_ID,
    ConflictWorkspaceEnvironment,
    conflicting_start_for_seed,
)
from arl_conflict.experiment import conflict_plan
from arl_multitask.env import RESCHEDULE_TASK_ID


class ConflictWorkspaceEnvironmentTests(unittest.TestCase):
    def test_compatible_concurrent_change_is_atomic_and_typed(self) -> None:
        environment = ConflictWorkspaceEnvironment("unrelated_state_change_before_update_once")
        try:
            observation = environment.reset(RESCHEDULE_TASK_ID, 0)
            before_hash = environment.state_hash()
            action = conflict_plan(observation)[0].action
            result = environment.step(action)
            world = environment.export_world()
            event = world["calendar_events"][0]

            self.assertEqual(observation.env_version, ENV_VERSION)
            self.assertEqual(result.status, "conflict")
            self.assertEqual(result.error_code, "state_version_conflict")
            self.assertEqual(result.state_hash_before, before_hash)
            self.assertNotEqual(result.state_hash_after, before_hash)
            self.assertEqual(environment.state_version, 1)
            self.assertEqual(event["start_at"], observation.visible_task["current_start_at"])
            self.assertEqual(environment.last_fault_id, UNRELATED_CONFLICT_FAULT_ID)
            self.assertEqual(world["idempotency_records"], [])
        finally:
            environment.close()

    def test_incompatible_change_updates_target_and_snapshot_restores(self) -> None:
        environment = ConflictWorkspaceEnvironment("target_state_change_before_update_once")
        try:
            observation = environment.reset(RESCHEDULE_TASK_ID, 1)
            initial_hash = environment.state_hash()
            snapshot = environment.snapshot()
            result = environment.step(conflict_plan(observation)[0].action)
            world = environment.export_world()

            self.assertEqual(result.error_code, "state_version_conflict")
            self.assertEqual(
                world["calendar_events"][0]["start_at"],
                conflicting_start_for_seed(1),
            )
            self.assertEqual(environment.last_fault_id, TARGET_CONFLICT_FAULT_ID)
            environment.restore(snapshot)
            self.assertEqual(environment.state_hash(), initial_hash)
            self.assertEqual(environment.state_version, 0)
            self.assertEqual(
                environment.export_world()["calendar_events"][0]["start_at"],
                observation.visible_task["current_start_at"],
            )
        finally:
            environment.close()

    def test_concurrent_change_is_injected_only_once(self) -> None:
        environment = ConflictWorkspaceEnvironment("unrelated_state_change_before_update_once")
        try:
            observation = environment.reset(RESCHEDULE_TASK_ID, 2)
            action = conflict_plan(observation)[0].action
            first = environment.step(action)
            second = environment.step(
                replace(action, expected_state_version=environment.state_version)
            )
            self.assertEqual(first.error_code, "state_version_conflict")
            self.assertTrue(second.ok)
            self.assertEqual(environment.state_version, 2)
        finally:
            environment.close()

    def test_unknown_conflict_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ConflictWorkspaceEnvironment("not-a-mode")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
