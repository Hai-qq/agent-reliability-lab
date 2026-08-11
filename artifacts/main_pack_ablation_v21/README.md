# Main Pack Mechanism Ablation v0.21

v0.21 tests whether the 24-task pack actually depends on the reliability mechanisms attributed to R2. It runs the R2 baseline and six leave-one-mechanism-out variants on all 24 recoverable-fault tasks:

```text
24 faulted tasks x (R2 baseline + 6 leave-one-out variants) = 168 episodes
```

The full R2 baseline passes 24/24. Removing idempotency, state confirmation, input-schema adaptation, output normalization, conflict rebase, or bounded compensation reduces SafeSuccess to 20/24, with the expected four target tasks lost. All policy digests remain identical across variants, so the comparison changes runtime middleware rather than the agent plan.

The formal and independent repeat summaries are byte-identical, as are all 168 traces. See [summary.json](./summary.json) for machine-readable evidence and [validation.log](./validation.log) for commands, hashes and boundaries.

This is a deterministic mechanism-validity experiment. It does not measure an LLM and must not be presented as the two-model confirmatory main study.
