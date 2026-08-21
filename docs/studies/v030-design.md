# arl-study-v0.30.0 design (no model execution)

This is a preregistration-ready design and scripted infrastructure preflight. It is not
a model study result. No provider call, credential, response, or model outcome is
present.

The catalog contains 48 planning task templates across workspace, retail, and travel;
each of six known fault families owns eight task-template clusters. Eleven unseen
variants include delayed acknowledgement, duplicate delivery, stale read after write,
confirmation conflict, partial compensation failure, authorization expiry, out-of-order
callback, correlated multi-call failure, recovery-path timeout, unsafe retry, and
no-safe-recovery.

The frozen design uses three environment seeds, three trials, R1/R2 as the primary
comparison, R0 as a descriptive baseline, four conditions, two unbound model slots, and
a blocked randomized order. The power simulation is a frozen design assumption using
task-template clusters; its first candidate at or above 80% simulated power is 48. This
assumption must be reviewed before execution and is not evidence of an observed effect.

Run the provider-free preflight from an installed editable checkout:

```bash
python scripts/run_v030_scripted_preflight.py
```

It checks clean/recoverable/no-safe-recovery oracles, evaluator mutations, duplicate
side effects, unsafe retry, public evidence generation and verification, schedule
reproducibility/balance, and budget feasibility. A future provider run requires a new
explicit authorization, frozen model/provider bindings, pricing snapshot, source
commit, protected output path, and public-evidence plan.
