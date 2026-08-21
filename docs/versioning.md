# Compatibility and versioning policy

ARL follows semantic versioning for the `agent-reliability-lab` Python distribution.
`pyproject.toml` is the sole distribution-version source and `arl.__version__` resolves
installed metadata. Public Protocol additions are backwards compatible; removing or
changing a stable Protocol member requires a distribution major release.

Study contracts, evidence schemas, task catalogs, and artifact bundles are separately
versioned immutable research objects. A distribution release may support many study
versions. It must not rename, rewrite, or silently reinterpret an existing study.

`arl-evidence-v1` is strict: unknown fields are rejected. Backwards-compatible readers
may add explicit adapters for older records, but writers cannot emit undeclared fields.
A breaking evidence change creates a new schema identifier and migration path. Artifact
bundle bytes are never overwritten; a corrected publication receives a new bundle
version and records what it supersedes.

Historical implementation packages such as `arl_holdout_v29` remain importable for
reproduction, but new integrations should use only the stable `arl.runtime`,
`arl.environments`, `arl.faults`, `arl.evaluation`, `arl.studies`, `arl.providers`,
`arl.evidence`, and `arl.analysis` namespaces.
