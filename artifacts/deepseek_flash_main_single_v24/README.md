# DeepSeek Flash 24-Task Single-Slot Study v0.24

v0.24 runs one exact DeepSeek-V4-Flash binding across the complete 24-task ARL benchmark pack. It is the first model-backed execution of the full task catalog and a readiness gate for adding a second model; it is deliberately named a **single-slot study**, not the two-model confirmatory main study.

The frozen matrix is:

```text
24 tasks x 2 conditions x 3 runtimes x 1 model x 3 trials = 432 episodes
```

All 432 episodes completed. The 14 infrastructure-validity checks pass, including exact model binding, zero provider/protocol errors, non-thinking mode, hard per-episode budgets, digest-only traces, usage reconciliation and credential audit. R1 recovers 5 of its 18 clean-capable tasks; R2 recovers 17 of 18. The task-paired R2 minus R1 recovery-rate difference is `+0.6666666666666666`; a frozen 10,000-resample task-cluster bootstrap gives a 95% percentile interval of `[0.4444444444444444, 0.8823529411764706]`.

Public evidence:

- [summary.json](./summary.json): compact aggregate, validity, resource use and manifest bindings;
- [analysis.json](./analysis.json): 24 task rows, fault/domain breakdowns, mechanism counts and paired bootstrap;
- [validation.log](./validation.log): exact commands, versions, hashes, results and limits.

The complete 4,222,913-byte summary, 432 result files, 432 digest-only traces and study state remain in local ignored paths. Their hashes are retained in the compact summary. No credential or raw provider request/response is committed.

The run establishes single-model, single-seed evidence only. Six tasks fail clean `SafePass@3` under every Runtime, fault-family subgroups contain four tasks, the provider exposes neither a sampling seed nor immutable serving-weight hash, and a second exact model binding is still required before the frozen 864-episode contract can execute.
