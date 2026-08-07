# ARL Schema Adapter v0.7

Schema Adapter v0.7 在不新增业务域、不修改 v0.1–v0.6 冻结源码的前提下，为 Agent Reliability Lab 增加第一组可归因的工具合同漂移实验。它只使用本地合成 Travel 世界，不调用模型或网络，也不接触真实账户、凭据或第三方系统。

## 实验问题

当环境仍可完成同一业务任务，但公开工具的输入字段或成功结果从 `1.0` 变为 `2.0` 时，runtime 能否只依据公开 schema descriptor 做确定性适配，并保持最终状态和副作用合同？

clean/fault 对共享完全相同的初始 SQLite 状态、任务目标和 evaluator ground truth，只改变一个公开合同：

| 任务 | Fault 中唯一差异 | R1 行为 | R2 行为 |
|---|---|---|---|
| `travel.book_policy_compliant_itinerary` | `flights.book` 输入从 v1 五字段迁移到 v2 五字段 | 旧合同被 `schema_version_unsupported` 拒绝，状态不变 | 读取 descriptor，把 canonical v1 action 静态映射为 v2 后调用 |
| `travel.recover_bundle_after_flight_failure` | `hotels.book` 成功结果改为嵌套的 v2 reservation/amount | 写入已提交，但结果合同校验失败并停止 | 严格校验 v2 envelope，归一化为 canonical v1 结果后继续 |

R2 的 registry 不读取 task ID、seed、fault ID、evaluator 目标或隐藏状态。未知版本、缺失/额外字段、错误类型、descriptor 字段不匹配或允许额外字段时全部 fail closed。

## 配对结果

矩阵为 `2 tasks × 3 seeds × 2 runtimes × clean/fault = 24 episodes`。

| Runtime | Clean TaskSuccess | Fault TaskSuccess | SafeSuccess | RecoveryRate | 输入适配 | 输出归一化 |
|---|---:|---:|---:|---:|---:|---:|
| R1 Guarded | 6/6 | 0/6 | 6/12 | 0.0 | 0 | 0 |
| R2 Schema-adapted | 6/6 | 6/6 | 12/12 | 1.0 | 3 | 3 |

所有 R1 输入漂移 case 都在首次动作前安全失败；所有 R1 输出漂移 case 都保留一次已提交的酒店预订，因此 evaluator 不会把“runtime 停止”误判为任务完成。R2 对每个 fault episode 恰好使用一次对应 adapter，并完成原始目标。结果只证明固定合成任务上的 runtime 机制，不是模型能力或排行榜成绩。

## Validity gates

- 同 task/runtime/seed 的 clean/fault 初始 state hash 完全相同；
- 每个 fault episode 只出现一条注册差异，clean 不出现 fault ID；
- 九个 malformed-contract case 全部被拒绝，包括字段缺失、额外 alias、类型错误、未知版本和 descriptor 合同篡改；
- 9 份公开 descriptor 可重复生成，且不含 fault、target、seed、oracle、evaluator 或 idempotency 信息；
- 连续 20 次 reset 与 snapshot/restore 通过；
- do-nothing 与 claim-only 对两个任务均失败；
- trace 只保存 digest 与类型化元数据，不含原始 traveler/flight/hotel/arguments；
- v0.1–v0.6 六份历史 source manifest 全部逐文件匹配；
- 内部 shadow run、正式 run 与独立 repeat 均确定性一致。

## 证据

- [正式 summary](../artifacts/schema_adapter_v07/summary.json)
- [正式 24 条 trace](../artifacts/schema_adapter_v07/traces/)
- [独立 repeat](../artifacts/schema_adapter_v07_repeat/)
- [命令、版本和哈希](../artifacts/schema_adapter_v07/validation.log)
- [完整实验指南](./running-experiments.md)

正式与 repeat summary 逐字节一致，SHA-256 为 `a0b25f440651bfbe6776e2a4cb21c89630451775ad246fd4ae4735c4791b13d6`；24/24 条同名 trace 逐字节一致。v0.7 source manifest 覆盖 13 个实际依赖文件，SHA-256 为 `75a7ba7fbec5728215e3c0556973a38d05eb378f760bb3b9ef9ad817dae8bf64`。

## 限制与下一步

- 只有两个受控 schema 变更，没有自动字段匹配、未知版本协商或同时漂移；
- 仍是固定 oracle plan，不是模型 Agent；
- 沿用两个 Travel 任务，没有扩大域或任务规模；
- v0.7 本身没有一般冲突恢复；首条 Workspace guarded conflict rebase 已在 [v0.8](./conflict-recovery-v08.md) 实现，一般化 compensation、symbolic user、scheduler 和 trace viewer 仍未实现；
- 模型/API、真实账户、外部网络与攻击/防御实验均未实现或启用。
