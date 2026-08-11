# OpenCode Go Flash + Qwen Main v0.28

This public-safe artifact records the completed 864-episode ARL main matrix for
OpenCode Go `deepseek-v4-flash` and `qwen3.7-plus`.

## Disposition

- 864/864 episodes completed with 18/18 infrastructure checks passing.
- The run recorded zero unrecovered provider or protocol errors. One Flash HTTP
  503 recovered through the preregistered bounded retry policy.
- Flash clean `SafePass@3` was 18/24 at R0, R1, and R2.
- Qwen clean `SafePass@3` was 17/24, 18/24, and 17/24; the preregistered
  per-runtime 75% readiness gate therefore failed.
- The confirmatory builder failed closed and no `analysis.json` exists.
- `exploratory-analysis.json` is explicitly non-confirmatory. Its paired
  task-bootstrap intervals cannot be cited as the preregistered primary result.

## Files

- `summary.json`: compact aggregate, gates, manifests, usage, and evidence hashes.
- `exploratory-analysis.json`: 10,000 paired task-cluster bootstrap samples,
  labelled exploratory with `confirmatory_claim_allowed=false`.
- `validation.log`: commands, hashes, results, checks, and limitations.
- `full-summary.json` and `study/`: local evidence of record excluded by
  `.gitignore`; their hashes remain in the public compact summary.

Provider request/response bodies and the process-only credential are not
persisted. Both models share one OpenCode Go gateway, so this result is not
cross-provider evidence.
