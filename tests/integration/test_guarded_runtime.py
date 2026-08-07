from __future__ import annotations

import unittest

from arl.envs.workspace import WORKSPACE_TASK_ID, WorkspaceEnvironment
from arl.evaluators.workspace import evaluate_workspace
from arl.experiments.workspace_paired import oracle_actions
from arl.runtime.journal import EventJournal
from arl.runtime.loop import GuardedRuntime


def run_case(runtime_name: str, faulted: bool):
    environment = WorkspaceEnvironment(
        fault_mode="invites_precommit_timeout_once" if faulted else "none"
    )
    observation = environment.reset(WORKSPACE_TASK_ID, 0)
    pre_snapshot = environment.snapshot()
    journal = EventJournal(
        run_id="test",
        episode_id=f"{runtime_name}-{'fault' if faulted else 'clean'}",
        task_id=WORKSPACE_TASK_ID,
        seed=0,
    )
    execution = GuardedRuntime(runtime_name).execute(
        environment,
        oracle_actions(observation),
        journal,
    )
    evaluation = evaluate_workspace(
        pre_snapshot,
        environment.snapshot(),
        journal.as_dicts(),
    )
    return environment, journal, execution, evaluation


class GuardedRuntimeTests(unittest.TestCase):
    def test_r0_clean_succeeds(self) -> None:
        environment, _, execution, evaluation = run_case("r0_raw", False)
        try:
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.retry_count, 0)
            self.assertTrue(evaluation.safe_success)
        finally:
            environment.close()

    def test_r0_fault_stops_on_retryable_error(self) -> None:
        environment, _, execution, evaluation = run_case("r0_raw", True)
        try:
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "tool_timeout_precommit")
            self.assertEqual(execution.retry_count, 0)
            self.assertFalse(evaluation.task_success)
        finally:
            environment.close()

    def test_r1_fault_retries_once_and_recovers(self) -> None:
        environment, journal, execution, evaluation = run_case("r1_guarded", True)
        try:
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.retry_count, 1)
            self.assertTrue(evaluation.safe_success)
            self.assertEqual(len(evaluation.recovery_events), 1)
            self.assertEqual(
                sum(event.event_type == "retry_scheduled" for event in journal.events),
                1,
            )
        finally:
            environment.close()

    def test_trace_contains_contract_fields_but_not_raw_arguments(self) -> None:
        environment, journal, _, _ = run_case("r1_guarded", True)
        try:
            required = {
                "run_id",
                "episode_id",
                "task_id",
                "seed",
                "event_id",
                "parent_event_id",
                "timestamp_logical",
                "actor",
                "event_type",
                "input_digest",
                "output_digest",
                "tool_name",
                "schema_version",
                "latency_ms",
                "token_usage",
                "monetary_cost",
                "state_hash_before",
                "state_hash_after",
                "error_code",
                "fault_id",
            }
            for event in journal.as_dicts():
                self.assertEqual(set(event), required)
            serialized = journal.jsonl_bytes().decode("utf-8")
            self.assertNotIn("@synthetic.invalid", serialized)
            self.assertNotIn("participants", serialized)
            self.assertNotIn("recipients", serialized)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
