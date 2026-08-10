# Prospective Holdout v0.29

v0.29 是在观察到 v0.28 readiness 失败后设计的前瞻性独立复核。它不改写
v0.28、不降低 75% clean 门槛，也不选择性重跑失败 cell。它能提供新的
holdout 证据，但不能伪装成完全未见结果的首次预注册。

## 冻结设计

- 24 个新 task ID 和新 user request，与 v0.28 的 24 个 ID 完全不重叠；
- Workspace、Retail、Travel 各 8 个任务，六类故障各 4 个任务；
- 三个数据 seed：`29101`、`29211`、`29307`；每个 seed 使用不同 context、
  record identity 与状态命名空间；
- 继续使用同一组公开 tool schema 和六种 runtime mechanism archetype，避免把
  接口变化误当成 runtime 增益；
- 模型仍精确绑定 OpenCode Go `deepseek-v4-flash` non-thinking 与
  `qwen3.7-plus` default inference；两者共享 gateway，不支持跨 provider 结论；
- formal 算式为 `24 × 3 × 2 × 3 × 3 × 2 = 2,592` episodes；
- 每个 model × seed × runtime 必须单独达到至少 `18/24` clean
  `SafePass@3`，R2 相对 R1 的 clean noninferiority 也逐 seed 检查；
- bootstrap 以 24 个 task template 为 cluster，并将两个模型、三个 seed、
  R1/R2 clean/fault 与全部 trials 留在 cluster 内。

完整合同 SHA-256 为
`55c9ec71ea880f837dd736def8ceccdc3da2f003d96fa6f988692ea3dc465883`，
transition SHA-256 为
`7672dea16162636060eefae7730874d59774f355e589807a317b2b34f387721f`，
holdout catalog SHA-256 为
`c8f0235b042b87b3c9445823f1b4b3f80dbfefe3ef93ef1297dce93d32ed96bc`。

## 当前完成状态

最终证据链已全部执行：

- 零模型 preflight：432/432 episodes、16/16 checks、216/216 clean
  `SafeSuccess` 与 72/72 R2 fault `SafeSuccess`，零模型/网络调用；
- 双模型 protocol probe：4 次逻辑调用、4 次网络尝试、0 retry，两个精确 binding
  均通过两轮 structured-tool protocol；
- canary：36/36 episodes，infrastructure validity 与 formal readiness 均为 true；
- formal：2,592/2,592 episodes，经一次 checkpoint resume 完成，但最终
  infrastructure validity 为 **false**。

正式运行失败的三个预注册检查是
`zero_unrecovered_provider_transport_or_parse_errors`、
`usage_totals_match_provider_records` 与
`per_episode_model_budgets_respected`。根因是两次 Qwen HTTP 503 在完整 retry
policy 后仍未恢复，以及四个 Qwen episode 的 usage-value estimate 超过冻结的
USD 0.01 上限。失败记录和超限 episode 均原样保留，没有选择性重跑或删除。

因此 confirmatory 与 exploratory builder 都以
`v0.29 analysis requires infrastructure-valid input` 非零退出，且没有生成
`analysis.json` 或 `exploratory-analysis.json`。正式 summary 内的 point estimate
只能作为描述性诊断，不能写成推断性主结论。

有效证据链共同使用 51-file source manifest SHA-256
`d2b413603354baf07e1c08932b0cb12070fafe77f609f232016636e095ffbf20`。
公开入口为 [preflight summary](../artifacts/opencode_go_holdout_v29_preflight/summary.json)、
[probe](../artifacts/opencode_go_holdout_v29_probe/probe.json) 与
[formal compact summary](../artifacts/opencode_go_holdout_v29/summary.json)；完整命令、
失败门禁、恢复审计和哈希见
[validation.log](../artifacts/opencode_go_holdout_v29/validation.log)。

## 描述性结果（非推断）

| 模型 | Seed | R0 / R1 / R2 clean `SafePass@3` | 逐 seed readiness |
|---|---:|---:|---|
| Flash | 29101 | 20/24 · 20/24 · 20/24 | 通过 |
| Flash | 29211 | 19/24 · 19/24 · 19/24 | 通过 |
| Flash | 29307 | 19/24 · 19/24 · 19/24 | 通过 |
| Qwen | 29101 | 18/24 · 18/24 · 16/24 | 失败 |
| Qwen | 29211 | 17/24 · 15/24 · 16/24 | 失败 |
| Qwen | 29307 | 16/24 · 18/24 · 18/24 | 失败 |

Flash 与 Qwen 的 R2−R1 matched fault-recovery point estimate 分别为
`+0.6897` 与 `+0.6847`；clean point estimate 分别为 `0.0000` 与 `-0.0139`。
由于 infrastructure validity 和 Qwen readiness 都失败，这些数值没有 bootstrap
区间，也不构成成功 replication。

## 执行顺序

```bash
ARL_PYTHON="$(uv python find 3.12)"

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_holdout_v29_preflight.py \
  --output artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --traces-dir artifacts/opencode_go_holdout_v29_preflight/traces

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/probe_opencode_go_v29.py \
  --preflight-summary artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --output artifacts/opencode_go_holdout_v29_probe/probe.json \
  --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v29.py --stage canary \
  --preflight-summary artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --protocol-probe artifacts/opencode_go_holdout_v29_probe/probe.json \
  --workspace artifacts/opencode_go_holdout_v29_canary/study \
  --summary artifacts/opencode_go_holdout_v29_canary/full-summary.json \
  --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v29.py --stage formal \
  --preflight-summary artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --protocol-probe artifacts/opencode_go_holdout_v29_probe/probe.json \
  --canary-summary artifacts/opencode_go_holdout_v29_canary/full-summary.json \
  --workspace artifacts/opencode_go_holdout_v29/study \
  --summary artifacts/opencode_go_holdout_v29/full-summary.json \
  --timeout-seconds 120
```

只有 canary 的 infrastructure validity 为 true 后，才允许用相同 source manifest
启动 formal。Formal 支持在同一 workspace、同一参数后追加 `--resume`；scheduler
会核对 frozen manifest、既有 result/trace 和 source hash，任何漂移都会拒绝继续。
本次在 2,322 个结果后发生进程级断连，恢复前后既有结果集合 digest 都是
`547a240c47baa7a83d70f168be1b7c173dc49b829e99e3effe2ddefa5eb76a8c`，
原结果未变化。

## 结论边界

- v0.29 的结果无论成功或失败，都不会删除或覆盖 v0.28；
- infrastructure 或逐 seed clean readiness 失败时，所有 analysis builder 必须拒绝输出；
- v0.29 已失败，不能通过选择性重跑失败 cell、修改预算或降低门槛改写其处置；
- 后续只能在调用模型前冻结新的独立 replication，并将 v0.29 继续保留为失败证据；
- 同一 gateway 下的两个 model ID 不能证明跨 provider 泛化；
- provider 不提供统一 sampling seed 或不可变 serving-weight hash，因此模型输出不
  具备逐字节确定性。
