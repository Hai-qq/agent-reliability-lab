from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from arl.cli import main
from arl.core.types import canonical_json
from arl.studies.smoke import smoke_inputs


class StableCliTests(unittest.TestCase):
    def test_doctor_claims_and_studies(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["doctor"]), 0)
            self.assertEqual(main(["claims"]), 0)
            self.assertEqual(main(["studies"]), 0)

    def test_smoke_verify_analyze_and_invalid_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "smoke"
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["run", "smoke", "--output", str(bundle)]), 0)
                self.assertEqual(main(["verify", str(bundle)]), 0)
                self.assertEqual(main(["analyze", str(bundle), "--iterations", "50"]), 0)
            (bundle / "aggregate.json").write_bytes(b"{}\n")
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main(["verify", str(bundle)]), 1)

    def test_bundle_command_accepts_only_normalized_interchange(self) -> None:
        study, episodes = smoke_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private = root / "private"
            private.mkdir()
            (private / "study.json").write_text(
                json.dumps(study, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            (private / "episodes.jsonl").write_text(
                "".join(canonical_json(item) + "\n" for item in episodes), encoding="utf-8"
            )
            (private / "provider-calls.jsonl").write_text("", encoding="utf-8")
            output = root / "public"
            arguments = [
                "bundle",
                str(private),
                "--public-output",
                str(output),
                "--public-state-field",
                "counter",
                "--public-state-field",
                "side_effect_count",
                "--public-state-field",
                "status",
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(arguments), 0)
                self.assertEqual(main(["verify", str(output)]), 0)


if __name__ == "__main__":
    unittest.main()
