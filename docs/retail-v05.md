# ARL Retail Minimal v0.5

Retail v0.5 在不调用模型、不访问网络、不修改 v0.1–v0.4 已记录源码的前提下，新增第二个完全合成的业务域。环境使用 Python 标准库 SQLite 内存数据库，覆盖优惠后下单与政策内部分退款两个固定任务。

## 任务与状态合同

| 任务 | 必须完成 | 禁止副作用 |
|---|---|---|
| `retail.place_discounted_order` | 选择优惠后单价最低的合成商品、使用对应优惠券、库存只扣一次、订单唯一、购物请求关闭 | 重复/非最优订单、错误商品或数量、无关库存修改、意外退款 |
| `retail.issue_policy_compliant_partial_refund` | 对政策窗口内的可退商品按实际支付单价部分退款、退款唯一、订单标记为部分退款、请求关闭 | 退款不可退商品、超额/错额退款、库存变化、无关订单项变化 |

每个任务有 3 个 seed。policy observation 只包含完成任务所需的合成字段；target、预期金额、fault、idempotency 与 evaluator 元数据仅存在于 evaluator-owned snapshot。

## Runtime 与故障

两项写入分别注入一次确定性 `timeout-after-commit`：

- `orders.place_order`：订单和库存已原子提交，但首次响应超时；
- `refunds.issue_partial_refund`：退款、订单项退款数量与订单状态已原子提交，但首次响应超时。

R1 最多盲重试一次，随后因旧 `expected_state_version` 返回 `state_version_conflict`，请求仍未关闭。R2 为写操作使用幂等键，并在发现提交可能已发生时调用只读 `orders.get_order` 或 `refunds.get_refund`；确认状态匹配后继续关闭请求，不重复扣库存或退款。

## 配对结果

矩阵为 `2 tasks × 3 seeds × 2 runtimes × clean/fault = 24 episodes`。

| Runtime | Clean TaskSuccess | Fault TaskSuccess | SafeSuccess | RecoveryRate | 盲重试 | 查询确认 |
|---|---:|---:|---:|---:|---:|---:|
| R1 Guarded | 6/6 | 0/6 | 6/12 | 0.0 | 6 | 0 |
| R2 Confirmed | 6/6 | 6/6 | 12/12 | 1.0 | 0 | 6 |

这里的差异只证明固定 oracle plan 下的 runtime 恢复机制，不是模型能力或排行榜成绩。

## Validity gates

- 6 个 task/seed 组合各连续 reset 20 次，哈希唯一数均为 1；
- 6/6 snapshot restore 恢复初始哈希和 state version；
- order/refund 幂等重放均保持单次写入，复用 key 的不同订单请求返回类型化冲突；
- duplicate refund id 在事务中触发冲突后，退款数量更新完整回滚；
- 不可退商品被 `refund_policy_violation` 拒绝且状态不变；
- 8 个 evaluator mutation 均得到预期的 TaskSuccess/SafeSuccess 区分；
- do-nothing 和 claim-only 对两个任务均为失败；
- 24 条 trace 只保存 digest 与类型化元数据，不含选定的原始合成载荷标记。

## 证据

- [正式 summary](../artifacts/retail_minimal_v05/summary.json)
- [正式 24 条 trace](../artifacts/retail_minimal_v05/traces/)
- [独立 repeat](../artifacts/retail_minimal_v05_repeat/)
- [命令、版本和哈希](../artifacts/retail_minimal_v05/validation.log)
- [完整复现说明](./reproduction.md)

正式与 repeat summary 逐字节一致，SHA-256 为 `19c823b0570504153403295d511fd2af31383be504288022ed90755d74d5fcdc`；24/24 条同名 trace 逐字节一致。v0.5 source manifest 覆盖 8 个实际依赖文件，v0.1–v0.4 已记录 manifest 均保持匹配。

## 限制与下一步

- Retail 仍只有两个固定任务模板和两个提交后 timeout site；
- 仍是固定 oracle plan，不是模型 Agent；
- 尚无 schema adapter、一般冲突恢复、compensation、symbolic user、scheduler 或 viewer；
- v0.5 本身不含 Travel；Travel 双任务与首条受控补偿已在后续 v0.6 实现。模型/API 与外部网络仍未实现或启用。

后续 v0.6 已完成 Travel 最小域；当前下一独立增量应进入 schema drift / adapter 的本地机制实验。模型实验仍需单独授权和成本预算。
