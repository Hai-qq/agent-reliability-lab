#!/usr/bin/env python3
"""Require immutable action SHAs and default-deny workflow permissions."""

from __future__ import annotations

import re
from pathlib import Path

ACTION = re.compile(r"^\s*(?:-\s*)?uses:\s*[^\s@]+@([^\s#]+)", re.MULTILINE)
SHA = re.compile(r"^[0-9a-f]{40}$")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    failures: list[str] = []
    workflows = sorted((root / ".github/workflows").glob("*.yml"))
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        if not re.search(r"(?m)^permissions:\s*\{\}\s*$", text):
            failures.append(f"{workflow.name}: top-level permissions must be {{}}")
        references = ACTION.findall(text)
        if not references:
            failures.append(f"{workflow.name}: no pinned action references")
        for reference in references:
            if not SHA.fullmatch(reference):
                failures.append(f"{workflow.name}: mutable action reference @{reference}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Verified immutable action pins and default permissions in {len(workflows)} workflows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
