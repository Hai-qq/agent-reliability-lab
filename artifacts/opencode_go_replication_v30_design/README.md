# ARL v0.30 frozen design evidence

This directory contains public-safe, machine-readable evidence for ARL's own
independent reliability replication. It is not an upstream-paper reproduction
artifact and contains no provider credential, prompt body, model response, or
real user data.

- `budget-calibration.json` recomputes the v0.29 resource distribution from
  the retained local full summary identified by SHA-256. It freezes the v0.30
  per-episode limits before any v0.30 provider call.
- The USD fields are provider usage-value estimates, not incremental
  subscription charges.
- The source v0.29 full summary remains local and gitignored; the calibration
  output exposes only aggregate maxima, quantiles, checks, and the source hash.

Provider execution is permitted only after the 432-episode zero-model preflight,
the current source manifest, the authenticated model catalog, the repeated
protocol/availability probe, and the 36-episode canary all pass.
