from __future__ import annotations

import unittest

from arl.envs.workspace import SCHEMA_VERSION, WORKSPACE_TASK_ID
from arl_multitask.env import MultiTaskWorkspaceEnvironment
from arl_validity.baselines import random_valid_action, run_random_valid_rollout


class ValidityBaselineUnitTests(unittest.TestCase):
    def test_hash_selected_action_is_deterministic_and_schema_valid(self) -> None:
        environment = MultiTaskWorkspaceEnvironment()
        try:
            observation = environment.reset(WORKSPACE_TASK_ID, 0)
            first = random_valid_action(
                observation,
                state_version=environment.state_version,
                policy_seed=7,
                step_index=2,
            )
            second = random_valid_action(
                observation,
                state_version=environment.state_version,
                policy_seed=7,
                step_index=2,
            )
        finally:
            environment.close()
        self.assertEqual(first, second)
        self.assertEqual(first[1].schema_version, SCHEMA_VERSION)
        self.assertIsInstance(first[1].arguments, dict)

    def test_rollout_exports_digests_not_raw_arguments(self) -> None:
        result = run_random_valid_rollout(WORKSPACE_TASK_ID, 0, 0)
        self.assertEqual(result["schema_error_count"], 0)
        serialized = str(result)
        self.assertNotIn("@synthetic.invalid", serialized)
        self.assertNotIn("recipients", serialized)


if __name__ == "__main__":
    unittest.main()
