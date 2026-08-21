# Threats to validity

## Construct validity

`safe_success` combines task completion with evaluator clauses and absence of declared
severe side effects. It cannot cover undeclared harms or hidden state omitted from the
environment contract. Every new task therefore requires evaluator mutation tests,
duplicate-side-effect tests, unsafe-retry tests, and public projection checks. A trace
digest proves identity only when the referenced trace is obtainable; a hash is not a
substitute for materialized evidence.

## Internal validity

Historical v0.28/v0.29 studies used a fixed serial order. Runtime, condition, and model
cells may therefore be confounded by gateway load, temporal drift, retry behavior, or
price/usage changes. The studies are not rewritten. v0.30 instead freezes a blocked
randomized order within task-template × environment-seed × sampling-trial blocks and
stores the complete order plus digest before execution.

Provider failures, parse failures, accepted decisions, logical calls, and transport
attempts are separate quantities. Treating transport errors as zero policy calls can
otherwise obscure usage and retry semantics. New audit events use sequence indices and
monotonic durations; wall-clock timestamps stay outside reproducible digests.

## Statistical conclusion validity

The historical conditional quantity

\[
P(F_{R2}\mid C_{R2}) - P(F_{R1}\mid C_{R1})
\]

uses runtime-specific clean denominators and may compare different strata. It remains
`runtime_specific_conditional_recovery_difference` and `descriptive_only=true`. The
primary repaired estimand is

\[
\Delta_F = \operatorname{mean}(Y_{R2,\,fault} - Y_{R1,\,fault}),
\]

on all complete paired units. A secondary common-clean analysis retains only clusters
whose R1 and R2 clean cells both pass. Bootstrap resampling is by task template and
keeps every seed, trial, runtime, condition, and model slot together. New analyses of
v0.28/v0.29 are explicitly post hoc and cannot change their validity or claims.

## Budget and treatment fairness

A common USD cap can be structurally unfair when legal token responses have different
model prices. Under the frozen v0.29 token ceiling, Flash's cache-miss worst case is USD
0.00509376, while Qwen's is USD 0.0211072; the shared USD 0.01 cap was feasible for the
former and impossible for the latter. This diagnosis does not modify v0.29. New studies
share call/input/output token budgets, report cost as an outcome by default, and permit
only preflighted model-specific hard caps that cannot bind a legal maximum response.

## External validity

Local synthetic environments provide control and reproducibility, not proof of
production behavior. A shared gateway with two model slots is not cross-provider
replication. Results may not generalize to different tools, providers, languages,
latency regimes, account permissions, or real organizational workflows. External
replication remains pending until a third party publishes independently verifiable
evidence under a frozen binding.

## Evidence availability and selection

The public checkout lacks the ignored v0.29 full summary/study ledger. It therefore
cannot independently recompute all 2,592 episodes; the status is `NOT_MATERIALIZED`.
Failed cells are not rerun or deleted, and readiness/infrastructure thresholds are not
relaxed. Any future migration must consume the original local evidence read-only,
verify source/trace manifests first, and reject raw provider content.
