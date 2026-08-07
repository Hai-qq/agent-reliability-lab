# ARL Travel Minimal v0.6

Travel v0.6 新增第三个完全合成的业务域，把既有状态 evaluator 与提交后确认扩展到行程预订，并加入首条受控补偿路径。环境使用 Python 标准库 SQLite 内存数据库；不调用模型、不访问网络、不接触真实账户或第三方系统。

## 任务与状态合同

| 任务 | 必须完成 | 禁止副作用 |
|---|---|---|
| `travel.book_policy_compliant_itinerary` | 从可见航班/酒店中选择满足路线、时间、预算与可退款约束的最低价组合，只预订一次并关闭请求 | 非最优或不可退款组合、重复/无关预订、错误库存扣减、支付方式修改 |
| `travel.recover_bundle_after_flight_failure` | 正常时完成首选组合；首选航班不可用时取消已订的可退款酒店，再预订备选组合并关闭请求 | 遗留首选酒店、重复预订、未观察故障就切换、错误库存或超预算组合 |

每个任务固定 3 个 seed。Policy observation 只包含完成任务所需的合成选项、约束与预注册 ID；target、预期总价、fault、idempotency 与 evaluator 元数据只存在于 evaluator-owned snapshot 或 harness。

## Runtime 与故障

两项任务对应两类确定性故障：

- 行程组合任务在首次 `flights.book` 事务提交后返回一次 `tool_timeout_postcommit`。R1 盲重试后命中旧 state version；R2 使用幂等键，并通过 `flights.get_booking` 确认已提交状态后继续。
- 恢复任务先预订首选酒店，再让首选 `flights.book` 返回 `flight_unavailable` 且不改状态。R1 停止并遗留活动酒店；R2 进入一次预注册 recovery branch，取消首选酒店、恢复房量、预订备选航班/酒店并关闭请求。

补偿仅覆盖这一个已知、可退款的酒店取消动作，不代表一般化 planner、任意回滚或分布式事务能力。

## 配对结果

矩阵为 `2 tasks × 3 seeds × 2 runtimes × clean/fault = 24 episodes`。

| Runtime | Clean TaskSuccess | Fault TaskSuccess | SafeSuccess | RecoveryRate | 查询确认 | Recovery branch | 补偿 |
|---|---:|---:|---:|---:|---:|---:|---:|
| R1 Guarded | 6/6 | 0/6 | 6/12 | 0.0 | 0 | 0 | 0 |
| R2 Confirmed | 6/6 | 6/6 | 12/12 | 1.0 | 3 | 3 | 3 |

R2 的 3 次查询确认对应提交后 timeout，3 条 recovery branch 对应首选航班不可用，3 次补偿均为首选酒店取消。结果只证明固定 oracle plan 下的 runtime/evaluator 机制，不是模型能力或排行榜成绩。

## Validity gates

- 6 个 task/seed 组合各连续 reset 20 次，哈希唯一数均为 1；
- 6/6 snapshot restore 恢复初始哈希和 state version；
- 航班预订与酒店取消幂等重放均不重复写，复用 key 的不同请求返回类型化冲突；
- 重复酒店 reservation ID 在事务中触发冲突后，房量扣减完整回滚；
- 不可退款航班在没有显式确认时被 `confirmation_required` 拒绝且状态不变；
- 8 个 evaluator mutation 均得到预期的 TaskSuccess/SafeSuccess 区分；
- do-nothing 和 claim-only 对两个任务均失败；
- R1 遗留酒店被 `orphaned_hotel_after_flight_failure` minefield 检出；
- 24 条 trace 只保存 digest 与类型化元数据，不含选定的合成 traveler/flight/hotel/argument 标记。

## 证据

- [正式 summary](../artifacts/travel_minimal_v06/summary.json)
- [正式 24 条 trace](../artifacts/travel_minimal_v06/traces/)
- [独立 repeat](../artifacts/travel_minimal_v06_repeat/)
- [命令、版本和哈希](../artifacts/travel_minimal_v06/validation.log)
- [完整复现说明](./reproduction.md)

正式与 repeat summary 逐字节一致，SHA-256 为 `51a5bd6aabca4b243c79325aa8446dd652ecefddfc9dba3d55303fd60e8b3bda`；24/24 条同名 trace 逐字节一致。v0.6 source manifest 覆盖 8 个实际依赖文件，SHA-256 为 `67a01d88b24fb41a61d550966e4137aca3a892bf35d24c170a600baa0f30c35c`。

## 限制与下一步

- Travel 仍只有两个固定任务模板、一个提交后 timeout 与一个航班不可用分支；
- 仍是固定 oracle plan，不是模型 Agent；
- 补偿只允许取消一条已知可退款酒店预订；
- 尚无 schema adapter、一般冲突恢复、symbolic user、scheduler 或 viewer；
- 模型/API、真实账户、外部网络与攻击/防御实验均未实现或启用。

下一独立增量应进入 schema drift / adapter 的本地机制实验，再扩展一般冲突恢复；模型实验仍需单独授权和成本预算。
