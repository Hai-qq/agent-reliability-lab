# ARL Study Runtime v0.10

Study Runtime v0.10 为 ARL 增加一个可恢复的本地实验执行层：固定 manifest、逐转换持久化、fail-closed resume、结果完整性校验，以及一个完全离线的只读 trace viewer。它是 ARL 自身的产品模块，不依赖模型、外部 API 或第三方 benchmark runtime。

## 执行合同

`StudyManifest` 固定 study ID、experiment version、job 顺序和每个 job 的 canonical JSON payload。创建 workspace 后，scheduler 为每个 job 预注册唯一的 result、trace 和 attempt 路径；已存在的 workspace 会被拒绝。

每个 job 按以下顺序提交：

1. 标记 `running`、增加 attempt 计数并原子保存 state；
2. executor 只写本次 attempt trace；
3. 写入带 job/payload/trace 链接的 result record；
4. 将 attempt trace 移到最终 trace 路径；
5. 保存 result/trace SHA-256，标记 `completed` 并再次原子保存 state。

State 写入使用临时文件、`flush`、`fsync` 和 `os.replace`。Resume 会重新构造同一个 manifest，并验证：

- schema、study ID、experiment version、job 顺序和 canonical payload 完全一致；
- job 状态、固定 artifact 路径和 attempt 计数合法；
- 每个 completed job 的 result/trace 文件存在且 SHA-256 与 state 一致；
- result record 的 job ID、payload digest、trace digest 和结构互相链接。

已完成 job 只校验和跳过。若进程在 result/trace 已完整落盘但 state 尚未更新时中断，resume 可按链接哈希完成 reconciliation；没有 final artifact 的 running job 会回到 pending，旧 attempt 保留，新 attempt 使用递增编号。只有一半 final artifact 或任一链接不匹配时立即 fail closed。

## 固定验证运行

v0.10 使用 v0.9 的 36 个固定 Retail/Travel resilience episode 作为 scheduler workload：

```text
2 domains × 2 runtimes × 3 conditions × 3 seeds = 36 jobs
```

首次运行在完成第 13 个 job 后主动停止。第二次以 `--resume` 启动时，scheduler 验证并跳过这 13 个 job，只执行余下 23 个。结果如下：

| Gate | 保存结果 |
|---|---:|
| 首阶段完成 / 待执行 | 13 / 23 |
| Resume 新执行 | 23 |
| 最终完成 | 36 / 36 |
| 已完成 job attempt count | 全部为 1 |
| 恢复前 13 个结果组合哈希 | `de8e068ad4f0…d599f16f30` |
| 恢复后同一组合哈希 | `de8e068ad4f0…d599f16f30` |
| State history | 77 events |
| v0.9 episode / trace 等价 | 36/36 / 36/36 |
| v0.1–v0.9 source manifest | 9/9 matched |

正式运行和独立 repeat 的 `interrupted.json`、`summary.json`、`study-state.json`、36 个 result、36 条 trace 和 `viewer.html` 均逐字节一致。最终 summary SHA-256 为 `c660aad0b8370670f7b10fc4352e11e1d969b8ca003d59d1e4bddf670ad279a5`，source manifest 覆盖 24 个文件，组合 SHA-256 为 `6a72d0ce9d5e8bb4e46da67e47b11ff6e85f31651e1550a0a434609827dc2a9f`。

## Read-only trace viewer

完整运行必须同时指定 `--viewer`。生成的单文件 HTML 内嵌 36 个 episode 的摘要与事件白名单字段，可按 domain、runtime、condition、outcome 和关键字筛选，并展开单条事件链。

Viewer 只包含 event type、actor/tool、error/fault code、逻辑时间、state hash 与 input/output digest；不包含原始 action arguments、任务正文或合成记录。它没有外部依赖、`fetch`、`XMLHttpRequest`、`WebSocket` 或可变实验接口。桌面与 390 px 窄屏渲染、筛选和详情展开均做过浏览器 QA，控制台无错误。

## 证据

- [中断 checkpoint summary](../artifacts/study_runtime_v10/interrupted.json)
- [最终 summary](../artifacts/study_runtime_v10/summary.json)
- [完整 state、36 个 result 与 36 条 trace bundle](../artifacts/release_bundle_v15/bundles/study-runtime-v10.zip)
- [离线 viewer](../artifacts/study_runtime_v10/viewer.html)
- [独立 repeat](../artifacts/study_runtime_v10_repeat/)
- [命令、版本、哈希和 QA](../artifacts/study_runtime_v10/validation.log)
- [逐文件 bundle manifest 与恢复目标](../artifacts/release_bundle_v15/manifest.json)

完整命令见 [Experiment Guide](./running-experiments.md)。

## 限制

- 当前是本地单进程、固定顺序 scheduler；没有并行 worker、lease、分布式队列、优先级或通用 DAG。
- checkpoint 发生在 job 状态转换处，不保存 episode 内部任意指令位置；中断中的 job 由 reconciliation 或新 attempt 处理。
- 正式验证只做一次 13/36 的任务边界中断；单元测试另覆盖 executor failure、旧 attempt 保留、manifest 不匹配、trace 篡改和 in-flight result 链接错误。
- viewer 是静态只读证据，不提供实时 tail、运行控制或远程服务。
- workload 仍是固定 oracle plan；不证明模型 Agent 能力，也不涉及真实账户、网络、凭据或第三方系统。
