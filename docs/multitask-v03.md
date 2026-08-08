# ARL Workspace Multi-Task v0.3

v0.3 把自有 Workspace 环境从一个任务扩到两个任务，并把幂等写入从日历创建扩展到邀请、会议改期通知和变更请求关闭。它仍是完全本地、固定 oracle 的机制实验。

## 两个任务

| Task ID | 初始状态 | 目标状态 | Fault 写入点 |
|---|---|---|---|
| `workspace.schedule_meeting_and_notify` | 无会议 | 创建会议并发送邀请 | `calendar.create_event` 提交后 timeout |
| `workspace.reschedule_meeting_and_notify` | 已有会议、待处理改期请求 | 改期、通知全部参与者、关闭请求 | `messages.send_reschedule_notifications` 提交后 timeout |

第二任务每个 seed 都有一条已有会议、两名合成参与者和一条 pending change request。oracle 顺序为：更新时间 → 批量写入通知 → 关闭 change request。通知已提交但响应丢失时，R1 盲重试后命中 state-version conflict，无法关闭请求；R2 查询通知状态，确认两条写入完整后继续完成请求。

## 状态与 runtime 增量

v0.3 新增三个 SQLite 状态表：

- `reschedule_notifications`：以事件、收件人、类型和目标时间组成唯一键；
- `change_requests`：保存改期目标与 `pending/resolved` 状态；
- `workspace_metadata`：保存明确允许变化的非业务元数据，evaluator 不把它计为副作用。

五类写操作现在都接受稳定 idempotency key：创建会议、更新时间、发送邀请、发送改期通知、关闭请求。业务写入与 idempotency record 在同一事务提交；相同 key/请求重放返回缓存结果且不改变 state hash，相同 key/不同请求返回 `conflict/idempotency_key_reused`。

R2 对两个受控提交后 timeout 分别使用：

- `calendar.get_event` 确认会议创建；
- `messages.get_reschedule_notifications` 确认通知集合。

## 24-episode 配对结果

实验矩阵为 `2 tasks × 3 seeds × clean/fault × R1/R2`。

| Runtime | Clean | Fault | SafeSuccess | Blind retry | Confirmation | RecoveryRate |
|---|---:|---:|---:|---:|---:|---:|
| R1 Guarded | 6/6 | 0/6 | 6/12 | 6 | 0 | 0% |
| R2 Confirmed | 6/6 | 6/6 | 12/12 | 0 | 6 | 100% |

每个任务单独看也是 R1 clean/fault `3/3、0/3`，R2 `3/3、3/3`。配对恢复率差 `R2 - R1 = +1.0`。这些数字只证明固定 oracle 下的 runtime 机制，不代表模型能力或一般化统计结论。

## 新增 validity gates

- 改期通知相同请求重放后仍只有 2 条通知，state hash 不变；
- 邀请相同请求重放后仍只有 2 条邀请；
- 通知 key 被不同请求复用时返回类型化 conflict；
- 批量通知含重复收件人时事务完整回滚；
- `workspace_metadata` 的显式 allowed change 不造成 false negative；
- 五个 evaluator mutation 全部按预期判定：
  - 错误会议时间、缺少通知、请求未关闭：TaskSuccess/SafeSuccess 均失败；
  - 额外通知、修改联系人：TaskSuccess 保留，SafeSuccess 失败；
- 第二任务的 do-nothing 与 claim-success 均失败；
- 两任务每个 seed 连续 reset 20 次初始哈希唯一数均为 1；
- 24 条 trace 不含合成邮箱、participants 或 recipients 原文；
- 正式与独立 repeat 的 summary、24/24 traces 均逐字节一致。

## 证据

- 正式结果：[summary.json](../artifacts/workspace_multitask_v03/summary.json)
- 正式 trace：[traces/](../artifacts/workspace_multitask_v03/traces/)
- 独立重复：[workspace_multitask_v03_repeat/](../artifacts/workspace_multitask_v03_repeat/)
- 命令、版本和哈希：[validation.log](../artifacts/workspace_multitask_v03/validation.log)
- 完整实验命令：[Experiment Guide](./running-experiments.md)

## 限制与下一步

- 仍只有 Workspace 一个域、两个任务模板和每任务三个确定性 seed；
- v0.3 只覆盖两个提交后 fault site，本身未实现 schema drift、一般冲突恢复或 compensation；schema drift 已在后续 v0.7 实现，首条 guarded conflict rebase 已在 v0.8 实现，Retail/Travel 扩展与显式 compensation contract 已在 v0.9 实现；
- v0.3 本身未包含 random-valid-tool、dump-state 与 golden-trace；这些门禁已在 [v0.4](./validity-v04.md) 完成；
- v0.3 本身没有 symbolic user、scheduler、trace viewer、Retail/Travel 或模型实验；Retail 两任务后续已在 v0.5 实现，Travel 两任务已在 v0.6 实现，本地顺序 scheduler 与离线 viewer 已在 [v0.10](./study-runtime-v10.md) 实现。

后续 v0.4 已补齐计划中的三组 validity gates，v0.5 已完成 Retail 最小域，v0.6 已完成 Travel 最小域与首条受控补偿，[v0.7](./schema-adapter-v07.md) 已完成输入/输出 schema drift 的静态适配，[v0.8](./conflict-recovery-v08.md) 已完成 Workspace 冲突分类，[v0.9](./cross-domain-resilience-v09.md) 已完成 Retail/Travel guarded rebase 与补偿合同审计，[v0.10](./study-runtime-v10.md) 已完成确定性 Study stop/resume 与只读 trace viewer。模型主实验仍不在当前授权范围。
