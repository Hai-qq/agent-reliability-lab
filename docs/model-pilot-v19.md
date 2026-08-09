# DeepSeek Flash Model Pilot v0.19

v0.19 是 ARL 原创 reliability benchmark 的首个有效模型 pilot，不是论文排行榜复刻。它把同一个 DeepSeek-V4-Flash Agent 放入 8 个本地合成任务、clean/recoverable-fault 两种条件和 R0/R1/R2 三档 Runtime，用状态 evaluator 检查可靠性 middleware 是否提高安全恢复，同时保持 clean 能力。

> 这是 v0.19 的冻结历史记录。后续 v0.20 已补齐全部 24 个 fixture，v0.21 已完成机制消融，v0.24 已运行 432-episode DeepSeek Flash non-thinking study 与配对 task-cluster bootstrap。历史 v0.25 thinking-high 路径没有完成；v0.27 双模型 matrix 完整运行但 validity/readiness 失败，当前前瞻性路径是全新 Flash + Qwen v0.28。

## 冻结合同

固定矩阵为：

\[
8\ \text{tasks}\times1\ \text{environment seed}\times2\ \text{conditions}
\times3\ \text{runtimes}\times1\ \text{model}\times3\ \text{trials}
=144\ \text{episodes}.
\]

模型精确绑定为 `deepseek-api/deepseek-v4-flash/DeepSeek-V4-Flash/non-thinking`。Sampling 固定 `temperature=0`、`top_p=1`、`max_output_tokens=512`；DeepSeek API 没有 sampling seed，所以 3 个 trial 是重复调用，不是随机流的逐字节复现。每个 episode 的硬预算为 8 calls、20,000 input tokens、2,000 output tokens 和 `$0.01`。

`SafePass@3` 要求同一个 task/runtime/condition 的 3 个 trial 全部 `SafeSuccess`。Pilot 的预注册模型质量门禁要求：

- infrastructure validity 全部通过；
- 每个 Runtime 的 clean `SafePass@3 ≥ 75%`；
- R2 相对 R1 的 clean delta 不低于 `-0.05`。

该 readiness gate 不要求先看到正向 R2 fault effect，避免按结果修改门槛。

## v0.18：失败的预检证据

v0.18 用完全相同矩阵和 256-token response cap 跑完 144/144 episodes。在 `workspace.clarify-attendees / R1 / recoverable_fault / trial 2` 中，provider 返回 `finish_reason=length`、256 output tokens，tool JSON 被截断并触发 1 次 local `model_protocol_error`。因此以下两项为 false：

- `zero_provider_transport_or_parse_errors`；
- `zero_local_model_protocol_errors`。

v0.18 的 infrastructure validity 和 readiness 均为 false。没有事后忽略该 episode 或放宽检查。资源聚合后来从 144 个不可变 result/trace 重建，修正为统计全部 provider calls；没有重跑任何 API episode。最终为 468 external calls、457,546 tokens、估算 `$0.01694112`。完整摘要 SHA-256 为 `ac876b09b05539e5da57ed320bf217cd18014f49221ce83c1eb0086c3e1e2424`。

## v0.19：有效的全新运行

v0.19 只把 response cap 从 256 提高到 512，并全新运行全部 144 episodes；没有复用或挑选 v0.18 结果。

| Runtime | Clean SafePass@3 | Fault SafePass@3 | Fault recovery rate |
|---|---:|---:|---:|
| R0 Raw | 8/8 | 3/8 | 0.375 |
| R1 Guarded | 8/8 | 1/8 | 0.125 |
| R2 Reliable | 8/8 | 8/8 | 1.000 |

描述性 primary effects：

- R2 − R1 fault recovery `SafePass@3` delta：`+0.875`；
- R2 − R1 clean `SafePass@3` delta：`0.0`。

全部 13 项 validity checks 和 3 项模型质量 readiness checks 通过。472 次外部调用均得到可接受的结构化 response；provider errors `0`、local protocol errors `0`、reasoning tokens `0`。144 条 journal 均通过 digest-only audit，289 个本地 study 文件中未发现进程内精确 credential。

## Token、成本与 provider 证据

| 指标 | v0.19 实测 |
|---|---:|
| External/model calls | 472 / 472 |
| Input tokens | 428,517 |
| Cache-hit / cache-miss input | 394,112 / 34,405 |
| Output tokens | 37,626 |
| Total tokens | 466,143 |
| Reasoning tokens | 0 |
| Estimated cost | `$0.0164554936` |
| Latency p50 / p95 | 968 / 1,388 ms |

成本按 2026-08-08 冻结的 [DeepSeek 官方定价](https://api-docs.deepseek.com/quick_start/pricing)计算：cache-hit input `$0.0028/M`、cache-miss input `$0.14/M`、output `$0.28/M`。这是 artifact 的审计估算，不是账单声明。API 返回的唯一 system fingerprint 为 `fp_a18b46594c_prod0820_fp8_kvcache_20260402`；provider 没有暴露 immutable serving-weight hash。

## Evidence 与数据边界

- [公开 compact summary](../artifacts/deepseek_flash_pilot_v19/summary.json) 为 37,705 bytes，SHA-256 `f265eb542d3250473feaf5d0774db1804627d84dbd418ee7fa61062b72b2af9e`；
- 本地忽略的完整 summary SHA-256 `3e3d89cfdce912b400ff987d89616779ecc2563f223c1359cf34dc29e67b07a1`；
- episode 集合 SHA-256 `d01c7e8431c51fe167f069721fe19764b8b648694cd8be87572577091e851b00`；
- study/source/trace manifest SHA-256 分别为 `02c5cd1f14b814f1a0ccdafd29947d0c7fb1a3094604ff10e5882a4d6a50851f`、`7308794d3ad97ff6468b110eb63e45a37975188b526ead31a70020add05677f8`、`d83cde5d1cbbca4510f598e3dbf84e39fee62f863be67fb6c949a92d09f5982d`。

完整 `full-summary.json`、144 result 与 144 trace 保留在本地 `.gitignore` 路径；公开 summary 保存完整摘要/episode digest、聚合、validity、readiness 和 manifests。credential 只从环境变量读取，原始 provider request/response 不写入 summary 或 trace。本实验只发送 ARL 自有合成 task/context/tool schema，不接触真实账户、真实业务系统或第三方目标。

## 能证明什么、还不能证明什么

该 pilot 支持一个窄而明确的结论：在这 8 个合成 task、一个模型 binding 和一个 environment seed 上，R2 在保持 clean `SafePass@3` 的同时，比 R1 恢复了更多 recoverable faults。它不能证明通用模型能力、跨模型稳健性、统计显著性或 24-task 主假设。

在 v0.19 冻结时，864-episode confirmatory main 仍有两个硬门禁：

1. 为 24-task catalog 补齐剩余 16 个 environment/fault/evaluator fixture；
2. 单独授权并冻结第二个精确模型 binding。

这些是 v0.19 当时的边界。v0.20/v0.21/v0.24 已完成第 1 项、task-cluster bootstrap 和 mechanism ablation。最新有效模型结果见 [Single-Slot Study v0.24](./main-single-slot-v24.md)；完整但无效的首个双模型运行见 [v0.27](./opencode-go-main-v27.md)，当前前瞻性合同见 [v0.28](./opencode-go-main-v28.md)。
