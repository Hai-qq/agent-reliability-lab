from __future__ import annotations

import unittest

from arl.core.types import digest_value
from arl.evidence.events import (
    adapt_legacy_provider_record,
    count_provider_events,
    validate_provider_event_ledger,
)


class ProviderAuditTests(unittest.TestCase):
    def test_failure_is_a_logical_call_without_invented_transport_start(self) -> None:
        events = adapt_legacy_provider_record(
            {
                "episode_id": "episode-1",
                "request_digest": digest_value({"request": 1}),
                "model_binding": "legacy-slot",
                "provider_error": "provider_http_503",
                "status": "failed",
            }
        )
        counts = count_provider_events(events)
        self.assertEqual(counts.logical_call_count, 1)
        self.assertEqual(counts.transport_attempt_count, 0)
        self.assertEqual(counts.provider_failure_count, 1)
        self.assertEqual(counts.usage_bearing_response_count, 0)

    def test_usage_and_accepted_decision_have_independent_counts(self) -> None:
        events = adapt_legacy_provider_record(
            {
                "episode_id": "episode-2",
                "request_digest": digest_value({"request": 2}),
                "model_binding": "legacy-slot",
                "usage": {"input_tokens": 10, "output_tokens": 4},
                "cost_usd": "0.0001",
                "currency": "USD",
                "decision_accepted": True,
                "status": "complete",
            }
        )
        counts = count_provider_events(events)
        self.assertEqual(counts.logical_call_count, 1)
        self.assertEqual(counts.usage_bearing_response_count, 1)
        self.assertEqual(counts.accepted_decision_count, 1)
        self.assertEqual(counts.provider_failure_count, 0)
        usage_event = next(item for item in events if item["event_type"] == "ProviderUsageRecorded")
        self.assertEqual(usage_event["cost_usd"], "0.0001")
        validate_provider_event_ledger(events)

    def test_logical_call_envelope_rejects_duplicate_start(self) -> None:
        events = adapt_legacy_provider_record(
            {
                "episode_id": "episode-3",
                "request_digest": digest_value({"request": 3}),
                "model_binding": "legacy-slot",
                "status": "complete",
            }
        )
        duplicate = dict(events[0])
        duplicate["sequence_index"] = 2
        events.insert(1, duplicate)
        for index, event in enumerate(events, start=1):
            event["sequence_index"] = index
        with self.assertRaises(ValueError):
            validate_provider_event_ledger(events)


if __name__ == "__main__":
    unittest.main()
