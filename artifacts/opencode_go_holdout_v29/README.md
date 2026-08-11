# OpenCode Go Prospective Holdout v0.29

This public-safe artifact records the completed 2,592-episode, three-seed ARL
holdout matrix for OpenCode Go `deepseek-v4-flash` and `qwen3.7-plus`.

## Disposition

- 2,592/2,592 episodes completed, including a verified checkpoint resume.
- Infrastructure validity is **false**. Two Qwen calls exhausted the frozen
  retry policy with HTTP 503, and four Qwen episodes exceeded the preregistered
  USD 0.01 usage-value cap.
- Flash passed clean readiness in all three seeds. Qwen did not.
- Both confirmatory and exploratory analysis builders failed closed; neither
  `analysis.json` nor `exploratory-analysis.json` exists.
- Aggregate R2-minus-R1 recovery differences remain available only as
  descriptive point estimates in `summary.json`; they are not inferential
  claims or a successful replication result.

## Files

- `summary.json`: compact aggregate, failed gates, readiness, manifests, usage,
  and evidence hashes.
- `validation.log`: commands, resume audit, exact failures, hashes, and limits.
- `full-summary.json` and `study/`: local evidence of record excluded by
  `.gitignore`; their hashes remain in the public compact summary.

The run persisted no provider request/response bodies or credential. Both
models share one OpenCode Go gateway, so the matrix cannot identify provider
effects or support cross-provider generalization.
