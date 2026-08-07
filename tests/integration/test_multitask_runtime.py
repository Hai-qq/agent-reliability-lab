from __future__ import annotations

import unittest

from arl.envs.workspace import WORKSPACE_TASK_ID
from arl.runtime.journal import EventJournal
from arl_multitask.env import RESCHEDULE_TASK_ID, MultiTaskWorkspaceEnvironment
from arl_multitask.evaluator import evaluate_workspace_multitask
from arl_multitask.experiment import task_actions
from arl_multitask.runtime import MultiTaskRuntime


def run_case(task_id: str, runtime_name: str, fault_mode: str):
    environment = MultiTaskWorkspaceEnvironment(fault_mode=fault_mode)
    observation = environment.reset(task_id, 0)
    pre_snapshot = environment.snapshot()
    journal = EventJournal(
        run_id="v03-test",
        episode_id=f"{task_id}-{runtime_name}-{fault_mode}",
        task_id=task_id,
        seed=0,
    )
    execution = MultiTaskRuntime(runtime_name).execute(
        environment,
        task_actions(observation, runtime_name),
        journal,
    )
    evaluation = evaluate_workspace_multitask(
        pre_snapshot,
        environment.snapshot(),
        journal.as_dicts(),
    )
    return environment, journal, execution, evaluation


class MultiTaskRuntimeTests(unittest.TestCase):
    def test_r1_reschedule_fault_stops_before_request_resolution(self) -> None:
        environment, _, execution, evaluation = run_case(
            RESCHEDULE_TASK_ID,
            "r1_guarded",
            "reschedule_notifications_postcommit_timeout_once",
        )
        try:
            world = environment.export_world()
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "state_version_conflict")
            self.assertEqual(execution.retry_count, 1)
            self.assertFalse(evaluation.task_success)
            self.assertEqual(world["change_requests"][0]["status"], "pending")
        finally:
            environment.close()

    def test_r2_reschedule_fault_confirms_notifications_and_finishes(self) -> None:
        environment, journal, execution, evaluation = run_case(
            RESCHEDULE_TASK_ID,
            "r2_confirmed",
            "reschedule_notifications_postcommit_timeout_once",
        )
        try:
            world = environment.export_world()
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.retry_count, 0)
            self.assertEqual(execution.confirmation_count, 1)
            self.assertTrue(evaluation.safe_success)
            self.assertEqual(world["change_requests"][0]["status"], "resolved")
            self.assertEqual(len(world["reschedule_notifications"]), 2)
            self.assertEqual(
                sum(event.event_type == "state_confirmation_succeeded" for event in journal.events),
                1,
            )
        finally:
            environment.close()

    def test_r2_original_task_still_recovers_event_postcommit_fault(self) -> None:
        environment, _, execution, evaluation = run_case(
            WORKSPACE_TASK_ID,
            "r2_confirmed",
            "event_postcommit_timeout_once",
        )
        try:
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.confirmation_count, 1)
            self.assertTrue(evaluation.safe_success)
        finally:
            environment.close()

    def test_multitask_trace_is_digest_only(self) -> None:
        environment, journal, _, _ = run_case(
            RESCHEDULE_TASK_ID,
            "r2_confirmed",
            "reschedule_notifications_postcommit_timeout_once",
        )
        try:
            serialized = journal.jsonl_bytes().decode("utf-8")
            self.assertNotIn("@synthetic.invalid", serialized)
            self.assertNotIn('"participants"', serialized)
            self.assertNotIn('"recipients"', serialized)
            self.assertIn(
                "fault.workspace.reschedule_notifications.postcommit_timeout_once",
                serialized,
            )
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
