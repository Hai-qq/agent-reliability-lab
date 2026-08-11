# 24-Task DeepSeek Flash Single-Slot Study v0.24

v0.24 is a full-catalog model experiment for the original Agent Reliability Lab benchmark. It asks whether runtime-owned reliability mechanisms improve safe recovery from six deterministic fault families without reducing clean task capability. It does not reproduce a paper leaderboard and it does not masquerade as the frozen two-model confirmatory study.

## Frozen design

The executable matrix is:

\[
24\ \text{tasks}\times 2\ \text{conditions}\times 3\ \text{runtimes}
\times 1\ \text{model}\times 3\ \text{trials}=432\ \text{episodes}.
\]

Workspace, Retail and Travel each provide eight local synthetic tasks. Post-commit response loss, retryable invocation error, input schema drift, output schema drift, compatible state conflict and bounded compensation each cover four tasks. Clean and faulted pairs share the same reset state; the model sees the same task/tool contract across R0, R1 and R2, while only runtime-owned middleware changes.

The exact model binding is `deepseek-api/deepseek-v4-flash/DeepSeek-V4-Flash/non-thinking`, with `temperature=0`, `top_p=1`, 512 tokens per provider response and no provider sampling seed. Each episode is bounded by eight calls, 20,000 input tokens, 2,000 output tokens and an estimated cost of `$0.01`. Before every request, the runner reserves one maximum-sized response against the output-token budget; it therefore cannot accept a response that would make the episode cross its frozen hard limit.

`SafePass@3` requires all three repeated calls for a task/runtime/condition cell to be `SafeSuccess`. Recovery rate uses only tasks that pass clean `SafePass@3` for the same runtime. This avoids counting a faulted success on a task the model cannot solve cleanly.

## Result

| Runtime | Clean SafePass@3 | Fault SafePass@3 | Matched recovery |
|---|---:|---:|---:|
| R0 Raw | 18/24 | 8/24 | 8/18 = 0.444 |
| R1 Guarded | 18/24 | 5/24 | 5/18 = 0.278 |
| R2 Reliable | 18/24 | 17/24 | 17/18 = 0.944 |

The primary R2 minus R1 matched fault-recovery difference is `+0.6666666666666666`; the clean `SafePass@3` difference is `0.0`. A paired nonparametric task-cluster bootstrap keeps all R1/R2 clean/fault trial cells for a task together, resamples 24 task templates 10,000 times with seed `20260808`, and gives:

| Estimate | Observed | 95% percentile interval |
|---|---:|---:|
| R2−R1 fault recovery | 0.667 | [0.444, 0.882] |
| R2−R1 clean SafePass@3 | 0.000 | [0.000, 0.000] |
| R1 fault recovery | 0.278 | [0.077, 0.500] |
| R2 fault recovery | 0.944 | [0.812, 1.000] |

The bootstrap probability that the fault delta is above zero is `1.0`; this is a descriptive resampling proportion, not a p-value. Fault-family subgroups contain only four tasks and should be treated as diagnostics. The observed R2−R1 deltas are `+1.0` for input drift, output drift and post-commit loss, `+0.5` for bounded compensation, `+0.333` for compatible conflict and `0.0` for retryable invocation errors.

Six tasks fail clean `SafePass@3` under all runtimes: `retail.duplicate-order`, `retail.payment-order-split`, `travel.cancel-itinerary`, `travel.clarify-budget`, `workspace.partial-change-compensation` and `workspace.revised-authorization`. This is visible model/task difficulty, not silently removed data.

## Infrastructure and resource evidence

All 432 jobs finish, and all 14 frozen validity checks pass. The run records 1,684 provider calls, 1,614,032 input tokens, 156,207 output tokens, zero reasoning tokens, zero provider errors and zero local model-protocol errors. Estimated cost is `$0.06379268000000014`; p50/p95 latency is 1,185/1,899 ms. The maximum episode uses 8 calls, 10,637 input tokens, 1,335 output tokens and an estimated `$0.0005107368`, all inside the frozen limits.

R2 fault episodes record 9 retries, 12 confirmations, 9 input adaptations, 15 output normalizations, 12 conflict rebases and 27 compensation actions. R1 records 21 retries and none of the other reliability mechanisms; R0 records none. This provides typed process evidence in addition to final-state scores.

The runner saves no raw model request/response. All 432 journals pass the digest-only audit, and the exact credential audit finds no persisted match. Full result/state evidence remains locally ignored; public [summary](../artifacts/deepseek_flash_main_single_v24/summary.json), [analysis](../artifacts/deepseek_flash_main_single_v24/analysis.json) and [validation log](../artifacts/deepseek_flash_main_single_v24/validation.log) preserve content hashes and the execution/analysis source manifests.

## Reproduce

All output paths must not already exist. Supply the authorized credential only through the current process environment:

```bash
ARL_MAIN_SINGLE=/tmp/arl-main-single-v024

env DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:?set in current shell}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_main_single_slot.py \
    --workspace "$ARL_MAIN_SINGLE/study" \
    --summary "$ARL_MAIN_SINGLE/full-summary.json" \
    --timeout-seconds 60

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/compact_model_pilot_summary.py \
    --input "$ARL_MAIN_SINGLE/full-summary.json" \
    --output "$ARL_MAIN_SINGLE/summary.json"

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/build_main_single_slot_analysis.py \
    --input "$ARL_MAIN_SINGLE/full-summary.json" \
    --output "$ARL_MAIN_SINGLE/analysis.json" \
    --iterations 10000 \
    --seed 20260808
```

An interrupted run can use the same workspace with `--resume`; the study scheduler validates the frozen manifest and already committed result/trace hashes before executing only pending jobs. The public compact summary is 87,044 bytes with SHA-256 `9931a76f94445ed6645d332ede4e592433347734d3bc5b3d0c6edf9a942a2e12`. Full hashes and source bindings are listed in the artifact validation log.

## Subsequent dual-mode amendment

The 24-task fixtures, deterministic mechanism ablation, task-cluster analysis and non-thinking slot are complete. The historical same-model thinking-high amendment was implemented but not run to completion and is no longer the active main-study path. v0.27 later completed a true two-model OpenCode Go matrix but failed its validity/readiness gates. The current prospective study is the fresh Flash + Qwen v0.28 contract, which does not reuse observed v0.27 episodes; see [v0.27](./opencode-go-main-v27.md) and [v0.28](./opencode-go-main-v28.md).
