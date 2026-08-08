# ARL Scenario Pack v0.12

Scenario Pack v0.12 将现有 Retail purchase/refund 与 Travel booking/recovery 四个状态任务统一成可审计的 reliability task template。每个模板固定一个冲突写入点、一组 exact public-read guards 和允许的补偿类型；模板描述不包含任务载荷或 evaluator ground truth。

## 四个任务模板

| Template | 冲突写入点 | Guard / contract |
|---|---|---|
| Retail purchase resolution | `retail.resolve_purchase_request` | 订单仍为 `placed` |
| Retail refund resolution | `retail.resolve_refund_request` | refund 仍为 `issued` |
| Travel itinerary resolution | `travel.resolve_booking_request` | 航班仍 `booked` 且酒店仍 `active` |
| Travel fallback workflow | `hotels.cancel` | 单动作合同 + 4 步 bounded workflow |

每个 conflict site 都有两种固定原子变化：compatible condition 只改变无关 metadata；incompatible condition 改变即将写入的目标状态。旧 R2 看到 state-version conflict 后停止；template-guarded R2 只在全部公开读 guard 精确匹配时允许一次 rebase。

## Bounded compensation workflow

`CompensationWorkflowContract` 要求 2–8 个固定步骤、每个写入都有非空幂等键、首个补偿步骤有 pre/postcondition、整个 workflow 有 terminal postconditions，且最多尝试一次。当前 Travel fallback 固定为：

1. 取消已预订的首选可退款酒店；
2. 预订备选航班；
3. 预订备选酒店；
4. 将 booking request 解析到备选组合。

成功后通过 6 次 public read 验证：首选酒店已取消、备选航班已预订、备选酒店 active、请求 resolved，并且 selected flight/hotel ID 指向备选组合。任一 guard 不满足都会返回 machine-readable failure，部分 workflow 不记为成功。

## 固定验证结果

正式矩阵为：

```text
4 templates × 2 runtimes × 3 conditions × 3 seeds = 72 episodes
```

| Gate | 保存结果 |
|---|---:|
| R2 control | 12/12 SafeSuccess |
| R2 compatible conflict | 0/12 |
| Template-guarded control | 12/12 SafeSuccess |
| Template-guarded compatible conflict | 12/12 SafeSuccess，12 次 rebase |
| Template-guarded incompatible conflict | 12/12 分类停止，0 次 rebase |
| Workflow attempt / success / classified failure | 9 / 6 / 3 |
| 成功 workflow terminal probes | 36/36 |
| v0.1–v0.11 source manifests | 11/11 matched |

正式与独立 repeat 的 summary 和 72/72 traces 均逐字节一致。固定哈希：

```text
summary: 02cb8306f0cb932a205aec81ad22de7ce6f767e8d0ba1c61c96278e1d814f13a
source:  97cd66807a665bf67b9ccc2d00d927b1b4ed041b5dfaa01b3eecc2af21dccd87
traces:  eac40997996f6071cf1cce9a3e082d89e02f46ebdad34fccb2dd31a1a14be4f0
```

## 证据

- [正式 summary](../artifacts/scenario_pack_v12/summary.json)
- [72 条正式 trace bundle](../artifacts/release_bundle_v15/bundles/scenario-pack-v12-traces.zip)
- [独立 repeat](../artifacts/scenario_pack_v12_repeat/)
- [命令、版本、哈希和门禁](../artifacts/scenario_pack_v12/validation.log)
- [逐文件 bundle manifest 与恢复目标](../artifacts/release_bundle_v15/manifest.json)

## 限制

- 当前只有 4 个固定模板、4 个冲突点和一个 4 步 Travel workflow；
- guard 只支持精确相等，不做自动语义合并；
- workflow 是预注册固定序列，不是动态补偿规划器；
- 所有计划仍是固定 oracle；没有模型、symbolic user、真实账户、凭据、网络或第三方系统。
