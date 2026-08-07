# Schema Adapter v0.7 evidence

This directory is a checked-in, deterministic acceptance artifact for the local synthetic
schema-drift increment. It is product evidence for Agent Reliability Lab, not an external
benchmark score.

## Reproduce

Use Python 3.11 or 3.12 and choose fresh output paths; the runner refuses to overwrite existing
evidence.

```bash
PYTHONPATH=src python3.12 scripts/run_schema_adapter.py \
  --output artifacts/schema_adapter_v07_new/summary.json \
  --traces-dir artifacts/schema_adapter_v07_new/traces
```

The checked-in run used CPython 3.12.12, makes zero model or network calls, and uses only local
synthetic Travel state.

## Result

- Matrix: 2 tasks x 3 seeds x 2 runtimes x 2 conditions = 24 episodes and 24 JSONL traces.
- R1 guarded: clean `6/6`, schema-drift fault `0/6`, paired recovery rate `0.0`.
- R2 schema-adapted: clean `6/6`, schema-drift fault `6/6`, paired recovery rate `1.0`.
- R2 adaptations: 3 `flights.book` input mappings and 3 `hotels.book` result normalizations.
- All selected validity gates passed, including nine malformed-contract cases, non-oracular
  descriptors, 20 resets, snapshot restore, baseline rejection, digest-only traces, and all six
  historical source manifests.

## Integrity

- `summary.json` SHA-256:
  `a0b25f440651bfbe6776e2a4cb21c89630451775ad246fd4ae4735c4791b13d6`
- Source manifest SHA-256 (13 files):
  `75a7ba7fbec5728215e3c0556973a38d05eb378f760bb3b9ef9ad817dae8bf64`
- Trace manifest SHA-256 (24 files):
  `7cf55f84381bc661c2cbb971d572182e2a9617239d59aeac245cb0494a41f550`
- The formal and repeat summaries, plus every corresponding trace, are byte-identical.

## Limits

The adapter is a strict static registry for two controlled schema changes. It does not infer
mappings, negotiate unknown versions, combine simultaneous drift, call an LLM, or interact with
real accounts, credentials, third-party systems, or network targets.
