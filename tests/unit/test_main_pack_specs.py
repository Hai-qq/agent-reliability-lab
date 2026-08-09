from __future__ import annotations

import unittest

from arl.core.types import canonical_json
from arl_mainpack.specs import MAIN_TASK_SPECS, main_pack_catalog_audit
from arl_pilot.env import PilotEnvironment


class MainPackSpecTests(unittest.TestCase):
    def test_pack_exactly_completes_the_frozen_blueprint(self) -> None:
        audit = main_pack_catalog_audit()
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["task_count"], 24)
        self.assertEqual(
            audit["domain_counts"],
            {"retail": 8, "travel": 8, "workspace": 8},
        )
        self.assertEqual(set(audit["fault_family_counts"].values()), {4})
        self.assertEqual(
            audit["implementation_version_counts"],
            {"v017": 8, "v020": 16},
        )

    def test_all_input_drift_tasks_use_their_exact_task_mapping(self) -> None:
        specs = [spec for spec in MAIN_TASK_SPECS if spec.fault_family == "input_schema_drift"]
        self.assertEqual(len(specs), 4)
        drifted_field_sets = set()
        for spec in specs:
            environment = PilotEnvironment(spec, "recoverable_fault")
            try:
                environment.reset(spec.task_id, 0)
                operation = spec.operation(spec.fault_operation_id)
                semantic = operation.semantic_action()
                adapted = environment.adapt_input_action(semantic)
                drifted_field_sets.add(tuple(sorted(adapted.arguments)))
                self.assertEqual(adapted.schema_version, "2.0")
                self.assertTrue(environment.step(adapted).ok)
            finally:
                environment.close()
        self.assertGreaterEqual(len(drifted_field_sets), 3)

    def test_all_output_drift_tasks_normalize_to_distinct_canonical_results(self) -> None:
        specs = [spec for spec in MAIN_TASK_SPECS if spec.fault_family == "output_schema_drift"]
        self.assertEqual(len(specs), 4)
        canonical_results = set()
        for spec in specs:
            environment = PilotEnvironment(spec, "recoverable_fault")
            try:
                environment.reset(spec.task_id, 0)
                operation = spec.operation(spec.fault_operation_id)
                semantic = operation.semantic_action()
                drifted = environment.step(semantic)
                normalized = environment.normalize_result(semantic, drifted)
                self.assertTrue(environment.result_contract_valid(semantic, normalized))
                canonical_results.add(canonical_json(normalized.value))
            finally:
                environment.close()
        self.assertEqual(len(canonical_results), 4)

    def test_conflict_effects_are_task_local_and_guards_are_public(self) -> None:
        specs = [
            spec for spec in MAIN_TASK_SPECS if spec.fault_family == "compatible_state_conflict"
        ]
        self.assertEqual(len(specs), 4)
        effect_paths = {path for spec in specs for path, _ in spec.conflict_effects}
        self.assertEqual(len(effect_paths), 4)
        self.assertTrue(
            all(
                {path for path, _ in spec.conflict_guard}.issubset(spec.public_read_paths)
                for spec in specs
            )
        )


if __name__ == "__main__":
    unittest.main()
