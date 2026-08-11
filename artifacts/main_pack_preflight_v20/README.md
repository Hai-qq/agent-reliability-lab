# Main Pack Scripted Preflight v0.20

v0.20 turns the frozen 24-task blueprint into a fully runnable, project-owned benchmark pack. Workspace, Retail, and Travel each contribute eight synthetic tasks; the six recoverable-fault families each contain four tasks. This is a deterministic fixture/runtime/evaluator gate with zero model or network calls, not an LLM result.

The formal run contains 144 episodes:

```text
24 tasks x 2 conditions x 3 runtimes = 144 episodes
```

All three runtimes pass 24/24 clean tasks. Under recoverable faults, R0 passes 0/24, R1 passes 4/24, and R2 passes 24/24. The R2 minus R1 recovery-rate difference is `+0.8333333333333334`. Every catalog, evaluator-isolation, fault-registration, mechanism and digest-only trace gate passes.

The formal and independent repeat summaries are byte-identical, as are all 144 trace files. The machine-readable result is [summary.json](./summary.json); the exact commands, hashes and limits are recorded in [validation.log](./validation.log).

The main-study contract still fails closed because it requires two exact model bindings. v0.20 proves that all 24 local fixtures are runnable; it does not claim model capability or complete the 864-episode confirmatory study.
