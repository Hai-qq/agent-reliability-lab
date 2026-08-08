# ARL Compact Artifact Bundle v0.15

Compact Artifact Bundle v0.15 keeps the public repository inspectable without discarding reproducibility. The full local v0.10–v0.13 study and trace trees contain 940 formal files plus 940 byte-identical repeat files. The public tree replaces those nested files with four deterministic, lossless ZIP bundles and one machine-readable manifest.

Summaries, validation logs, contract documents and the Evidence Explorer remain ordinary readable files. Local full artifacts are preserved in place and only excluded from Git; nothing is deleted.

## Bundle inventory

| Increment | Contents | Files | ZIP size | SHA-256 |
|---|---|---:|---:|---|
| v0.10 | Study state, 36 result JSON, 36 traces | 73 | 109,553 B | `47042f7e203a…b6f097` |
| v0.11 | Parallel state, 36 result JSON, 36 final + 2 attempt traces | 75 | 119,462 B | `bebd13cc1fea…e042eb` |
| v0.12 | Scenario Pack digest-only traces | 72 | 114,715 B | `6b5f3e160292…efec8d` |
| v0.13 | Symbolic User digest-only traces | 720 | 792,615 B | `605a09b574f6…cbd24` |

Every formal source tree is byte-identical to its repeat tree, so one ZIP per increment is sufficient. `manifest.json` retains the two restore targets, every member SHA-256, the canonical tree hash and the bundle SHA-256.

## Deterministic format

The builder sorts POSIX member paths and fixes all archive metadata:

- timestamp `1980-01-01 00:00:00`;
- Unix regular-file mode `0100644`;
- ZIP deflate level 9;
- no directory entries, encryption, absolute paths or `..` components.

It hashes the source before and during archive construction, then reopens every output ZIP and verifies every member. A second complete build produced byte-identical manifests and ZIPs.

## Verify and restore

Verification works directly from a public clone and does not create files:

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/manage_artifact_bundles.py verify \
  --bundle-dir artifacts/release_bundle_v15
```

To reconstruct both formal and repeat full trees in a clone where the ignored targets do not yet exist:

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/manage_artifact_bundles.py restore \
  --bundle-dir artifacts/release_bundle_v15 \
  --project-root .
```

Restore first verifies every bundle and refuses if any of the eight target directories already exists. It never merges with a partial or existing evidence tree. The validation gate restored 1,880 files into a clean temporary root and reproduced all four formal/repeat tree manifests exactly.

## Evidence

- [Machine-readable manifest](../artifacts/release_bundle_v15/manifest.json)
- [Four deterministic bundles](../artifacts/release_bundle_v15/bundles/)
- [Independent repeat manifest](../artifacts/release_bundle_v15_repeat/manifest.json)
- [Commands, hashes, restore and size gates](../artifacts/release_bundle_v15/validation.log)

## Boundaries

- bundles contain only ARL-generated digest traces, typed results and scheduler state;
- no upstream benchmark source, task payload, model content or personal data;
- no model/API call, external network, account, credential or real system;
- bundles improve public presentation but do not replace the direct summary/validation evidence.
