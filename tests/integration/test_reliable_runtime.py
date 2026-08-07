from __future__ import annotations

import unittest

from arl.envs.workspace import WORKSPACE_TASK_ID
from arl.runtime.journal import EventJournal
from arl.runtime.loop import GuardedRuntime
from arl_r2.env import ReliableWorkspaceEnvironment
from arl_r2.evaluator import evaluate_workspace_r2
from arl_r2.experiment import workspace_actions
from arl_r2.runtime import ReliableRuntime


def run_case(runtime_name: str, faulted: bool):
    environment = ReliableWorkspaceEnvironment(
        fault_mode="event_postcommit_timeout_once" if faulted else "none"
    )
    observation = environment.reset(WORKSPACE_TASK_ID, 0)
    pre_snapshot = environment.snapshot()
    journal = EventJournal(
        run_id="r2-test",
        episode_id=f"{runtime_name}-{'fault' if faulted else 'clean'}",
        task_id=WORKSPACE_TASK_ID,
        seed=0,
    )
    actions = workspace_actions(observation, runtime_name)
    if runtime_name == "r1_guarded":
        execution = GuardedRuntime(runtime_name).execute(environment, actions, journal)
    else:
        execution = ReliableRuntime().execute(environment, actions, journal)
    evaluation = evaluate_workspace_r2(
        pre_snapshot,
        environment.snapshot(),
        journal.as_dicts(),
    )
    return environment, journal, execution, evaluation


class ReliableRuntimeTests(unittest.TestCase):
    def test_r1_blind_retry_cannot_finish_after_ambiguous_commit(self) -> None:
        environment, _, execution, evaluation = run_case("r1_guarded", True)
        try:
            world = environment.export_world()
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.retry_count, 1)
            self.assertEqual(execution.failure_code, "state_version_conflict")
            self.assertFalse(evaluation.task_success)
            self.assertEqual(len(world["calendar_events"]), 1)
            self.assertEqual(len(world["invitations"]), 0)
        finally:
            environment.close()

    def test_r2_confirms_commit_and_finishes_without_blind_retry(self) -> None:
        environment, journal, execution, evaluation = run_case("r2_confirmed", True)
        try:
            world = environment.export_world()
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.retry_count, 0)
            self.assertEqual(execution.confirmation_count, 1)
            self.assertTrue(evaluation.safe_success)
            self.assertEqual(len(evaluation.recovery_events), 1)
            self.assertEqual(len(world["calendar_events"]), 1)
            self.assertEqual(len(world["invitations"]), 2)
            self.assertEqual(
                sum(event.event_type == "state_confirmation_succeeded" for event in journal.events),
                1,
            )
        finally:
            environment.close()

    def test_r2_trace_is_digest_only(self) -> None:
        environment, journal, _, _ = run_case("r2_confirmed", True)
        try:
            serialized = journal.jsonl_bytes().decode("utf-8")
            self.assertNotIn("@synthetic.invalid", serialized)
            self.assertNotIn('"participants"', serialized)
            self.assertNotIn('"recipients"', serialized)
            self.assertIn("fault.workspace.event.postcommit_timeout_once", serialized)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
