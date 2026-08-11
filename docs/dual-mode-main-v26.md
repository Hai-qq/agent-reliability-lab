# DeepSeek V4 Flash Dual-Mode Main Amendment

> 这是未完成的历史 amendment，不是当前主实验路径。thinking-high 正式矩阵没有启动；后续 v0.27 改为真正的双模型 OpenCode Go matrix，但完整运行未通过 validity/readiness。当前前瞻性路径为全新 Flash + Qwen v0.28，见 [v0.28 合同](./opencode-go-main-v28.md)。

该增量把原先“一个 API 模型 + 一个本地开源模型”的 864-episode 计划，透明修订为同一个 `DeepSeek V4 Flash` 的两种推理配置：

| 配置 | 精确 revision | Thinking | Reasoning effort | 已有状态 |
|---|---|---|---|---|
| `flash_non_thinking` | `DeepSeek-V4-Flash/non-thinking` | disabled | n/a | v0.24 的 432 轮有效结果已冻结 |
| `flash_thinking_high` | `DeepSeek-V4-Flash/thinking-high` | enabled | high | runner、合同和分析已实现；未继续执行，已由后续双模型路径取代 |

两者的 provider 与 model ID 完全相同。因此本增量只能检验 **同一模型两种推理模式下 Runtime 效应是否一致**，不能写成跨模型、跨 provider 或独立权重泛化。修订发生在 v0.24 非思考结果已经观察之后，完整 864 结果也不能冒充预先注册的异构双模型 confirmatory study；机器合同将 `main.confirmatory` 明确设为 `false`。

## 冻结矩阵与主指标

完整修订矩阵仍保持原 v0.16 的 episode 算术：

\[
24\ \text{tasks}\times 1\ \text{seed}\times 2\ \text{conditions}
\times 3\ \text{runtimes}\times 2\ \text{inference modes}
\times 3\ \text{trials}=864\ \text{episodes}.
\]

主指标仍为每个配置内 `R2 Reliable − R1 Guarded` 的 matched fault `SafePass@3` recovery-rate 差值；clean `SafePass@3` 的非劣界为 `−0.05`。分析先分别对两个配置做 10,000 次 task-cluster bootstrap，再做联合 task bootstrap：抽到一个 task 时，两种模式以及该 task 的全部 R1/R2 clean/fault trial cell 必须一起保留。

只有以下条件同时成立，才允许写“修订主假设得到支持”：

- 两个 432-episode 输入的基础设施 validity 都通过；
- 两个配置在每档 Runtime 的 clean `SafePass@3` 均不低于 75%；
- 两个配置的 R2 clean 差值均不低于 `−0.05`；
- 两个配置的 fault-recovery 差值 bootstrap 95% percentile interval 下界均大于 0。

## Provider 与预算合同

`arl_dualmode` 不修改 v0.24 已被 source manifest 冻结的后端和 runner，而是在独立包中加入：

- `DeepSeekFlashThinkingBackend`：发送 `thinking={"type":"enabled"}` 与 `reasoning_effort="high"`；
- 六类故障各一个任务的 6-job fail-closed canary；
- 432-job thinking-high manifest、原子 checkpoint 和 resume；
- 864-episode same-model dual-mode 聚合、source-manifest 复核和联合 bootstrap。

非思考 v0.24 继续使用每次最多 512 output tokens、每 episode 最多 2,000 output tokens。Thinking-high 为容纳计入 completion usage 的 reasoning tokens，固定为每次最多 1,024、每 episode 最多 8,192 output tokens；两者均最多 8 次调用、20,000 input tokens 和估算 `$0.01`。每次调用前都预留一次最大 response cap。由于输出预算不同，跨模式 token、成本或绝对成功率只能作描述性比较；Runtime 的主要效应必须在每个配置内部计算。

## 当前实测状态

截至 2026-08-09：

- v0.24 非思考 432 轮仍通过全部 14 项 validity；其 30-file source manifest 与当前 checkout 重新核验一致；
- 双模式代码在当时的 Python 3.11.15 与 3.12.12 门禁中各通过 238 tests，Ruff 0.15.17 check/format check 通过；
- 第一次 6-job thinking-high canary 因剪贴板不是 API key 而得到 6 次 `provider_http_401`，0 accepted calls、0 tokens、`$0`；credential 与 digest-only 门禁通过，但 overall validity 为 false；
- 432-episode thinking-high 正式矩阵与 864 聚合均未启动。

失败 canary 只作为本地忽略的基础设施诊断保留，不能进入模型或 Runtime 结论。新凭据必须写入一个全新的、不可覆盖的 canary 路径。

## 运行顺序

Key 只能通过当前进程环境提供；下列路径必须不存在：

```bash
ARL_DUAL=/tmp/arl-deepseek-flash-dual-mode

env DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:?set in current shell}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_flash_thinking_slot.py \
    --stage canary \
    --workspace "$ARL_DUAL/canary/study" \
    --summary "$ARL_DUAL/canary/full-summary.json" \
    --timeout-seconds 120

env DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:?set in current shell}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_flash_thinking_slot.py \
    --stage formal \
    --workspace "$ARL_DUAL/thinking/study" \
    --summary "$ARL_DUAL/thinking/full-summary.json" \
    --timeout-seconds 120

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/compact_model_pilot_summary.py \
    --input "$ARL_DUAL/thinking/full-summary.json" \
    --output "$ARL_DUAL/thinking/summary.json"

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/build_flash_dual_mode_main.py \
    --non-thinking artifacts/deepseek_flash_main_single_v24/full-summary.json \
    --thinking-high "$ARL_DUAL/thinking/full-summary.json" \
    --full-output "$ARL_DUAL/combined/full-summary.json" \
    --public-output "$ARL_DUAL/combined/summary.json" \
    --iterations 10000 --seed 20260809
```

正式 runner 支持 `--resume`；scheduler 会先核验 manifest、state 以及已完成 result/trace 哈希，只运行剩余 job。任何 validity 或 clean-quality gate 失败都必须保留原结果并停止主结论升级。
