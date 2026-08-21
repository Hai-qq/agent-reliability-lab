from __future__ import annotations

import subprocess
import sys
import unittest
from importlib.metadata import version
from pathlib import Path

import arl
from arl.environments import StatefulEnvironment
from arl.evaluation import StateEvaluator
from arl.evidence import EvidenceWriter
from arl.faults import FaultInjector
from arl.providers import ModelBackend
from arl.runtime import AgentPolicy, ReliabilityRuntime


class StablePublicApiTests(unittest.TestCase):
    def test_distribution_version_comes_from_installed_metadata(self) -> None:
        self.assertEqual(arl.__version__, version("agent-reliability-lab"))
        self.assertEqual(arl.__version__, "0.4.0")

    def test_protocols_are_importable_from_stable_namespaces(self) -> None:
        protocols = [
            StatefulEnvironment,
            StateEvaluator,
            EvidenceWriter,
            FaultInjector,
            ModelBackend,
            AgentPolicy,
            ReliabilityRuntime,
        ]
        self.assertTrue(all(getattr(item, "_is_runtime_protocol", False) for item in protocols))

    def test_all_examples_run_offline(self) -> None:
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "examples/minimal_environment/example.py",
            "examples/custom_fault/example.py",
            "examples/custom_runtime/example.py",
        ):
            with self.subTest(example=relative):
                result = subprocess.run(
                    [sys.executable, relative],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
