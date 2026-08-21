# arl-evidence-v1

The public bundle layout is:

```text
evidence/<study_id>/
  manifest.json
  study.json
  episodes.jsonl.gz
  provider-calls.jsonl.gz
  aggregate.json
  analysis.json
  redaction-policy.json
  README.md
  schemas/
```

The normative interoperable schemas are in `schemas/arl-evidence-v1/`. The Python
verifier additionally enforces canonical bytes, safe paths, exact file sets, cross-file
digests, episode/cell uniqueness, schedule order, aggregate recomputation, analysis
input linkage, logical-call linkage, the canonical redaction policy, and evaluator
clause outcomes against public state.

An episode's `trace_digest` is recomputed over its materialized normalized public
decisions, tool calls/results, fault/recovery events, evaluator outcomes, state
digests, and terminal reason. It is therefore an integrity check over obtainable
public trace content, not a substitute for an unavailable trace.

`aggregate.json` is also recomputed from the ledger and records every eligible
`SafePass@3` group. A group is eligible only when sampling trials are exactly 0, 1,
and 2 for the same task template, environment seed, Runtime, condition, and model
binding; all three episodes must be `SafeSuccess` to pass. Incomplete groups remain
visible with a null result instead of being silently dropped.

The verifier reconstructs the schedule digest from the ordered public cell dimensions
and reconstructs the task-catalog digest from its version plus all ledger task IDs.
Every episode must also carry the study's exact source-manifest digest; the bundle
manifest binds that same value. This verifies the public linkage without pretending
that a digest materializes historical source bytes that are absent.

`ProviderUsageRecorded` keeps token usage separate from transport and decision counts.
When a frozen pricing reconciliation is public, it may additionally carry a canonical
non-negative decimal `cost_usd` with `currency=USD`; otherwise both fields are null and
the explorer displays cost as not materialized.

Build a reviewed normalized private interchange directory with:

```bash
arl bundle PRIVATE_DIR --public-output evidence/STUDY_ID \
  --public-state-field status --public-state-field counter
arl verify evidence/STUDY_ID
```

`PRIVATE_DIR` must contain exactly `study.json`, `episodes.jsonl`, and
`provider-calls.jsonl` in the reviewed normalized shape. Unknown files or fields fail.
This generic migration intentionally does not ingest historical raw/full provider
directories. For v0.29, the public full episode inputs are absent; no bundle is
generated and the claim registry remains `NOT_MATERIALIZED`.
