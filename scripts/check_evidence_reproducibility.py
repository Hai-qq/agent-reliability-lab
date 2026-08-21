#!/usr/bin/env python3
"""Prove that the smoke bundle rebuild is byte-identical to itself and the fixture."""

from __future__ import annotations

import tempfile
from pathlib import Path

from arl.studies.smoke import run_smoke


def tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    expected = project_root / "evidence/arl-smoke-v1"
    with tempfile.TemporaryDirectory(prefix="arl-evidence-repro-") as temporary:
        root = Path(temporary)
        first = root / "first"
        second = root / "second"
        run_smoke(first)
        run_smoke(second)
        if tree(first) != tree(second):
            raise AssertionError("two smoke builds are not byte-identical")
        if tree(first) != tree(expected):
            raise AssertionError("committed smoke evidence is stale or changed")
    print("Smoke evidence is byte-identical across two builds and the committed fixture")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
