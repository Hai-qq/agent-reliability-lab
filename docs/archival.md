# Release archival and provenance

ARL releases are built from a clean tagged checkout. The GitHub Release should include
the wheel, sdist, checksums, public smoke evidence bundle, SPDX SBOM, source manifest,
and GitHub artifact attestation. Verify downloaded assets before depositing them.

For long-term preservation, a maintainer may connect the repository or upload the
verified release to a DOI-capable archival repository such as Zenodo or an institutional
archive. The archive record should include the Git tag and commit, release notes,
license, creators, checksums, source manifest, SBOM, public evidence bundle, methodology,
claim registry, and links back to the repository. Reserve or mint the DOI in the archive
itself, then update `CITATION.cff` and release metadata in a subsequent reviewed change.

No DOI is currently asserted by this document. Never guess a DOI or reuse one from a
different version. Historical provider artifacts that are not public-safe must not be
uploaded merely for completeness; record them as `NOT_MATERIALIZED` instead.
