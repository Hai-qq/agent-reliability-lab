# ARL Pilot Preflight v0.17

v0.17 把 v0.16 的“主实验合同”推进为一个可运行的 **8-task、6-fault、48-episode 零模型 pilot preflight**。它已经补齐所选任务的合成 SQLite 环境、可见任务合同、oracle policy、fault、状态 evaluator、R0/R1/R2 统一 runtime 和 provider-neutral model tool definitions；它仍不是 144-episode 模型 pilot。

> 这是 v0.17 的冻结历史记录。后续 v0.20 已补齐 24 个 runnable fixture，v0.21 已完成机制消融，v0.24 已完成 DeepSeek Flash 432-episode non-thinking study。历史 v0.25 thinking-high 路径没有完成；v0.27 双模型 matrix 完整运行但 validity/readiness 失败，当前前瞻性路径是全新 Flash + Qwen v0.28。

## 与 v0.16 的版本边界

v0.16 冻结了 24-task blueprint，并如实记录 6 个 `existing_core` 与 18 个 `planned`。v0.17 不回写或篡改该历史 artifact，而是在独立 `arl_pilot` 包中选择 8 个模板：迁移 5 个 existing blueprint，并为 3 个原 planned blueprint 提供第一版可运行 fixture。完成本增量后，24 个主实验模板中仍有 16 个没有 v0.17 实现。

| Domain | Template | 主故障族 | v0.16 来源状态 | v0.17 状态 |
|---|---|---|---|---|
| Workspace | schedule meeting | post-commit response loss | existing core | runnable |
| Workspace | reschedule meeting | post-commit response loss | existing core | runnable |
| Workspace | clarify attendees | output schema drift | planned | runnable fixture |
| Retail | discounted order | post-commit response loss | existing core | runnable |
| Retail | eligible exchange | retryable invocation error | planned | runnable fixture |
| Retail | shipping revision | compatible state conflict | planned | runnable fixture |
| Travel | book itinerary | input schema drift | existing core | runnable |
| Travel | bundle recovery | bounded compensation | existing core | runnable |

## 公平的 Agent/Runtime 边界

三档 Runtime 接收同一个 deterministic reactive oracle policy。Agent 只能发出 canonical 语义工具动作，不能设置 state version 或 idempotency key；输出 schema 任务还要求 Agent 只有收到 canonical `attendee_ids` 后才能继续，避免固定 oracle plan 绕过异常返回。

| Runtime | v0.17 行为 |
|---|---|
| R0 Raw | 原样派发，不重试、不校验、不拥有可靠性机制 |
| R1 Guarded | state-version fencing、canonical result validation、一次有界 retry |
| R2 Reliable | R1 + 确定性幂等、提交后公共状态确认、精确 schema adapter/normalizer、public-read guarded rebase、3-step bounded compensation |

所有 faulted pair 与 clean 共享同一初始 state hash；环境只改变一个注册故障条件。Runtime 只能看到类型化 `StepResult`、public descriptor 与 public read 结果，不能读取 fault ID、oracle final state 或 evaluator ground truth。

## 48-episode 实测结果

固定公式为：

\[
8\ \text{tasks}\times1\ \text{environment seed}\times2\ \text{conditions}\times3\ \text{runtimes}=48\ \text{episodes}.
\]

| Runtime | Clean SafeSuccess | Fault SafeSuccess | RecoveryRate |
|---|---:|---:|---:|
| R0 Raw | 8/8 | 0/8 | 0.000 |
| R1 Guarded | 8/8 | 1/8 | 0.125 |
| R2 Reliable | 8/8 | 8/8 | 1.000 |

在这组 scripted preflight 中，R2 相对 R1 的 fault RecoveryRate 差值为 `0.875`。它是机制门禁的描述性结果，不是模型效应，也没有抽样置信区间。

六类机制均被真实触发并写入 digest-only trace：3 次 post-commit confirmation、2 次 invocation retry（R1/R2 各 1）、1 次输入 schema adaptation、1 次输出 schema normalization、1 次 compatible conflict rebase 与 3 个 compensation action。

## Validity 与模型就绪边界

48 个 episode 全部通过以下门禁：

- exact matrix、同 policy digest 与 clean/fault reset hash parity；
- 每个 faulted episode 只出现一个注册 fault ID；
- clean 24/24 SafeSuccess，R2 fault 8/8 SafeSuccess；
- 8/8 do-nothing 被拒；
- 逐项破坏 required final-state field 均被 evaluator 检出；
- R0 的 retry/confirm/schema/rebase/compensation 计数全部为 0；
- 48 条 trace 不包含原始 arguments、visible task 或固定合成实体值；
- model/network calls 均为 0。

每个任务在 v0.17 中提供公开 `user_request`、合成 context 与 structured tool definitions。集成测试使用内存 fake backend 验证 `ModelAgent → PilotRuntime → evaluator` 接口闭环，并修正了零成本本地 backend 在 `max_monetary_cost=0` 下被错误提前阻止的问题。该冻结版本没有实际 DeepSeek、Ollama 或 API backend，`default_contract().assert_ready("pilot")` 会在精确模型 slot 未绑定时 fail closed。

## 复现

输出路径必须尚不存在：

```bash
ARL_PREFLIGHT=/tmp/arl-pilot-preflight-v017

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_pilot_preflight.py \
  --output "$ARL_PREFLIGHT/summary.json" \
  --traces-dir "$ARL_PREFLIGHT/traces"
```

正式与独立 repeat 的 summary 及 48/48 traces 均逐字节一致：

- summary SHA-256：`3976f4ab9cbce28a430d7834cd712a0fe434bfd61c73d8a3af6b2cdeb2822fd4`；
- source manifest SHA-256：`47c68e987ff5cd1ad5d13ff203e5965d0be503f143d3ed735b30d2eccd5e707a`；
- trace manifest SHA-256：`b15c2c4c6a9ec0a5acb0ff2d78add0956e59ccf2ab24aad3462a2bab7f8adf92`；
- pilot catalog SHA-256：`3019dbeb2d1bf7950cf1b4ee8da1d10655ff9e076bcc6d00c7b0080807733ad9`。

证据入口见 [artifact 说明](../artifacts/pilot_preflight_v17/README.md)、[summary.json](../artifacts/pilot_preflight_v17/summary.json) 与 [validation.log](../artifacts/pilot_preflight_v17/validation.log)。v0.17 验收时在 Python 3.11.15 与 3.12.12 上均通过 200 tests，Ruff check 与 format check 全部通过。

## 尚未完成

- 24-task 主目录仍有 16 个模板没有 v0.17 环境、fault、oracle 与 evaluator；
- 8 个 fixture 只有一个固定环境 seed，尚需人工 task-card 审查与参数化扩展；
- 没有真实模型 backend、模型 prompt trace、token/cost 实测或三个 sampling trial；
- 144 model pilot、864 confirmatory main、10,000 次 task-cluster bootstrap 和机制消融尚未运行；
- 因此当前结果不能证明 DeepSeek、Ollama 或任何 API 模型的能力。

上述“尚未完成”是 v0.17 的版本边界；8-task 模型 pilot 见 [DeepSeek Flash Model Pilot v0.19](./model-pilot-v19.md)，最新有效模型结果见 [Single-Slot Study v0.24](./main-single-slot-v24.md)，当前前瞻性双模型合同见 [v0.28](./opencode-go-main-v28.md)。
