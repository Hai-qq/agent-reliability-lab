# ARL v0.30 Independent Reliability Replication

v0.30 is a new experiment for the original Agent Reliability Lab project. It
does not rerun an upstream paper leaderboard and does not repair, censor, or
replace the failed v0.29 evidence. Its purpose is to test ARL's own claim that a
state-aware reliability runtime improves recoverable-fault completion without
damaging clean-task safety.

## Frozen status

- Design date: 2026-08-10.
- Parent evidence commit: `1cb56bb25d2b5c6093d5566888af483415b9c05b`.
- v0.29 remains completed but infrastructure-invalid.
- No v0.29 failed cell is reused or selectively rerun.
- The v0.30 code, task catalog, thresholds, retry policy, budget calibration,
  and analysis seed must be frozen before the first v0.30 provider call.

## Models and claim boundary

| Slot | Exact binding | Inference control | Role |
| --- | --- | --- | --- |
| Flash | `opencode-go/deepseek-v4-flash/listing-2026-08-10/non-thinking` | thinking disabled | retained primary anchor |
| Pro | `opencode-go/deepseek-v4-pro/listing-2026-08-10/non-thinking` | thinking disabled | previously uncalled comparison |

The current [official OpenCode Go documentation](https://dev.opencode.ai/docs/go/)
lists both models on the OpenAI-compatible Chat Completions endpoint and
publishes zero-day retention for them. Pro was selected before any Pro ARL
outcome was observed. MiMo-V2.5 and Qwen3.7 Plus are not reused as co-primary
models because their prior ARL studies missed the frozen clean-readiness gate.

Both slots still share OpenCode Go and the DeepSeek V4 family. A valid result can
support within-gateway, within-family runtime consistency; it cannot establish
cross-provider or cross-family generalization.

## Independent matrix

`24 tasks × 3 environment seeds × 2 conditions × 3 runtimes × 3 trials ×
2 models = 2,592 episodes`.

- New seeds: `30113`, `30229`, `30347`.
- All 24 template IDs and user requests are disjoint from the v0.28 main pack
  and v0.29 holdout.
- Context values, operation IDs, record identities, task IDs, and state
  namespaces are regenerated under the v0.30 catalog.
- The six runtime mechanism archetypes and public tool schemas are intentionally
  reused so the intervention remains R0/R1/R2 rather than a task redesign.

## Result-informed budget, frozen before calls

The calibration source is the retained v0.29 full summary with SHA-256
`ae59041b7314ea765da00cc40008d98751d856deece478378eeef99e0c5e2800`.
The public aggregate is
[`budget-calibration.json`](../artifacts/opencode_go_replication_v30_design/budget-calibration.json).

| Per-episode limit | Frozen value |
| --- | ---: |
| logical model calls | 8 |
| input tokens | 20,000 |
| output tokens | 8,192 |
| accounted output reservation per response | 1,024 |
| usage value | USD 0.015 |
| serialized-request framing reserve | 2,048 input tokens |

Before every external call, the backend reserves the UTF-8 serialized request
byte count plus the framing reserve, the maximum accounted response, and the
corresponding worst-case cache-miss usage value. If any projected episode total
would exceed a limit, the episode stops with
`model_budget_reservation_exhausted` before network dispatch. Provider usage
above a reservation invalidates the study; it is never accepted and relabeled
afterward.

The USD 0.015 ceiling is 25.8% above the observed v0.29 maximum of USD 0.011926.
It is therefore less brittle than v0.29's USD 0.01 limit while remaining a
binding hard cap.

## Availability and transport policy

Each logical call permits one initial attempt plus at most four retries for only
the frozen transport classes: HTTP 429/500/502/503/504, transport errors, and
invalid or timed-out responses. Retry delays are `0.5/1/2/4` seconds. Every
physical attempt and recovered retry is counted; any unrecovered provider or
protocol failure still invalidates the study.

Provider stages are ordered:

1. authenticated catalog attestation;
2. three independent two-turn protocol repetitions per model (12 logical calls);
3. 36-episode canary covering all six fault families and all three seeds;
4. the immutable 2,592-episode formal manifest.

## Offline and provider commands

```bash
ARL_PYTHON="$(uv python find 3.12)"

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/build_v30_budget_calibration.py \
  --input artifacts/opencode_go_holdout_v29/full-summary.json \
  --output artifacts/opencode_go_replication_v30_design/budget-calibration.json

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/run_replication_v30_preflight.py \
  --traces-dir artifacts/opencode_go_replication_v30_preflight/traces \
  --output artifacts/opencode_go_replication_v30_preflight/full-summary.json
```

The provider commands accept the key only from the current process environment;
the CLI never accepts it as an argument:

```bash
env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/probe_opencode_go_v30.py \
  --preflight-summary artifacts/opencode_go_replication_v30_preflight/full-summary.json \
  --output artifacts/opencode_go_replication_v30_probe/probe.json \
  --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/run_opencode_go_v30.py --stage canary \
  --preflight-summary artifacts/opencode_go_replication_v30_preflight/full-summary.json \
  --protocol-probe artifacts/opencode_go_replication_v30_probe/probe.json \
  --workspace artifacts/opencode_go_replication_v30_canary/study \
  --summary artifacts/opencode_go_replication_v30_canary/full-summary.json \
  --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/run_opencode_go_v30.py --stage formal \
  --preflight-summary artifacts/opencode_go_replication_v30_preflight/full-summary.json \
  --protocol-probe artifacts/opencode_go_replication_v30_probe/probe.json \
  --canary-summary artifacts/opencode_go_replication_v30_canary/full-summary.json \
  --workspace artifacts/opencode_go_replication_v30/study \
  --summary artifacts/opencode_go_replication_v30/full-summary.json \
  --timeout-seconds 120
```

The formal command is allowed only after the canary summary validates against
the same source manifest. The runner is resumable and refuses to overwrite prior
summary, result, or trace paths. A checkpointed formal run may only continue by
repeating the identical command with `--resume`; it must not delete or rerun
selected cells.

After formal completion, create the public-safe aggregate before analysis:

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/compact_model_pilot_summary.py \
  --input artifacts/opencode_go_replication_v30/full-summary.json \
  --output artifacts/opencode_go_replication_v30/summary.json

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/build_opencode_go_v30_analysis.py \
  --input artifacts/opencode_go_replication_v30/full-summary.json \
  --output artifacts/opencode_go_replication_v30/analysis.json \
  --iterations 10000 --seed 20260810
```

The confirmatory builder fails closed unless both infrastructure validity and
all readiness gates pass. If infrastructure is valid but readiness fails, the
separate exploratory builder may write only an explicitly labeled
`exploratory-analysis.json`; infrastructure-invalid input produces no analysis.

## Confirmatory gates

Infrastructure validity requires the exact matrix and bindings, current source
and prerequisite hashes, matching reset/policy digests, digest-only traces,
bounded retry, pre-dispatch budget reservations, zero unrecovered
provider/protocol errors, and zero credential persistence.

Each model, seed, and runtime must independently reach at least 18/24 clean
`SafePass@3`; R2 clean noninferiority must be no worse than -0.05 per seed.
Only then may the fixed 10,000-iteration task-template cluster bootstrap with
seed `20260810` test the joint R2-minus-R1 fault-recovery hypothesis. A
completed matrix that misses infrastructure or readiness gates remains evidence,
but it cannot produce a confirmatory claim.

## Completed result and disposition

The frozen sequence completed on 2026-08-11:

- zero-model preflight: 432/432 episodes and 16/16 checks;
- authenticated repeated probe: 12/12 logical calls, exact model IDs, no retry;
- canary: 36/36 episodes, 104 logical calls, no retry, infrastructure valid;
- formal: 2,592/2,592 episodes, 10,047 logical calls, 10,052 network
  attempts, and 5 recovered transport retries;
- provider-reported usage: 10,065,145 input + 1,014,426 output =
  11,079,571 tokens; USD 0.8473333474 usage value, not an incremental charge.

Completion did not satisfy validity. Four Pro clean episodes for
`retail.cancel-duplicate-renewal` ended in `model_protocol_error` with
`unknown_tool_or_arguments`: two R0 episodes at seed `30113`, one R1 episode at
seed `30113`, and one R1 episode at seed `30229`. All corresponding provider
calls returned the requested Pro model with status `ok`; the failures were local
model/runtime protocol outcomes rather than unrecovered transport or parse
errors. The frozen check `zero_local_model_protocol_errors` is therefore false.
The evidence is retained without deleting or rerunning those cells.

Clean `SafePass@3` readiness by seed was:

| Model | Seed | R0 | R1 | R2 | Seed gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Flash | 30113 | 19/24 | 19/24 | 20/24 | pass |
| Flash | 30229 | 18/24 | 18/24 | 17/24 | fail |
| Flash | 30347 | 19/24 | 19/24 | 20/24 | pass |
| Pro | 30113 | 18/24 | 19/24 | 20/24 | pass |
| Pro | 30229 | 19/24 | 19/24 | 19/24 | pass |
| Pro | 30347 | 20/24 | 20/24 | 20/24 | pass |

Flash therefore also missed its all-seed clean-readiness gate. Both the
confirmatory and exploratory builders rejected the infrastructure-invalid input
with `RuntimeError: v0.30 analysis requires infrastructure-valid input`; neither
analysis file exists. No bootstrap confidence interval or inferential main
effect may be reported.

For diagnosis only, the compact summary retains matched fault-recovery
R2-minus-R1 point differences of `+0.7158521303` for Flash and
`+0.5537697253` for Pro, with clean differences of `+0.0138888889` for both.
These are descriptive values from invalid evidence, not a successful
replication claim.

Public-safe evidence is in
[`summary.json`](../artifacts/opencode_go_replication_v30/summary.json), the
artifact [README](../artifacts/opencode_go_replication_v30/README.md), and the
[validation log](../artifacts/opencode_go_replication_v30/validation.log).
The ignored full summary has SHA-256
`84caae7458ab1d71e83f8f9945c2c736f2523e1dc515790ac4516f6b7ba1cfcd`;
the frozen source manifest remains
`9874e9e459efb14192e3deea77b001c46ebd89f823f46c70009689173d758af2`.
