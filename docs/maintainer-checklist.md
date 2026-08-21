# Maintainer checklist

The following controls require a maintainer to configure GitHub UI/repository settings;
workflow files cannot prove they are enabled.

## Latest verified execution

As of 2026-08-21, the repository controls and the
[`v0.4.0` release](https://github.com/Hai-qq/agent-reliability-lab/releases/tag/v0.4.0)
were verified as follows:

- `main` requires pull requests, branch synchronization, conversation resolution, and
  19 app-bound CI, evidence, package, documentation, and security checks. The rule is
  enforced for administrators and prohibits force pushes and deletion. The approving
  review count is zero because this is currently a single-maintainer repository.
- The active `v*` tag ruleset restricts creation, deletion, and non-fast-forward updates;
  only the `Hai-qq` user is an audited bypass actor.
- Private vulnerability reporting, Dependabot alerts, Dependabot security updates,
  secret scanning, and push protection are enabled.
- The protected `release` environment requires `Hai-qq` review and accepts only `v*`
  tags. The `github-pages` environment accepts only `main`. Repository and `release`
  environment secret counts were both zero, and PyPI publication remains absent.
- [Release run 32495993842](https://github.com/Hai-qq/agent-reliability-lab/actions/runs/32495993842)
  targeted commit `8b3f97c218f9843ba26b281c65f27902a738b85e` and passed identity,
  wheel verification, metadata, checksums, provenance attestation, and asset upload.
- A clean post-publication download audit matched all six GitHub asset digests, all five
  entries in `checksums.txt`, and all six SLSA provenance attestations. The downloaded
  wheel and sdist each passed a Python 3.11 clean install, CLI smoke, verifier, and
  version check. The 874-file source manifest matched the raw Git blobs at the tag.

The unchecked boxes below remain a reusable settings/release procedure rather than a
live status dashboard. Re-run every applicable check for future releases.

## Repository settings

- [ ] Protect `main` and require pull requests.
- [ ] Require current CI, evidence, package, docs, and security status checks.
- [ ] Require branches to be up to date before merge.
- [ ] Prohibit force pushes to `main`.
- [ ] Prohibit deletion of `main`.
- [ ] Restrict tag creation/deletion for `v*` release tags.
- [ ] Enable private vulnerability reporting.
- [ ] Enable Dependabot alerts and security updates.

## Environments

- [ ] Create a protected `release` environment with required human reviewers.
- [ ] Keep PyPI publication disabled until trusted publishing is deliberately configured
  in that protected environment.
- [ ] Protect the `github-pages` environment and restrict deployment to `main`.
- [ ] Review environment secrets; normal CI/evidence jobs should have none.

## Release approval

- [ ] Confirm tag/version/changelog/CITATION agreement.
- [ ] Confirm wheel/sdist clean-environment smoke and public bundle verification.
- [ ] Confirm checksums, SBOM, source manifest, and GitHub artifact attestation.
- [ ] Confirm baseline tracked artifact digest is unchanged.
- [ ] Confirm v0.28/v0.29 claims and validity states are unchanged.
- [ ] Confirm no provider call or credential was used by release automation.
- [ ] Verify the GitHub Release assets from a clean download before archival.
