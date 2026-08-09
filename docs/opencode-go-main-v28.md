# OpenCode Go Flash + Qwen Main v0.28

v0.28 is a fresh 864-episode ARL main study using OpenCode Go
`deepseek-v4-flash` and `qwen3.7-plus`. It does not reuse the observed v0.27
Flash episodes. The model choice, transport behavior, budgets, and stop rules
were frozen before any Qwen benchmark outcome was observed.

## Frozen design

The exact matrix is:

\[
24\ \text{tasks} \times 2\ \text{models} \times 3\ \text{runtimes}
\times 2\ \text{conditions} \times 3\ \text{trials} = 864\ \text{episodes}.
\]

Bindings:

- `opencode-go/deepseek-v4-flash/listing-2026-08-09/non-thinking`
- `opencode-go/qwen3.7-plus/listing-2026-08-09/default-inference`

The shared per-episode logical budget is 8 model calls, 20,000 input tokens,
8,192 output tokens, a maximum 1,024 tokens per response, and USD 0.01 of
usage-value estimate. A call is refused before dispatch if reserving the maximum
next response would exceed a hard budget.

## Transport policy

Each logical model call may make at most three network attempts: the initial
attempt plus two retries after 0.25 and 0.5 seconds. Retryable classes are HTTP
429/500/502/503/504, transport errors, and invalid or timed-out responses.
Logical model calls and physical network attempts are counted separately;
recovered retries remain visible in the audit. Any unrecovered provider or
protocol error invalidates the study.

If the Qwen structured-tool protocol probe fails, the runner stops. Qwen is not
silently swapped for another model; a further replacement would require a new
amendment before observing that model's benchmark outcome.

## Qualification and interpretation

The 12-episode canary covers one representative of every fault family for each
model at R2 under fault. It must pass the infrastructure gate before the formal
matrix starts. Confirmatory analysis additionally requires at least 75% clean
`SafePass@3` for every Runtime within each model and the frozen clean
noninferiority gate.

Both model slots use the same OpenCode Go gateway. A valid result can support
cross-model consistency within this gateway, not cross-provider generalization.
Catalog dates identify observed listings, not immutable serving weights, and
usage-value estimates are not incremental subscription charges.

## Completed result

The protocol probe passed with two digest-only calls. The 12-episode canary
then passed its infrastructure gate, and the formal runner completed all
864/864 episodes from a fresh workspace with Python 3.12.12.

| Measure | Flash | Qwen |
|---|---:|---:|
| Clean `SafePass@3`, R0 / R1 / R2 | 18 / 18 / 18 | 17 / 18 / 17 |
| Matched fault recovery, R1 | 5 / 18 | 4 / 18 |
| Matched fault recovery, R2 | 17 / 18 | 15 / 17 |
| R2 − R1 recovery delta | +0.667 | +0.660 |
| Exploratory 95% task-bootstrap CI | [0.438, 0.882] | [0.429, 0.875] |

All 18 infrastructure checks passed. The run recorded 3,541 logical model
calls, 3,542 network attempts, 3,721,076 tokens, and zero unrecovered provider
or protocol errors. One Flash call received HTTP 503 and recovered through the
frozen retry policy. The usage-value estimate is USD 1.2767371528, not an
incremental subscription charge.

The preregistered confirmatory readiness gate failed because Qwen reached only
17/24 clean `SafePass@3` tasks at R0 and R2, below the required 18/24 in every
runtime. The confirmatory builder therefore refused the input and no
`analysis.json` exists. A separate `exploratory-analysis.json` records 10,000
paired task-cluster bootstrap samples and explicitly sets
`confirmatory_claim_allowed=false` and `primary_hypothesis_supported=false`.
At R2, Qwen failed `SafePass@3` on the same six clean tasks that Flash failed,
plus `travel.split-booking-compensation`; it was exactly one task below the
readiness threshold, but that frozen threshold is not waived after observing
the result.

## Commands

The secret must be supplied only through `OPENCODE_GO_API_KEY`; output paths
must not already exist.

```bash
ARL_PYTHON="$(uv python find 3.12)"

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in the current shell}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/probe_opencode_go_v28.py \
    --output artifacts/opencode_go_flash_qwen_v28_probe/probe.json \
    --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in the current shell}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v28.py \
    --stage canary \
    --protocol-probe artifacts/opencode_go_flash_qwen_v28_probe/probe.json \
    --workspace artifacts/opencode_go_flash_qwen_v28_canary/study \
    --summary artifacts/opencode_go_flash_qwen_v28_canary/full-summary.json \
    --timeout-seconds 120
```

After a valid canary, start the formal matrix with both prerequisite artifacts:

```bash
env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in the current shell}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v28.py \
    --stage formal \
    --protocol-probe artifacts/opencode_go_flash_qwen_v28_probe/probe.json \
    --canary-summary artifacts/opencode_go_flash_qwen_v28_canary/full-summary.json \
    --workspace artifacts/opencode_go_flash_qwen_v28/study \
    --summary artifacts/opencode_go_flash_qwen_v28/full-summary.json \
    --timeout-seconds 120
```

The formal runner verifies that the protocol probe and canary passed and that
their source hashes match the current runner before creating the workspace. The
confirmatory analysis builder is allowed to run only after both infrastructure
validity and model-quality readiness are true. On this completed run, the
following command fails closed as intended:

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/build_opencode_go_v28_analysis.py \
    --input artifacts/opencode_go_flash_qwen_v28/full-summary.json \
    --output artifacts/opencode_go_flash_qwen_v28/analysis.json \
    --iterations 10000 --seed 20260809
```

Because the infrastructure is valid but readiness is false, the separately
labelled exploratory command is:

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/build_opencode_go_v28_exploratory_analysis.py \
    --input artifacts/opencode_go_flash_qwen_v28/full-summary.json \
    --output artifacts/opencode_go_flash_qwen_v28/exploratory-analysis.json \
    --iterations 10000 --seed 20260809
```

The protocol probe performs one fixed synthetic tool call followed by one tool
feedback turn. Its artifact stores only model binding, usage, typed outcomes,
source/response digests, and sanitized transport attempts—not message or tool
content.

Public-safe evidence is in
[`summary.json`](../artifacts/opencode_go_flash_qwen_v28/summary.json),
[`exploratory-analysis.json`](../artifacts/opencode_go_flash_qwen_v28/exploratory-analysis.json),
and [`validation.log`](../artifacts/opencode_go_flash_qwen_v28/validation.log).
The 9.2 MB full summary, study state, result records, and traces remain local and
ignored; the compact summary retains their hashes and audit counts.
