from __future__ import annotations

import unittest

from arl.runtime.journal import EventJournal
from arl_retail.env import PURCHASE_TASK_ID, REFUND_TASK_ID, RetailEnvironment
from arl_retail.evaluator import evaluate_retail
from arl_retail.experiment import task_actions
from arl_retail.runtime import RetailRuntime


def run_case(task_id: str, runtime_name: str, fault_mode: str):
    environment = RetailEnvironment(fault_mode=fault_mode)
    observation = environment.reset(task_id, 0)
    pre_snapshot = environment.snapshot()
    journal = EventJournal(
        run_id="retail-v05-test",
        episode_id=f"{task_id}-{runtime_name}-{fault_mode}",
        task_id=task_id,
        seed=0,
    )
    execution = RetailRuntime(runtime_name).execute(
        environment,
        task_actions(observation, runtime_name),
        journal,
    )
    evaluation = evaluate_retail(
        pre_snapshot,
        environment.snapshot(),
        journal.as_dicts(),
    )
    return environment, journal, execution, evaluation


class RetailRuntimeTests(unittest.TestCase):
    def test_r1_purchase_fault_stops_before_request_resolution(self) -> None:
        environment, _, execution, evaluation = run_case(
            PURCHASE_TASK_ID,
            "r1_guarded",
            "order_postcommit_timeout_once",
        )
        try:
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "state_version_conflict")
            self.assertEqual(execution.retry_count, 1)
            self.assertFalse(evaluation.task_success)
            self.assertEqual(
                environment.export_world()["purchase_requests"][0]["status"], "pending"
            )
        finally:
            environment.close()

    def test_r2_purchase_fault_confirms_order_and_finishes(self) -> None:
        environment, journal, execution, evaluation = run_case(
            PURCHASE_TASK_ID,
            "r2_confirmed",
            "order_postcommit_timeout_once",
        )
        try:
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.retry_count, 0)
            self.assertEqual(execution.confirmation_count, 1)
            self.assertTrue(evaluation.safe_success)
            self.assertEqual(len(environment.export_world()["orders"]), 1)
            self.assertEqual(
                sum(event.event_type == "state_confirmation_succeeded" for event in journal.events),
                1,
            )
        finally:
            environment.close()

    def test_r1_refund_fault_stops_before_request_resolution(self) -> None:
        environment, _, execution, evaluation = run_case(
            REFUND_TASK_ID,
            "r1_guarded",
            "refund_postcommit_timeout_once",
        )
        try:
            self.assertFalse(execution.completed_plan)
            self.assertEqual(execution.failure_code, "state_version_conflict")
            self.assertFalse(evaluation.task_success)
            self.assertEqual(environment.export_world()["refund_requests"][0]["status"], "pending")
        finally:
            environment.close()

    def test_r2_refund_fault_confirms_refund_and_finishes(self) -> None:
        environment, _, execution, evaluation = run_case(
            REFUND_TASK_ID,
            "r2_confirmed",
            "refund_postcommit_timeout_once",
        )
        try:
            self.assertTrue(execution.completed_plan)
            self.assertEqual(execution.confirmation_count, 1)
            self.assertTrue(evaluation.safe_success)
            self.assertEqual(environment.export_world()["refund_requests"][0]["status"], "resolved")
        finally:
            environment.close()

    def test_retail_trace_is_digest_only(self) -> None:
        environment, journal, _, _ = run_case(
            REFUND_TASK_ID,
            "r2_confirmed",
            "refund_postcommit_timeout_once",
        )
        try:
            serialized = journal.jsonl_bytes().decode("utf-8")
            self.assertNotIn("synthetic-customer-", serialized)
            self.assertNotIn("synthetic-product-", serialized)
            self.assertNotIn('"arguments"', serialized)
            self.assertIn("fault.retail.refund.postcommit_timeout_once", serialized)
        finally:
            environment.close()


if __name__ == "__main__":
    unittest.main()
