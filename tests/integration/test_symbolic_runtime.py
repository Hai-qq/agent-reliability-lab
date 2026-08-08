from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from arl_scenarios.catalog import TASK_TEMPLATES
from arl_symbolic.experiment import run_symbolic_session
from arl_symbolic.protocol import cohort_engaged


class SymbolicRuntimeIntegrationTests(unittest.TestCase):
    def test_one_shot_commits_without_missing_or_fresh_authorization(self) -> None:
        template = TASK_TEMPLATES[0]
        missing = run_symbolic_session(
            template_id=template.template_id,
            policy="one_shot",
            condition="clarification_required",
            seed=0,
            repeat_index=0,
            trace_path=None,
        )
        revised = run_symbolic_session(
            template_id=template.template_id,
            policy="one_shot",
            condition="precommit_revision",
            seed=0,
            repeat_index=0,
            trace_path=None,
        )
        self.assertTrue(missing["execution"]["unsafe_commit"])
        self.assertEqual(missing["execution"]["failure_code"], "authorization_missing")
        self.assertTrue(revised["execution"]["unsafe_commit"])
        self.assertEqual(revised["execution"]["failure_code"], "stale_authorization")

    def test_revision_aware_clarifies_and_reauthorizes_when_user_responds(self) -> None:
        template = TASK_TEMPLATES[0]
        for condition in ("clarification_required", "precommit_revision"):
            seed, repeat_index = next(
                (seed, repeat_index)
                for repeat_index in range(20)
                for seed in range(20)
                if cohort_engaged(template.template_id, condition, seed, repeat_index)
            )
            with self.subTest(condition=condition):
                result = run_symbolic_session(
                    template_id=template.template_id,
                    policy="revision_aware",
                    condition=condition,
                    seed=seed,
                    repeat_index=repeat_index,
                    trace_path=None,
                )
                self.assertTrue(result["execution"]["safe_success"])
                self.assertFalse(result["execution"]["unsafe_commit"])
        self.assertEqual(result["execution"]["reauthorization_count"], 1)
        self.assertEqual(result["execution"]["authorization_check_count"], 2)

    def test_revision_aware_abandonment_is_safe_abort(self) -> None:
        template = TASK_TEMPLATES[0]
        seed, repeat_index = next(
            (seed, repeat_index)
            for repeat_index in range(20)
            for seed in range(20)
            if not cohort_engaged(
                template.template_id,
                "precommit_revision",
                seed,
                repeat_index,
            )
        )
        result = run_symbolic_session(
            template_id=template.template_id,
            policy="revision_aware",
            condition="precommit_revision",
            seed=seed,
            repeat_index=repeat_index,
            trace_path=None,
        )
        self.assertTrue(result["execution"]["safe_abort"])
        self.assertFalse(result["execution"]["commit_attempted"])
        self.assertFalse(result["execution"]["unsafe_commit"])

    def test_symbolic_trace_is_digest_only(self) -> None:
        template = TASK_TEMPLATES[0]
        with tempfile.TemporaryDirectory(prefix="arl-symbolic-trace-") as temporary:
            trace_path = Path(temporary) / "trace.jsonl"
            run_symbolic_session(
                template_id=template.template_id,
                policy="revision_aware",
                condition="precommit_revision",
                seed=0,
                repeat_index=0,
                trace_path=trace_path,
            )
            serialized = trace_path.read_text(encoding="utf-8")
        self.assertIn("authorization_checked", serialized)
        self.assertIn("intent_revised", serialized)
        self.assertNotIn('"engaged"', serialized)
        self.assertNotIn('"selection"', serialized)
        self.assertNotIn('"arguments"', serialized)


if __name__ == "__main__":
    unittest.main()
