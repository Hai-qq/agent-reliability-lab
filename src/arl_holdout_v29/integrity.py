"""Source and trace integrity helpers shared by the v0.29 entrypoints."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from arl.core.types import canonical_json
from arl_study.scheduler import file_sha256


def source_manifest(project_root: Path) -> dict[str, Any]:
    paths = sorted(
        {
            project_root / "pyproject.toml",
            project_root / "src/arl/core/types.py",
            project_root / "src/arl/runtime/journal.py",
            project_root / "src/arl_study/scheduler.py",
            *project_root.glob("src/arl_mainstudy/**/*.py"),
            *project_root.glob("src/arl_pilot/**/*.py"),
            *project_root.glob("src/arl_mainpack/**/*.py"),
            *project_root.glob("src/arl_modelpilot/**/*.py"),
            *project_root.glob("src/arl_mainmodel/**/*.py"),
            *project_root.glob("src/arl_opencode_v28/**/*.py"),
            *project_root.glob("src/arl_holdout_v29/**/*.py"),
            project_root / "scripts/run_holdout_v29_preflight.py",
            project_root / "scripts/probe_opencode_go_v29.py",
            project_root / "scripts/run_opencode_go_v29.py",
            project_root / "scripts/build_opencode_go_v29_analysis.py",
            project_root / "scripts/build_opencode_go_v29_exploratory_analysis.py",
        }
    )
    missing = [str(path.relative_to(project_root)) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"v0.29 source manifest paths are missing: {missing}")
    files = {
        str(path.relative_to(project_root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    return {
        "algorithm": "sha256(canonical_json({relative_path: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest(),
        "files": files,
    }


def trace_manifest(workspace: Path) -> dict[str, Any]:
    files = {
        path.name: file_sha256(path) for path in sorted((workspace / "traces").glob("*.jsonl"))
    }
    return {
        "algorithm": "sha256(canonical_json({trace_filename: file_sha256}))",
        "sha256": hashlib.sha256(canonical_json(files).encode("utf-8")).hexdigest(),
        "files": files,
    }
