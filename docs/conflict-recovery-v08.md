# ARL Conflict Recovery v0.8

Conflict Recovery v0.8 在不新增业务域、不修改 v0.1–v0.7 冻结源码的前提下，为 R2 增加第一条可审计的状态版本冲突恢复路径。实验只使用本地合成 Workspace 世界，不调用模型或网络，也不接触真实账户、凭据或第三方系统。

## 实验问题

当计划中的写操作携带旧 `expected_state_version` 时，runtime 能否区分：

1. 其他 actor 只改了与当前操作无关的状态，目标前置条件仍成立，可以安全 rebase；
2. 其他 actor 已经改了当前目标字段，原计划不再安全，必须停止而不是覆盖对方写入。

三个 condition 共享完全相同的初始 SQLite 状态、任务目标和 evaluator：

| Condition | 唯一差异 | 正确行为 |
|---|---|---|
| `clean` | 无并发变化 | 正常完成改期、通知和请求关闭 |
| `compatible_conflict` | 首次更新时间前，外部 actor 原子更新允许变化的 metadata 并递增 state version | 读取目标事件；原始时间未变时允许一次 rebase |
| `incompatible_conflict` | 首次更新时间前，外部 actor 原子修改目标事件时间并递增 state version | 读取目标事件；前置条件变化时 fail closed |

```mermaid
sequenceDiagram
    participant R as Conflict-aware R2
    participant E as Workspace environment
    participant D as SQLite state
    R->>E: update_event_time(expected_version=0)
    E->>D: concurrent atomic change; version=1
    E-->>R: state_version_conflict
    R->>E: get_event(expected_version=1)
    E-->>R: public target state
    alt guard exact match
        R->>E: update_event_time(expected_version=1)
        E-->>R: committed; continue plan
    else target changed
        R-->>R: conflict_precondition_changed; stop
    end
```

Guard 由初始公开 observation 和公开 read tool 构造，不读取 task ground truth、fault ID、evaluator、内部 world export 或故障模式。每个动作最多允许一次 rebase；guard 缺失、路径缺失、读合同异常或第二次冲突全部停止。

## 配对结果

矩阵为 `1 task × 3 seeds × 2 runtimes × 3 conditions = 18 episodes`。

| Runtime | Clean TaskSuccess | Compatible TaskSuccess | Incompatible TaskSuccess | Compatible recovery | Classified safe abort |
|---|---:|---:|---:|---:|---:|
| R2 Confirmed | 3/3 | 0/3 | 0/3 | 0.0 | 0.0 |
| R2 Conflict-aware | 3/3 | 3/3 | 0/3 | 1.0 | 1.0 |

`incompatible_conflict` 的 TaskSuccess 预期为 0：外部 actor 已改变目标时间，runtime 没有用户授权覆盖该状态。正确性由单独的 classified-abort gate 判断；3/3 case 均返回 `conflict_precondition_changed`，保留外部时间，且通知数、关闭请求数和 idempotency record 数均为 0。

Conflict-aware R2 共看到 6 个冲突，执行 6 次公开状态 probe：3 次 guard 匹配并 rebase 后完成，3 次 guard 不匹配并停止。结果只证明固定合成任务上的 runtime 机制，不代表模型能力或一般化并发控制。

## Validity gates

- 每个 seed 的两种 runtime、三个 condition 初始 state hash 完全相同；
- clean 不出现 fault ID；两类 conflict episode 各只出现一条对应注册差异；
- 旧 R2 的 6 个 conflict episode 均停在 `state_version_conflict`，不读取 guard；
- compatible conflict 3/3 完成一次 probe、一次 rebase、零 abort，在 evaluator 中各记录一条 recovery event，并达到 SafeSuccess；
- incompatible conflict 3/3 完成一次 probe、零 rebase、一次 classified abort，且没有 runtime 写副作用；
- exact/change/missing/wrong-shape 四个 guard contract case 全部通过；
- 三种 mode 各连续 reset 20 次一致，snapshot/restore 与 fault reinjection 通过；
- do-nothing 与 claim-only 均被 evaluator 拒绝；
- observation 不含 fault、conflict mode、oracle、evaluator 或 minefield 信息；
- trace 只保存 digest 与类型化元数据，不含 arguments、合成邮箱或并发 metadata 原文；
- v0.1–v0.7 七份历史 source manifest 全部逐文件匹配；
- 内部 shadow run、正式 run 与独立 repeat 均确定性一致。

## 证据

- [正式 summary](../artifacts/workspace_conflict_v08/summary.json)
- [正式 18 条 trace](../artifacts/workspace_conflict_v08/traces/)
- [独立 repeat](../artifacts/workspace_conflict_v08_repeat/)
- [命令、版本和哈希](../artifacts/workspace_conflict_v08/validation.log)
- [完整实验指南](./running-experiments.md)

正式与 repeat summary 逐字节一致，SHA-256 为 `91d72d86f156377416344669c9bd0517a298b1e4f7af5816993eca53e57ad6f7`；18/18 条同名 trace 逐字节一致。v0.8 source manifest 覆盖 20 个实际依赖文件，SHA-256 为 `23f30e2d16ca2fbb5b1b9235d3e295a8cb04be669df089b92b8c43315b44fdc5`。

## 限制与下一步

- 只覆盖既有 Workspace 改期任务的一个冲突点和三个 seed；
- guard 使用精确值匹配，不做自动语义合并、字段级 merge 或模型推理；
- 每个动作最多一次 rebase，没有长事务、锁、并行 scheduler 或多 actor event stream；
- 仍是固定 oracle plan，不是模型 Agent；
- 后续 [v0.9](./cross-domain-resilience-v09.md) 已把 guard/rebase 合同扩展到 Retail/Travel 各一个写入点，并为酒店取消增加可审计 compensation contract；动态补偿规划仍未实现；
- 本地顺序 scheduler 与 trace viewer 已在后续 [v0.10](./study-runtime-v10.md) 实现；symbolic user、模型/API 与真实系统集成仍未实现或启用。
