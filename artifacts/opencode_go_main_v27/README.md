# OpenCode Go Two-Model Main v0.27

This artifact records a completed but invalid 864-episode exploratory run of the
ARL 24-task reliability matrix with OpenCode Go `deepseek-v4-flash` and
`mimo-v2.5`. It is retained as failure evidence and must not be cited as a
confirmatory two-model result.

## Disposition

- 864/864 scheduled episodes completed with Python 3.12.12.
- The infrastructure validity gate failed because one MiMo request returned
  `provider_http_503` and one separate MiMo response was rejected locally as
  `model_protocol_error`.
- MiMo clean `SafePass@3` also missed the preregistered 75% qualification gate
  at R0 and R1: 16/24, 17/24, and 19/24 for R0/R1/R2.
- The confirmatory analysis command failed closed. No `analysis.json` exists.
- Flash-only and MiMo-only metrics remain descriptive diagnostics, not the
  preregistered confirmatory result.

## Files

- `summary.json`: compact, public-safe aggregate and typed episode evidence.
- `validation.log`: commands, hashes, gates, results, and limitations.
- `full-summary.json`, `study/`: complete local evidence, excluded by
  `.gitignore` because it is large and contains per-episode model records.

All persisted provider evidence is digest-only. The credential, raw requests,
raw responses, and model message content are absent from the artifact.
