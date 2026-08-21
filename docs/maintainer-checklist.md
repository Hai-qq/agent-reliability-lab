# Maintainer checklist

The following controls require a maintainer to configure GitHub UI/repository settings;
workflow files cannot prove they are enabled.

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
