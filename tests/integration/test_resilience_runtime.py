from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arl_resilience.experiment import run_episode


class ResilienceRuntimeTests(unittest.TestCase):
    def test_existing_r2_stops_on_both_compatible_conflicts(self) -> None:
        for domain in ("retail", "travel"):
            with self.subTest(domain=domain):
                result = run_episode(
                    domain=domain,
                    runtime_name="r2_confirmed",
                    condition="compatible_conflict",
                    seed=0,
                    trace_path=None,
                )
                self.assertFalse(result["execution"]["completed_plan"])
                self.assertEqual(result["execution"]["failure_code"], "state_version_conflict")
                self.assertFalse(result["evaluation"]["task_success"])

    def test_guarded_runtime_recovers_compatible_retail_conflict(self) -> None:
        result = run_episode(
            domain="retail",
            runtime_name="r2_contract_guarded",
            condition="compatible_conflict",
            seed=0,
            trace_path=None,
        )
        self.assertTrue(result["execution"]["completed_plan"])
        self.assertEqual(result["execution"]["conflict_rebase_count"], 1)
        self.assertEqual(result["final_state"]["request_status"], "resolved")
        self.assertTrue(result["evaluation"]["safe_success"])
        self.assertEqual(len(result["evaluation"]["recovery_events"]), 1)

    def test_guarded_runtime_fails_closed_on_changed_retail_order(self) -> None:
        result = run_episode(
            domain="retail",
            runtime_name="r2_contract_guarded",
            condition="incompatible_conflict",
            seed=0,
            trace_path=None,
        )
        self.assertEqual(
            result["execution"]["failure_code"],
            "conflict_precondition_changed",
        )
        self.assertEqual(result["execution"]["conflict_abort_count"], 1)
        self.assertEqual(result["final_state"]["order_status"], "externally_changed")
        self.assertEqual(result["final_state"]["request_status"], "pending")

    def test_travel_compensation_contract_recovers_compatible_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-v09-recovery-") as temporary:
            trace_path = Path(temporary) / "trace.jsonl"
            result = run_episode(
                domain="travel",
                runtime_name="r2_contract_guarded",
                condition="compatible_conflict",
                seed=0,
                trace_path=trace_path,
            )
            trace_events = [
                json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]
        recovery_ids = set(result["evaluation"]["recovery_events"])
        recovery_types = {
            event["event_type"] for event in trace_events if event["event_id"] in recovery_ids
        }
        execution = result["execution"]
        self.assertTrue(execution["completed_plan"])
        self.assertEqual(execution["conflict_rebase_count"], 1)
        self.assertEqual(execution["compensation_contract_attempt_count"], 1)
        self.assertEqual(execution["compensation_contract_success_count"], 1)
        self.assertEqual(execution["compensation_probe_count"], 2)
        self.assertEqual(result["final_state"]["preferred_hotel_status"], "cancelled")
        self.assertEqual(result["final_state"]["request_status"], "resolved")
        self.assertTrue(result["evaluation"]["safe_success"])
        self.assertEqual(
            recovery_types,
            {
                "recovery_branch_started",
                "recovery_branch_succeeded",
                "state_conflict_rebased",
                "compensation_contract_succeeded",
            },
        )

    def test_travel_compensation_contract_classifies_changed_target(self) -> None:
        result = run_episode(
            domain="travel",
            runtime_name="r2_contract_guarded",
            condition="incompatible_conflict",
            seed=0,
            trace_path=None,
        )
        execution = result["execution"]
        self.assertFalse(execution["completed_plan"])
        self.assertEqual(execution["failure_code"], "conflict_precondition_changed")
        self.assertEqual(execution["compensation_contract_failure_count"], 1)
        self.assertEqual(result["final_state"]["preferred_hotel_status"], "externally_changed")
        self.assertEqual(result["final_state"]["request_status"], "pending")

    def test_resilience_trace_contains_digests_not_payloads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-v09-trace-") as temporary:
            path = Path(temporary) / "trace.jsonl"
            run_episode(
                domain="travel",
                runtime_name="r2_contract_guarded",
                condition="compatible_conflict",
                seed=0,
                trace_path=path,
            )
            serialized = path.read_text(encoding="utf-8")
        self.assertIn("compensation_contract_succeeded", serialized)
        self.assertIn("state_conflict_rebased", serialized)
        self.assertNotIn('"arguments"', serialized)
        self.assertNotIn("external-observer:", serialized)
        self.assertNotIn("synthetic-hotel", serialized)


if __name__ == "__main__":
    unittest.main()
