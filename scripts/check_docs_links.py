#!/usr/bin/env python3
"""Check repository-local Markdown links without network access."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    documents = [
        root / "README.md",
        root / "README.zh-CN.md",
        root / "CONTRIBUTING.md",
        root / "SECURITY.md",
        root / "GOVERNANCE.md",
        root / "ROADMAP.md",
        *sorted((root / "docs").rglob("*.md")),
    ]
    failures: list[str] = []
    for document in documents:
        for match in LINK.finditer(document.read_text(encoding="utf-8")):
            target = match.group(1).strip().split()[0].strip("<>")
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_text = unquote(target.split("#", 1)[0])
            if not path_text:
                continue
            path = (document.parent / path_text).resolve()
            try:
                path.relative_to(root.resolve())
            except ValueError:
                failures.append(f"{document.relative_to(root)} -> unsafe {target}")
                continue
            if not path.exists():
                failures.append(f"{document.relative_to(root)} -> missing {target}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Checked local links in {len(documents)} Markdown files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
