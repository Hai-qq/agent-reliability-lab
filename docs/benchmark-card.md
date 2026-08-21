# Benchmark card

## Intended use

Agent Reliability Lab (ARL) is a local fault-injection benchmark and reliability
runtime for stateful tool-using agents. It compares runtime interventions using
deterministic synthetic environments, state-level evaluators, and audit-ready public
evidence. It is suitable for runtime development, regression testing, paired
reliability studies, and external artifact review.

It is not a general intelligence leaderboard, a safety certification, a production
service test, or evidence about real people/accounts. Scripted preflights test the
harness, not model quality.

## Unit of analysis

The resampling cluster is a task template. A paired unit retains the template,
environment seed, sampling trial, model slot, R1/R2 runtime, and corresponding
clean/fault conditions. The primary new effect is the unconditional paired fault
safe-pass difference. Runtime-specific clean-conditioned ratios are retained only as
descriptive diagnostics.

## Components

- Stateful synthetic environments with deterministic reset and snapshots.
- Fault contracts with injection point, hidden ground truth, valid/prohibited recovery,
  invariants, side-effect boundaries, and mutation tests.
- R0 descriptive baseline plus R1/R2 confirmatory runtime comparison in v0.30.
- State evaluators that bind clause outcomes to allowlisted public state projections.
- `arl-evidence-v1` bundles with canonical JSON, deterministic gzip, SHA-256 links, and
  deny-by-default redaction.
- Offline CLI paths for smoke, verification, analysis, claims, studies, and diagnosis.

## Evidence coverage

| Study | Public status | Permitted interpretation |
| --- | --- | --- |
| v0.28 | infrastructure valid; Qwen readiness failed | exploratory only; no confirmatory claim |
| v0.29 | 2,592 scheduled episodes; infrastructure and Qwen readiness failed | descriptive aggregates only; episode ledger not materialized publicly |
| v0.30 | contract and scripted preflight only | no model result |
| `arl-smoke-v1` | complete public synthetic bundle | installation/verifier demonstration only |

## Data and privacy

Core environments are project-owned synthetic systems. Public evidence rejects API
keys, authorization headers, bearer tokens, cookies, email-like values, private keys,
raw prompts, raw responses, raw reasoning, hidden system prompts, and any state field
outside an explicit allowlist. Unknown fields abort publication.

## Reproducibility

Run `arl verify <bundle>` to check file bytes, schemas, cardinality, unique cells,
schedule order, cross-file digests, aggregate recomputation, analysis inputs,
redaction policy, provider accounting, and public evaluator clauses. Verification is
offline and returns a non-zero exit status on failure.

## Known limits

Historical v0.28/v0.29 model slots shared a gateway, execution order was fixed serially,
and public episode-level evidence is not currently materialized. Synthetic domains do
not establish real-system external validity. Pricing and provider behavior drift; a
future execution must freeze both. Independent cross-provider replication is pending.
