from __future__ import annotations

import unittest
from dataclasses import replace

from arl.core.types import StepResult, ToolAction, canonical_json
from arl_resilience.contracts import CompensationContract, StateGuard


def guard(expected_value: str = "active") -> StateGuard:
    return StateGuard(
        tool_name="hotels.get_reservation",
        schema_version="1.0",
        arguments={"reservation_id": "synthetic-reservation"},
        value_path=("reservation", "status"),
        expected_value=expected_value,
    )


def result(value):
    return StepResult(
        status="ok",
        value=value,
        error_code=None,
        state_version=1,
        retry_after_ms=None,
        state_hash_before="before",
        state_hash_after="after",
        timestamp_logical=1,
    )


def contract() -> CompensationContract:
    return CompensationContract(
        contract_id="travel.refundable_hotel.cancel.v1",
        trigger_tool="flights.book",
        trigger_error="flight_unavailable",
        action=ToolAction(
            tool_name="hotels.cancel",
            schema_version="1.0",
            arguments={"reservation_id": "synthetic-reservation"},
            idempotency_key="synthetic-idempotency-key",
            expected_state_version=1,
        ),
        preconditions=(guard(),),
        postconditions=(guard("cancelled"),),
    )


class ResilienceContractTests(unittest.TestCase):
    def test_state_guard_requires_exact_public_read_value(self) -> None:
        target = guard()
        self.assertTrue(target.matches(result({"reservation": {"status": "active"}})))
        self.assertFalse(target.matches(result({"reservation": {"status": "cancelled"}})))
        self.assertFalse(target.matches(result({"reservation": {}})))

    def test_compensation_contract_matches_only_registered_trigger(self) -> None:
        target = contract()
        self.assertTrue(target.matches_trigger("flights.book", "flight_unavailable"))
        self.assertFalse(target.matches_trigger("flights.book", "payment_not_authorized"))

    def test_compensation_contract_rejects_unbounded_or_non_idempotent_action(self) -> None:
        target = contract()
        with self.assertRaises(ValueError):
            replace(target, max_attempts=2)
        with self.assertRaises(ValueError):
            replace(target, action=replace(target.action, idempotency_key=None))
        with self.assertRaises(ValueError):
            replace(target, preconditions=())

    def test_contract_audit_descriptor_contains_digests_not_payloads(self) -> None:
        serialized = canonical_json(contract().audit_descriptor())
        self.assertNotIn("synthetic-reservation", serialized)
        self.assertNotIn("synthetic-idempotency-key", serialized)
        self.assertIn("argument_digest", serialized)


if __name__ == "__main__":
    unittest.main()
