from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_scenarios.catalog import TASK_TEMPLATES
from arl_symbolic.experiment import wilson_interval
from arl_symbolic.protocol import (
    INTENT_SCHEMAS,
    AuthorizationToken,
    SymbolicUserSession,
    cohort_engaged,
)
from scripts.run_symbolic_user import validate_paths


def session(condition: str, *, seed: int = 0, repeat_index: int = 0) -> SymbolicUserSession:
    return SymbolicUserSession(
        session_id="symbolic-unit",
        template=TASK_TEMPLATES[0],
        condition=condition,  # type: ignore[arg-type]
        seed=seed,
        repeat_index=repeat_index,
    )


class SymbolicProtocolTests(unittest.TestCase):
    def test_every_task_template_has_one_intent_schema(self) -> None:
        self.assertEqual(
            {item.template_id for item in INTENT_SCHEMAS},
            {item.template_id for item in TASK_TEMPLATES},
        )
        self.assertTrue(all(item.revision_field in item.required_fields for item in INTENT_SCHEMAS))

    def test_direct_response_has_current_digest_linked_token(self) -> None:
        target = session("direct_approval")
        response = target.request_authorization()
        self.assertEqual(response.status, "approved")
        self.assertIsNotNone(response.token)
        self.assertEqual(target.authorization_status(response.token), "current")
        evaluation = target.evaluate_commit(
            token=response.token,
            proposed_intent_digest=response.intent_digest,
            attempted=True,
        )
        self.assertTrue(evaluation.safe_success)

    def test_clarification_fills_exact_missing_field_or_safely_abandons(self) -> None:
        engaged = next(
            (seed, repeat_index)
            for repeat_index in range(20)
            for seed in range(20)
            if cohort_engaged(
                TASK_TEMPLATES[0].template_id,
                "clarification_required",
                seed,
                repeat_index,
            )
        )
        target = session("clarification_required", seed=engaged[0], repeat_index=engaged[1])
        response = target.request_authorization()
        self.assertEqual(response.status, "needs_clarification")
        self.assertTrue(target.clarify(response.missing_fields))
        self.assertEqual(target.request_authorization().status, "approved")

        abandoned = next(
            (seed, repeat_index)
            for repeat_index in range(20)
            for seed in range(20)
            if not cohort_engaged(
                TASK_TEMPLATES[0].template_id,
                "clarification_required",
                seed,
                repeat_index,
            )
        )
        target = session("clarification_required", seed=abandoned[0], repeat_index=abandoned[1])
        response = target.request_authorization()
        self.assertFalse(target.clarify(response.missing_fields))
        self.assertEqual(target.request_authorization().status, "abandoned")

    def test_revision_stales_old_token_and_tampering_is_invalid(self) -> None:
        target = session("precommit_revision")
        response = target.request_authorization()
        assert response.token is not None
        self.assertTrue(target.revise_before_commit())
        self.assertEqual(target.authorization_status(response.token), "stale")
        tampered = AuthorizationToken(
            session_id=response.token.session_id,
            revision=response.token.revision,
            intent_digest=response.token.intent_digest,
            token_digest="tampered",
        )
        self.assertEqual(target.authorization_status(tampered), "invalid")

    def test_wilson_interval_contains_observed_rate_and_validates_counts(self) -> None:
        interval = wilson_interval(8, 10)
        self.assertLessEqual(interval["lower"], 0.8)
        self.assertGreaterEqual(interval["upper"], 0.8)
        with self.assertRaises(ValueError):
            wilson_interval(1, 0)
        with self.assertRaises(ValueError):
            wilson_interval(11, 10)

    def test_runner_paths_refuse_overwrite_and_nested_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="arl-symbolic-cli-") as temporary:
            root = Path(temporary)
            validate_paths(root / "summary.json", root / "traces")
            with self.assertRaises(SystemExit):
                validate_paths(root / "traces/summary.json", root / "traces")
            output = root / "summary.json"
            output.write_text("existing", encoding="utf-8")
            with self.assertRaises(SystemExit):
                validate_paths(output, root / "traces")


if __name__ == "__main__":
    unittest.main()
