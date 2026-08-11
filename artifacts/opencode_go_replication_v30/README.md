# ARL Independent Reliability Study v0.30

This public-safe artifact records the completed 2,592-episode ARL study for
OpenCode Go `deepseek-v4-flash` and `deepseek-v4-pro`. It tests an original ARL
runtime hypothesis in local synthetic worlds; it is not a reproduction of an
upstream-paper leaderboard.

## Disposition

- 2,592/2,592 frozen episodes completed without selective reruns.
- Infrastructure validity is **false**. Four Pro clean episodes on the same
  synthetic cancellation task ended in `model_protocol_error` after repeated
  unknown tool/argument actions. Provider transport and parsing remained
  recoverable: 5 retries were recovered and 0 provider errors were unrecovered.
- Pro passed clean readiness for all three seeds. Flash did not: seed `30229`
  reached 17/24 R2 clean `SafePass@3`, below the frozen 18/24 minimum.
- Both analysis builders failed closed. Neither `analysis.json` nor
  `exploratory-analysis.json` exists, so no confidence interval or inferential
  main-effect claim is reported.
- The compact summary retains descriptive R2-minus-R1 matched fault-recovery
  differences of `+0.7158521303` for Flash and `+0.5537697253` for Pro. These
  are diagnostics, not a successful replication claim.

## Files

- `summary.json`: compact aggregate, failed gates, per-seed readiness, resource
  usage, manifests, and evidence hashes.
- `validation.log`: commands, exact failures, analysis-gate disposition,
  hashes, tests, and limitations.
- `full-summary.json` and `study/`: local evidence of record excluded by
  `.gitignore`; their hashes remain in the public compact summary.

The run used 11,079,571 provider-reported tokens and recorded USD 0.8473333474
as a usage-value estimate, not an incremental subscription charge. No provider
request/response body or credential was persisted. Both models share one
OpenCode Go gateway and the DeepSeek V4 family, so this study cannot establish
cross-provider or cross-family generalization.
