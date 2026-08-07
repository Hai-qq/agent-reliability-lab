# ARL Workspace Validity Gates v0.4

v0.4 在不调用模型、不访问网络、不修改 v0.1–v0.3 冻结源码的前提下，补齐 random-valid-tool、dump-state 和 golden-trace 三组 validity gates。它验证 evaluator 是否会被弱策略或输出文本误导，以及保存 trace 是否发生结构或内容漂移。

## Random-valid-tool baseline

基线使用 SHA-256 对 `task_id / environment seed / policy seed / step` 派生选择索引。每次动作都具有正确 schema、参数类型、当前 state version 和唯一 idempotency key，但不使用隐藏状态或 oracle 顺序。

矩阵为 `2 tasks × 3 environment seeds × 20 policy seeds × 5 steps = 120 rollouts`，覆盖 7 个配置工具。

| 指标 | 结果 | 门禁 |
|---|---:|---:|
| Schema errors | 0 | 必须为 0 |
| TaskSuccess | 11/120（9.17%） | ≤ 20% |
| SafeSuccess | 6/120（5.00%） | ≤ 10% |
| 工具覆盖 | 7/7 | 必须完整 |

11 个 TaskSuccess 全部来自较短的“创建会议并通知”任务，其中 5 个因额外副作用没有通过 SafeSuccess；三步改期任务为 0/60。该结果不是随机策略性能主张，而是用于监测 evaluator 分数是否异常膨胀的固定负基线。

## Dump-state baseline

每个任务/seed 分别执行两类仅输出、不改状态的探针：

- 可见 observation dump；
- evaluator-only full snapshot probe。

full snapshot 只在本地计算 digest，内容不进入 journal 或 artifact。12/12 case 的状态哈希保持不变，TaskSuccess/SafeSuccess 均为 0；说明文本输出或完整状态转储本身不能替代目标状态变更。

## Golden-trace gate

从 v0.3 正式 artifact 固定四条 R2 seed-0 trace，覆盖两个任务的 clean/fault：

- 校验 summary/trace SHA-256；
- 要求事件字段精确匹配 schema；
- 校验 event id 唯一性、parent chain 和 state-hash chain；
- 校验 clean/fault 所需和禁止的事件类型；
- 拒绝 raw participants/recipients/email payload。

三类确定性 mutation 均被拒绝：parent chain 篡改、额外 raw 字段、内容 digest 篡改。非 object JSONL 和截断 trace 也由单元测试覆盖，不会使 verifier 崩溃。

## 证据

- [正式 summary](../artifacts/workspace_validity_v04/summary.json)
- [独立 repeat](../artifacts/workspace_validity_v04_repeat/summary.json)
- [命令、版本和哈希](../artifacts/workspace_validity_v04/validation.log)
- [golden spec](../tests/golden/workspace_multitask_v03.json)
- [完整实验指南](./running-experiments.md)

正式与 repeat summary 逐字节一致，SHA-256 为 `cf1108e91fb9fbc6c0bec8f473f68b202a6e80393f12b43d573c3c54b61c179a`。v0.4 源码 manifest 覆盖 28 个文件；v0.1–v0.3 的已记录 manifest 仍全部匹配。

## 限制与下一步

- 仍只有 Workspace 一个业务域和两个固定任务模板；
- random baseline 是确定性 open-loop 工具策略，不是模型 Agent；
- golden gate 只固定四条代表性 trace；
- 没有 scheduler、viewer、symbolic user、模型/API 或网络。

后续 v0.5 已完成 Retail 本地 SQLite 状态、两个任务、oracle/evaluator、reset/snapshot 与 fault/runtime 配对，v0.6 已完成 Travel 双任务与查询确认/受控补偿，[v0.7](./schema-adapter-v07.md) 已完成两类 schema drift、九个 malformed-contract case 与历史 manifest 门禁，[v0.8](./conflict-recovery-v08.md) 已增加四个 guard mutation case、兼容冲突恢复与不兼容冲突 fail-closed 门禁。模型主实验仍不在当前授权范围。
