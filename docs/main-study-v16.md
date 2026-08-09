# ARL Main Study Contract v0.16

ARL v0.16 将此前分散的 deterministic runtime 结果收敛成一份可证伪、可机器校验的主实验合同。当前交付的是**主实验基础设施与无模型 smoke gate**，不是模型 pilot 或 864-episode 主实验结果。

> 这是 v0.16 的冻结历史记录。后续 v0.20 已补齐 24 个 runnable task，v0.21 已完成机制消融，v0.24 已完成 DeepSeek Flash 432-episode non-thinking study 与 task-cluster bootstrap。历史 v0.25 thinking-high 路径没有完成；v0.27 双模型 matrix 完整运行但 validity/readiness 失败，当前前瞻性路径是全新 Flash + Qwen v0.28。

## 原创研究问题

主假设固定为：在相同任务、环境 seed、Agent policy 和 sampling trial 下，R2 Reliable 相比 R1 Guarded 提高 recoverable-fault `SafePass^3`，同时 clean `SafeSuccess` 的下降不超过 5 个百分点，且不增加严重副作用。

五类外部设计影响被转化为 ARL 自身的分层合同：Study/trace、状态差分、milestone/minefield、utility/safety 分离和 validity-first CI。公开结果只来自本项目独立编写的合成任务和代码。

## 冻结矩阵

`arl_mainstudy.contract` 是 episode 算术、模型门禁和统计协议的机器可读真相源：

| 阶段 | 固定公式 | Episodes | 模型状态 |
|---|---:|---:|---|
| Scripted smoke | 2 tasks × 1 env seed × 2 conditions × 3 runtimes × 1 policy × 1 trial | 12 | 不调用模型 |
| Pilot | 8 × 1 × 2 × 3 × 1 × 3 | 144 | 需要 1 个精确绑定 |
| Main | 24 × 1 × 2 × 3 × 2 × 3 | 864 | 需要 2 个精确绑定 |
| Full three-seed | 24 × 3 × 2 × 3 × 2 × 3 | 2592 | 可选 robustness 扩展 |

精确模型绑定必须同时包含 provider、完整 model ID 和 revision。v0.16 冻结时两个 slot 均保持 unbound；任何 pilot/main 请求都会 fail closed。该版本没有 DeepSeek、Ollama 或其他 provider 的网络实现，也不读取 API key。

## 24-task blueprint

目录固定为 Workspace、Retail、Travel 各 8 个模板，六类 recoverable fault 各 4 个模板：

- post-commit response loss；
- retryable invocation error；
- input schema drift；
- output schema drift；
- compatible state conflict；
- bounded compensation。

目录明确区分 **6 个 existing core task** 与 **18 个 planned task**。planned 记录只冻结任务 ID、操作模式和主故障族，不包含空实现，也不计为可运行 benchmark。当前只有 Workspace schedule 和 Retail discounted order 两个 migration adapter 进入 smoke。

不兼容冲突、授权撤回和未来安全情景必须进入独立 CorrectAbort/Safety suite，不能混入 recoverable-fault RecoveryRate。

## 统一 Policy/Runtime 边界

`ScriptedAgent` 只产生语义工具动作，禁止设置 `idempotency_key` 或 `expected_state_version`。统一 `ActionRuntime` 才能按实验条件添加能力：

| Runtime | Runtime-owned behavior |
|---|---|
| R0 Raw | 不重试、不做结果合同校验、不附加可靠性元数据 |
| R1 Guarded | 附加 state version、验证结果合同、一次有界重试 |
| R2 Reliable | R1 + 确定性幂等键 + ambiguous commit 状态确认 |

因此三档 Runtime 获得完全相同的 Agent 语义计划；差异只来自被测 middleware。v0.16 的 `ModelAgent` 已提供 provider-neutral structured-action、精确绑定、工具白名单和本地预算合同，但该版本没有实际 provider backend。测试只使用内存 fake backend，零网络调用。

## Scripted smoke 实测

固定 Workspace schedule 与 Retail discounted order，分别运行 clean 和提交后响应丢失：

| Runtime | Clean SafeSuccess | Fault SafeSuccess | Retry | Confirmation |
|---|---:|---:|---:|---:|
| R0 Raw | 2/2 | 0/2 | 0 | 0 |
| R1 Guarded | 2/2 | 0/2 | 2 | 0 |
| R2 Reliable | 2/2 | 2/2 | 0 | 2 |

12 个 episode 的初始状态、registered fault isolation、相同 policy digest、结果合同和 digest-only trace 门禁全部通过；模型调用与外部网络调用均为 0。这个结果只验证 main-study harness 能公平施加 Runtime 差异，不支持模型能力、`SafePass^3` 或统计显著性结论。

正式与独立 repeat 的 `summary.json` 及 12/12 traces 均逐字节一致。正式 summary SHA-256 为 `9066b70a2ca8b3f37ba05fb5e99fd2c4274418403851c3df09d356225701cf4d`，source manifest SHA-256 为 `8a8b7e02c61c8981049fc7d147bc887eeec2959647d6f7ff2a417c55b3081598`，trace manifest SHA-256 为 `c8d9fac033ffbd6ac323b5eef76f2abf228ff5c7f33e8807b15ffab67d258bbf`。证据入口见 [artifact 说明](../artifacts/main_study_contract_v16/README.md)、[summary.json](../artifacts/main_study_contract_v16/summary.json) 与 [validation.log](../artifacts/main_study_contract_v16/validation.log)。

## 运行

目标路径必须尚不存在：

```bash
ARL_SMOKE=/tmp/arl-main-study-v016

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_main_study_smoke.py \
  --output "$ARL_SMOKE/summary.json" \
  --traces-dir "$ARL_SMOKE/traces"
```

查询关键门禁：

```bash
jq '.contract.stages, .aggregate.by_runtime, .validity' \
  "$ARL_SMOKE/summary.json"
```

v0.16 源码在 Python 3.11.15 与 3.12.12 上均通过 15 个定向测试；v0.17 验收时的全仓门禁为 200 tests。Ruff check 与 format check 全部通过，历史增量仍保留其各自冻结时的测试计数。

## v0.16 冻结时尚未完成

- v0.16 冻结时 18 个 planned task 尚无统一环境、oracle、fault 或 evaluator；后续 v0.17 已补 3 个 fixture，24-task 目录仍有 16 个模板未进入 v0.17 runner；
- v0.16 smoke 只有 post-commit response loss；后续 v0.17 preflight 才将六类故障全部接入统一 runner；
- v0.16 的 provider-neutral `ModelAgent` 没有 DeepSeek/Ollama backend，也没有模型 prompt/trace；
- 144 pilot、864 main、bootstrap CI 和定向机制消融均未运行；
- v0.16 不能取代 v0.1–v0.15 的冻结 artifact，也不改变其历史结论。

后续实现与 48-episode 证据见 [Pilot Preflight v0.17](./pilot-preflight-v17.md)。

后续 8-task 模型 pilot 见 [DeepSeek Flash Model Pilot v0.19](./model-pilot-v19.md)；完整 24-task 非思考实测、token/cost 与 bootstrap 见 [Single-Slot Study v0.24](./main-single-slot-v24.md)；完整但无效的首个双模型结果见 [v0.27](./opencode-go-main-v27.md)，当前前瞻性合同见 [v0.28](./opencode-go-main-v28.md)。
