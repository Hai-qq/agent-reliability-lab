# ARL Cross-Domain Resilience v0.9

Cross-Domain Resilience v0.9 将公开读 guard 和有界 state-version rebase 扩展到 Retail 与 Travel，并把 Travel 的酒店取消恢复步骤升级为可审计 compensation contract。实验仍只运行本地合成 SQLite 产品世界，不调用模型、网络或真实账户。

## 实验问题

v0.9 对两个既有任务各选择一个写入点，在相同初始状态下比较 `r2_confirmed` 与 `r2_contract_guarded`：

| Domain | Guarded write | Compatible conflict | Incompatible conflict |
|---|---|---|---|
| Retail | 关闭 purchase request | 其他 actor 只改无关 metadata | 目标 order status 已改变 |
| Travel | 取消首选酒店作为补偿 | 其他 actor 只改无关 metadata | 目标 reservation status 已改变 |

每个写操作最多 rebase 一次。只有计划中声明的公开 read 返回精确预期值时才更新 `expected_state_version`；目标值变化、路径缺失、读取失败、结果合同异常或第二次冲突都会 fail closed。

## Compensation contract

Travel 恢复分支不再只把“取消酒店”当作一个普通动作，而是显式声明：

- 精确触发条件：`flights.book / flight_unavailable`；
- 带非空 idempotency key 的取消动作；
- 取消前公开读取 reservation，要求状态为 `active`；
- 取消后再次公开读取，要求状态为 `cancelled`；
- `max_attempts = 1`；
- journal 只记录 contract、参数和值的 digest 及类型化事件，不记录原始载荷。

```mermaid
sequenceDiagram
    participant R as R2 Contract-guarded
    participant E as Travel environment
    R->>E: book preferred flight
    E-->>R: flight_unavailable
    R->>E: get reservation (precondition)
    E-->>R: active
    R->>E: cancel hotel (expected version)
    E-->>R: state_version_conflict
    R->>E: get reservation (conflict guard)
    alt target remains active
        E-->>R: active
        R->>E: cancel hotel (rebased once)
        E-->>R: committed
        R->>E: get reservation (postcondition)
        E-->>R: cancelled
    else target changed
        E-->>R: externally_changed
        R-->>R: conflict_precondition_changed; stop
    end
```

## 配对结果

矩阵为 `2 domains × 1 task × 3 seeds × 2 runtimes × 3 conditions = 36 episodes`。

| Runtime | Control TaskSuccess | Compatible TaskSuccess | Incompatible TaskSuccess | Compatible recovery | Classified safe abort |
|---|---:|---:|---:|---:|---:|
| R2 Confirmed | 6/6 | 0/6 | 0/6 | 0.0 | 0.0 |
| R2 Contract-guarded | 6/6 | 6/6 | 0/6 | 1.0 | 1.0 |

Retail 与 Travel 各自的 compatible conflict 都从 `0/3` 提升到 `3/3`。12 个 guarded conflict 中，runtime 做了 12 次公开 probe：6 次前置条件不变并完成一次 rebase，6 次目标状态已改变并返回 `conflict_precondition_changed`。后者的 TaskSuccess 预期为 0，因为 runtime 没有权限覆盖其他 actor 已修改的目标。

Travel 的 9 个 contract attempt 覆盖 control、compatible 和 incompatible 三种 condition：6 次完成 precondition、幂等取消和 postcondition 验证，3 次在目标 reservation 已改变时分类失败。结果只证明这两个固定合成任务上的 runtime 合同，不代表模型能力或一般化并发控制。

## Validity gates

- 每个 domain/seed 的两种 runtime、三个 condition 初始 state hash 完全相同；
- 12 个 control 全部达到 SafeSuccess；每个 fault episode 只出现注册差异；
- 旧 R2 的 12 个 conflict episode 均停在 `state_version_conflict`，不执行 guard probe；
- compatible conflict 6/6 完成一次 probe、一次 rebase 并达到 SafeSuccess；
- incompatible conflict 6/6 保留外部目标状态、保持 request pending，并分类停止；
- exact/change/missing/wrong-shape 四个 guard mutation case 全部通过；
- trigger、attempt bound、pre/postcondition 与 idempotency 四类 contract mutation gate 全部通过；
- 各 mode 连续 reset 20 次一致，snapshot/restore、fault reinjection 与 do-nothing rejection 通过；
- observation 不含 fault、conflict mode、oracle、evaluator 或 minefield 信息；
- trace 不含 arguments、合成标识或并发 metadata 原文；
- v0.1–v0.8 八份历史 source manifest 逐文件匹配；
- 内部 shadow run、正式 run 与独立 repeat 均确定性一致。

## 证据

- [正式 summary](../artifacts/cross_domain_resilience_v09/summary.json)
- [正式 36 条 trace](../artifacts/cross_domain_resilience_v09/traces/)
- [独立 repeat](../artifacts/cross_domain_resilience_v09_repeat/)
- [命令、版本和哈希](../artifacts/cross_domain_resilience_v09/validation.log)
- [完整实验指南](./running-experiments.md)

正式与 repeat summary 逐字节一致，SHA-256 为 `33c0cf3b4902418d8506a9582df9b21b37b0f2fd6d72c135ab38046211bf3676`；36/36 条同名 trace 逐字节一致。v0.9 source manifest 覆盖 20 个实际依赖文件，SHA-256 为 `c9dd9c76acb9768023b68ee18b3a3c1ab9782f6931e38be2e2cbd347d51799aa`。

## 限制与下一步

- 只覆盖 Retail purchase 与 Travel recovery 两个既有任务、每域一个冲突点和三个 seed；
- guard 使用精确值匹配，不做自动语义合并、字段级 merge 或模型推理；
- compensation 只有一类预注册酒店取消合同，没有动态补偿规划；
- 每个动作最多一次 rebase，没有长事务、锁、并行 scheduler 或多 actor event stream；
- 仍是固定 oracle plan，不是模型 Agent；
- symbolic user、Study scheduler、只读 trace viewer、模型/API 与真实系统集成仍未实现或启用。
