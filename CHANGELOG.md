# Changelog

All notable software-distribution changes are documented here. Historical study
contracts keep their original versions and artifacts.

## [Unreleased]

No provider study is scheduled by this changelog.

## [0.4.0] - 2026-08-21

### Added

- Stable `arl` Protocol facades and offline CLI.
- Strict `arl-evidence-v1` schemas, deny-by-default redaction, deterministic bundles,
  verifier, and synthetic smoke evidence.
- Paired estimands, task-template cluster bootstrap, exact McNemar sensitivity, budget
  feasibility, provider audit events, and blocked randomized schedules.
- v0.30 design-only contract and scripted preflight with no provider calls.
- Claims, benchmark, methodology, validity-threat, versioning, archival, and maintainer
  documentation.
- Cross-platform package, evidence, security, and release automation.

### Fixed

- Cross-platform trace bytes now use explicit UTF-8/LF rather than translated text
  writes.
- Historical source manifests resolve historical Git bytes instead of incorrectly
  requiring equality with the current release worktree.
- Validity error reporting no longer treats an aggregate boolean as a check object.

### Evidence status

- v0.28 remains blocked for confirmatory use because Qwen readiness failed.
- v0.29 remains invalid for inference and descriptive only.
- v0.29 public episode evidence remains `NOT_MATERIALIZED`.

[Unreleased]: https://github.com/Hai-qq/agent-reliability-lab/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/Hai-qq/agent-reliability-lab/releases/tag/v0.4.0
