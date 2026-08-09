# OpenCode Go Two-Model Main v0.27

v0.27 was ARL's first complete 864-episode run through the OpenCode Go gateway.
It paired `deepseek-v4-flash` with `mimo-v2.5` over the same 24 synthetic tasks,
three Runtime levels, clean/fault pairs, and three sampling trials. The run is
complete evidence, but it is not a valid confirmatory result.

## Why it is invalid

The frozen infrastructure contract required zero unrecovered provider errors
and zero local model-protocol errors. The run contained two separate failures:

1. `opencode-mimo-t0-travel.revise-dates.main-v1-r0_raw-clean` received HTTP
   503 from the provider.
2. `opencode-mimo-t2-retail.payment-order-split.main-v1-r1_guarded-clean`
   produced a response that the local structured-tool protocol rejected.

MiMo also missed the predeclared clean-capability qualification at R0 and R1:
its clean `SafePass@3` was 16/24, 17/24, and 19/24 for R0/R1/R2. Therefore both
`validity.all_selected_checks_passed` and
`readiness.ready_for_confirmatory_analysis` are false. The analysis builder
refused the input, and no confidence interval or hypothesis result exists.

The descriptive Flash counts—clean 18/24 at every Runtime and matched R1/R2
fault recovery of 5/18 versus 17/18—may help debug the harness, but they do not
rescue the invalid two-model study.

## Evidence and reproducibility

The public-safe [compact summary](../artifacts/opencode_go_main_v27/summary.json)
contains aggregates, typed failure evidence, contract metadata, and SHA-256
links to the local full result. The
[validation log](../artifacts/opencode_go_main_v27/validation.log) records the
exact command, hashes, failed checks, and limitations. The ignored local tree
contains all 864 result files and 864 digest-only traces; raw provider request,
response, and credential content were never persisted.

This run is retained rather than overwritten or selectively rerun. v0.28 is a
new, independently versioned study with a replacement comparison model and a
predeclared bounded transport-retry policy.
