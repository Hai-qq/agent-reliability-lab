from __future__ import annotations

import unittest
from dataclasses import replace

from arl.runtime.journal import EventJournal
from arl_conflict.env import ConflictWorkspaceEnvironment, conflicting_start_for_seed
from arl_conflict.evaluator import evaluate_workspace_conflict
from arl_conflict.experiment import conflict_plan
from arl_conflict.runtime import ConflictAwareRuntime
from arl_multitask.env import RESCHEDULE_TASK_ID
from arl_multitask.runtime import MultiTaskRuntime


def run_case(runtime_name: str, conflict_mode: str):
    environment = ConflictWorkspaceEnvironment(conflict_mode)  # type: ignore[arg-type]
    observation = environment.reset(RESCHEDULE_TASK_ID, 0)
    initial = environment.snapshot()
    journal = EventJournal(
        run_id="conflict-v08-test",
        episode_id=f"{runtime_name}-{conflict_mode}",
        task_id=RESCHEDULE_TASK_ID,
        seed=0,
    )
    plan = conflict_plan(observation)
    if runtime_name == "r2_conflict_aware":
        execution = ConflictAwareRuntime().execute(environment, plan, journal)
    else:
        execution = MultiTaskRuntime("r2_confirmed").execute(
            environment,
            [step.action for step in plan],
            journal,
        )
    evaluation = evaluate_workspace_conflict(
        initial,
        environment.snapshot(),
        journal.as_dicts(),
    )
    return environment, journal, execution, evaluation


class ConflictRuntimeTests(unittest.TestCase):
    def test_existing_r2_stops_on_compatible_state_conflict(self) -> None:
        environment, _, execution, evaluation = run_case(
            "r2_confirmed",
            "unrelated_state_change_before_update_once",
        )
        try:
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "state_version_conflict")
            self.assertFalse(evaluation.task_success)
        finally:
            environment.close()

    def test_conflict_aware_runtime_rebases_compatible_change(self) -> None:
        environment, journal, execution, evaluation = run_case(
            "r2_conflict_aware",
            "unrelated_state_change_before_update_once",
        )
        try:
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.conflict_probe_count, 1)
            self.assertEqual(execution.conflict_rebase_count, 1)
            self.assertEqual(execution.conflict_abort_count, 0)
            self.assertTrue(evaluation.safe_success)
            self.assertEqual(len(evaluation.recovery_events), 1)
            event_types = {event.event_type for event in journal.events}
            self.assertIn("state_conflict_detected", event_types)
            self.assertIn("state_conflict_rebased", event_types)
        finally:
            environment.close()

    def test_conflict_aware_runtime_fails_closed_on_changed_target(self) -> None:
        environment, journal, execution, evaluation = run_case(
            "r2_conflict_aware",
            "target_state_change_before_update_once",
        )
        try:
            world = environment.export_world()
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "conflict_precondition_changed")
            self.assertEqual(execution.conflict_probe_count, 1)
            self.assertEqual(execution.conflict_rebase_count, 0)
            self.assertEqual(execution.conflict_abort_count, 1)
            self.assertFalse(evaluation.task_success)
            self.assertEqual(world["calendar_events"][0]["start_at"], conflicting_start_for_seed(0))
            self.assertEqual(world["reschedule_notifications"], [])
            self.assertEqual(world["change_requests"][0]["status"], "pending")
            self.assertEqual(world["idempotency_records"], [])
            self.assertIn(
                "state_conflict_rejected",
                {event.event_type for event in journal.events},
            )
        finally:
            environment.close()

    def test_conflict_trace_contains_digests_not_payloads(self) -> None:
        environment, journal, _, _ = run_case(
            "r2_conflict_aware",
            "unrelated_state_change_before_update_once",
        )
        try:
            serialized = journal.jsonl_bytes().decode("utf-8")
            self.assertIn("state_conflict_rebased", serialized)
            self.assertNotIn("@synthetic.invalid", serialized)
            self.assertNotIn('"arguments"', serialized)
            self.assertNotIn("external-observer:", serialized)
        finally:
            environment.close()

    def test_missing_conflict_guard_fails_closed_without_probe(self) -> None:
        environment = ConflictWorkspaceEnvironment("unrelated_state_change_before_update_once")
        try:
            observation = environment.reset(RESCHEDULE_TASK_ID, 0)
            plan = conflict_plan(observation)
            plan[0] = replace(plan[0], guard=None)
            journal = EventJournal(
                run_id="conflict-v08-test",
                episode_id="missing-guard",
                task_id=RESCHEDULE_TASK_ID,
                seed=0,
            )
            execution = ConflictAwareRuntime().execute(environment, plan, journal)
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "conflict_guard_missing")
            self.assertEqual(execution.conflict_probe_count, 0)
            self.assertEqual(execution.conflict_abort_count, 1)
            self.assertEqual(environment.export_world()["reschedule_notifications"], [])
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
