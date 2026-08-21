"""Verify recorded historical source bytes without equating them to the current tree."""

from __future__ import annotations

import hashlib
import subprocess
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

from arl.core.types import canonical_json


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@lru_cache(maxsize=4096)
def _digest_exists_in_git_history(root_text: str, relative_path: str, digest: str) -> bool:
    root = Path(root_text)
    if not (root / ".git").exists():
        return False
    log = subprocess.run(
        ["git", "log", "--all", "--format=%H", "--", relative_path],
        cwd=root,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if log.returncode != 0:
        return False
    for commit in log.stdout.decode("ascii", errors="ignore").splitlines():
        if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
            continue
        shown = subprocess.run(
            ["git", "show", f"{commit}:{relative_path}"],
            cwd=root,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if shown.returncode == 0 and _sha256(shown.stdout) == digest:
            return True
    return False


def verify_recorded_source_manifest(project_root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Resolve each recorded digest from the current file or immutable Git history.

    A historical manifest describes its own source snapshot. Requiring an evolving
    worktree to have identical bytes makes legitimate releases unverifiable. This
    verifier still fails closed: every path/digest must exist either now or in the
    repository history, and the manifest's canonical aggregate digest must match.
    """

    expected_files = manifest.get("files")
    expected_sha = manifest.get("sha256")
    if not isinstance(expected_files, dict) or not isinstance(expected_sha, str):
        return {"file_count": 0, "matched": False, "passed": False, "reason": "invalid_shape"}
    manifest_sha = _sha256(canonical_json(expected_files).encode("utf-8"))
    if manifest_sha != expected_sha:
        return {
            "file_count": len(expected_files),
            "expected_sha256": expected_sha,
            "recorded_sha256": manifest_sha,
            "matched": False,
            "passed": False,
            "reason": "recorded_manifest_digest_mismatch",
        }
    resolution = {"current_worktree": 0, "git_history": 0, "unresolved": 0}
    unresolved: list[str] = []
    root = project_root.resolve()
    for relative_path, digest in sorted(expected_files.items()):
        if not isinstance(relative_path, str) or not isinstance(digest, str) or len(digest) != 64:
            unresolved.append(str(relative_path))
            resolution["unresolved"] += 1
            continue
        pure = PurePosixPath(relative_path)
        if pure.is_absolute() or ".." in pure.parts:
            unresolved.append(relative_path)
            resolution["unresolved"] += 1
            continue
        current = root / Path(*pure.parts)
        if current.is_file() and _sha256(current.read_bytes()) == digest:
            resolution["current_worktree"] += 1
        elif _digest_exists_in_git_history(str(root), relative_path, digest):
            resolution["git_history"] += 1
        else:
            unresolved.append(relative_path)
            resolution["unresolved"] += 1
    passed = not unresolved
    return {
        "file_count": len(expected_files),
        "expected_sha256": expected_sha,
        "recorded_sha256": manifest_sha,
        "resolution": resolution,
        "unresolved": unresolved,
        "matched": passed,
        "passed": passed,
        "meaning": "recorded historical snapshot resolved; not asserted equal to current worktree",
    }
