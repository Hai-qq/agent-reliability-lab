"""Build, verify, and restore deterministic bundles of frozen ARL artifacts."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from arl.core.types import canonical_json
from arl_release import __version__


@dataclass(frozen=True)
class BundleSpec:
    slug: str
    version: str
    formal_source: str
    repeat_source: str
    bundle_file: str


BUNDLE_SPECS = (
    BundleSpec(
        slug="study-runtime",
        version="v0.10",
        formal_source="artifacts/study_runtime_v10/study",
        repeat_source="artifacts/study_runtime_v10_repeat/study",
        bundle_file="bundles/study-runtime-v10.zip",
    ),
    BundleSpec(
        slug="parallel-study",
        version="v0.11",
        formal_source="artifacts/parallel_study_v11/study",
        repeat_source="artifacts/parallel_study_v11_repeat/study",
        bundle_file="bundles/parallel-study-v11.zip",
    ),
    BundleSpec(
        slug="scenario-pack-traces",
        version="v0.12",
        formal_source="artifacts/scenario_pack_v12/traces",
        repeat_source="artifacts/scenario_pack_v12_repeat/traces",
        bundle_file="bundles/scenario-pack-v12-traces.zip",
    ),
    BundleSpec(
        slug="symbolic-user-traces",
        version="v0.13",
        formal_source="artifacts/symbolic_user_v13/traces",
        repeat_source="artifacts/symbolic_user_v13_repeat/traces",
        bundle_file="bundles/symbolic-user-v13-traces.zip",
    ),
)

ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
ZIP_MODE = 0o100644


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def tree_manifest(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise FileNotFoundError(f"Artifact source directory is missing: {root}")
    files = {
        path.relative_to(root).as_posix(): _sha256(path.read_bytes())
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }
    if not files:
        raise ValueError(f"Artifact source directory is empty: {root}")
    return files


def tree_manifest_sha256(files: dict[str, str]) -> str:
    return _sha256(canonical_json(files).encode("utf-8"))


def build_zip(root: Path, files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        for relative_path in sorted(files):
            payload = (root / relative_path).read_bytes()
            if _sha256(payload) != files[relative_path]:
                raise AssertionError(f"Artifact changed while bundling: {relative_path}")
            info = zipfile.ZipInfo(relative_path, date_time=ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = ZIP_MODE << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                info,
                payload,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            )
    return output.getvalue()


def build_bundle_catalog(project_root: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    records = []
    payloads = {}
    for spec in BUNDLE_SPECS:
        formal_root = project_root / spec.formal_source
        repeat_root = project_root / spec.repeat_source
        formal_files = tree_manifest(formal_root)
        repeat_files = tree_manifest(repeat_root)
        if formal_files != repeat_files:
            raise AssertionError(f"Formal/repeat artifact trees differ: {spec.version}")
        payload = build_zip(formal_root, formal_files)
        payloads[spec.bundle_file] = payload
        records.append(
            {
                "slug": spec.slug,
                "version": spec.version,
                "bundle_file": spec.bundle_file,
                "bundle_sha256": _sha256(payload),
                "bundle_size_bytes": len(payload),
                "file_count": len(formal_files),
                "tree_manifest_sha256": tree_manifest_sha256(formal_files),
                "files": formal_files,
                "formal_repeat_identical": True,
                "restore_targets": [spec.formal_source, spec.repeat_source],
            }
        )

    validity = {
        "bundle_count": {
            "expected": len(BUNDLE_SPECS),
            "actual": len(records),
            "passed": len(records) == len(BUNDLE_SPECS),
        },
        "formal_repeat_trees": {
            "file_count": sum(item["file_count"] for item in records),
            "passed": all(item["formal_repeat_identical"] for item in records),
        },
        "deterministic_zip_metadata": {
            "timestamp": list(ZIP_TIMESTAMP),
            "mode": oct(ZIP_MODE),
            "passed": True,
        },
        "local_synthetic_boundary": {
            "model_calls": 0,
            "external_network_calls": 0,
            "passed": True,
        },
    }
    validity["all_selected_checks_passed"] = all(
        item["passed"] for key, item in validity.items() if key != "all_selected_checks_passed"
    )
    return (
        {
            "metadata": {
                "increment_version": __version__,
                "format": "deterministic ZIP, deflate level 9",
                "purpose": "compact public evidence with lossless local restoration",
                "model_calls": 0,
                "external_network_calls": 0,
                "uses_only_synthetic_data": True,
            },
            "bundles": records,
            "validity": validity,
            "limitations": [
                (
                    "Bundles compact frozen evidence; summaries and validation logs "
                    "remain direct files."
                ),
                "Restore refuses existing targets and never merges with a partial artifact tree.",
                "No model, API, network, account, credential, personal data, or real system.",
            ],
        },
        payloads,
    )


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def inspect_bundle(payload: bytes) -> dict[str, Any]:
    files: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(payload), mode="r") as archive:
        for info in archive.infolist():
            if info.is_dir() or not _safe_member(info.filename):
                raise ValueError(f"Unsafe or unexpected ZIP member: {info.filename}")
            if info.flag_bits & 0x1:
                raise ValueError(f"Encrypted ZIP member is not supported: {info.filename}")
            if info.date_time != ZIP_TIMESTAMP:
                raise ValueError(f"Non-deterministic ZIP timestamp: {info.filename}")
            if info.compress_type != zipfile.ZIP_DEFLATED:
                raise ValueError(f"Unexpected ZIP compression: {info.filename}")
            if info.external_attr >> 16 != ZIP_MODE:
                raise ValueError(f"Unexpected ZIP mode: {info.filename}")
            if info.filename in files:
                raise ValueError(f"Duplicate ZIP member: {info.filename}")
            files[info.filename] = _sha256(archive.read(info))
    return {
        "file_count": len(files),
        "tree_manifest_sha256": tree_manifest_sha256(files),
        "files": files,
    }


def verify_bundle_dir(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = []
    for record in manifest["bundles"]:
        bundle_path = bundle_dir / record["bundle_file"]
        payload = bundle_path.read_bytes()
        inspected = inspect_bundle(payload)
        passed = (
            _sha256(payload) == record["bundle_sha256"]
            and len(payload) == record["bundle_size_bytes"]
            and inspected["file_count"] == record["file_count"]
            and inspected["tree_manifest_sha256"] == record["tree_manifest_sha256"]
            and inspected["files"] == record["files"]
        )
        checks.append(
            {
                "version": record["version"],
                "bundle_file": record["bundle_file"],
                "passed": passed,
            }
        )
    result = {
        "bundle_count": len(checks),
        "checks": checks,
        "passed": bool(checks) and all(item["passed"] for item in checks),
    }
    if not result["passed"]:
        raise AssertionError("Compact artifact bundle verification failed")
    return result


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def restore_bundles(bundle_dir: Path, project_root: Path) -> dict[str, Any]:
    verification = verify_bundle_dir(bundle_dir)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    targets = [
        project_root / target
        for record in manifest["bundles"]
        for target in record["restore_targets"]
    ]
    existing = [str(path) for path in targets if path.exists()]
    if existing:
        raise FileExistsError(f"Refusing to restore over existing targets: {existing}")

    restored_files = 0
    restored_targets = []
    for record in manifest["bundles"]:
        payload = (bundle_dir / record["bundle_file"]).read_bytes()
        with zipfile.ZipFile(io.BytesIO(payload), mode="r") as archive:
            for relative_target in record["restore_targets"]:
                target_root = project_root / relative_target
                for info in archive.infolist():
                    if not _safe_member(info.filename):
                        raise ValueError(f"Unsafe ZIP member: {info.filename}")
                    _write_atomic(target_root / info.filename, archive.read(info))
                    restored_files += 1
                restored_targets.append(relative_target)
    return {
        "verified_bundles": verification["bundle_count"],
        "restored_targets": restored_targets,
        "restored_file_writes": restored_files,
        "passed": True,
    }
