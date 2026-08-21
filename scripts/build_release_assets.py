#!/usr/bin/env python3
"""Build deterministic source manifest, SPDX SBOM, evidence ZIP, and checksums."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from arl import __version__
from arl.core.types import canonical_json
from arl.evidence.verify import verify_bundle

ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def tracked_manifest(root: Path) -> dict[str, object]:
    raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    relative_paths = [Path(item.decode("utf-8")) for item in raw.split(b"\0") if item]
    files = {path.as_posix(): digest((root / path).read_bytes()) for path in sorted(relative_paths)}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    return {
        "algorithm": "sha256(canonical_json({relative_path:file_sha256}))",
        "source_commit": commit,
        "file_count": len(files),
        "files": files,
        "sha256": digest(canonical_json(files).encode("utf-8")),
    }


def evidence_zip(root: Path) -> bytes:
    output = __import__("io").BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
        paths = sorted(
            (item for item in root.rglob("*") if item.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
        for path in paths:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(relative, ZIP_TIMESTAMP)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def spdx_sbom(source_manifest: dict[str, object]) -> dict[str, object]:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    created = datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    namespace_digest = digest(
        canonical_json(
            {"version": __version__, "source_commit": source_manifest["source_commit"]}
        ).encode("utf-8")
    )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"agent-reliability-lab-{__version__}",
        "documentNamespace": f"https://github.com/Hai-qq/agent-reliability-lab/sbom/{namespace_digest}",
        "creationInfo": {"created": created, "creators": ["Tool: arl-build-release-assets-v1"]},
        "packages": [
            {
                "name": "agent-reliability-lab",
                "SPDXID": "SPDXRef-Package",
                "versionInfo": __version__,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "MIT",
                "licenseDeclared": "MIT",
                "supplier": "Organization: Agent Reliability Lab contributors",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/agent-reliability-lab@{__version__}",
                    }
                ],
            }
        ],
        "relationships": [
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": "SPDXRef-Package",
            }
        ],
        "annotations": [
            {
                "annotationDate": created,
                "annotationType": "OTHER",
                "annotator": "Tool: arl-build-release-assets-v1",
                "comment": "Core runtime dependencies: none.",
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    dist = args.dist_dir.resolve()
    if not dist.is_dir():
        raise FileNotFoundError(f"dist directory does not exist: {dist}")
    verification = verify_bundle(args.evidence)
    if not verification.valid:
        raise ValueError(f"public evidence is invalid: {verification.errors}")
    manifest = tracked_manifest(project_root)
    write_new(
        dist / "source-manifest.json",
        (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(),
    )
    write_new(
        dist / "sbom.spdx.json",
        (
            json.dumps(spdx_sbom(manifest), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode(),
    )
    write_new(dist / "arl-smoke-v1.zip", evidence_zip(args.evidence))
    assets = sorted(
        (path for path in dist.iterdir() if path.is_file() and path.name != "checksums.txt"),
        key=lambda path: path.name,
    )
    checksum_lines = [f"{digest(path.read_bytes())}  {path.name}" for path in assets]
    write_new(dist / "checksums.txt", ("\n".join(checksum_lines) + "\n").encode())
    print(f"Built release metadata for {len(assets)} assets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
