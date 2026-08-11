# ARL v0.30 zero-model preflight

The public `summary.json` is the compact aggregate for the frozen 432-episode
task/runtime/evaluator gate. The complete `full-summary.json` and 432 JSONL
traces remain local and gitignored.

This preflight makes no provider request. It verifies the new task IDs,
requests, three data seeds, reset isolation, fault isolation, expected
R0/R1/R2 outcomes, all six reliability mechanisms, do-nothing rejection,
evaluator mutations, digest-only traces, exact model contract, and source
manifest linkage.

The result is ready for the repeated protocol/availability probe, not evidence
of model quality or the formal hypothesis.
