# ARL Parallel Study v0.11

Parallel Study v0.11 为 ARL 的持久化实验层增加 4 个真实本地 worker thread，以及可审计的 lease、heartbeat、expiry、crash retry 和 stale-commit fencing。任务 attempt 允许重复执行，但每个 job 最终只能接受一次 result/trace commit。

## 协议

Coordinator 仍以固定 `StudyManifest` 为唯一 job 顺序，并为每次 acquisition 分配：

- 固定 `worker-0` 至 `worker-3`；
- 单调递增的 job-local lease epoch；
- 绑定 manifest、job、worker 和 epoch 的 SHA-256 token；
- 基于 logical tick 的确定性 expiry；
- 独立且拒绝覆盖的 attempt trace 路径。

一批最多 4 个 executor 在 `ThreadPoolExecutor` 中并行运行；coordinator 按 manifest 顺序处理返回值、故障和 commit。只有 token/epoch/worker 仍匹配且 lease 未过期的 attempt 可以提交。Result record 绑定 payload digest、lease 信息与 trace SHA-256；final result/trace 已存在时拒绝重复提交。

Resume 会先校验 manifest、worker 集、lease 参数、state shape 和全部 completed artifact 哈希。若 result/trace 已落盘但 state 尚未更新，会按 lease 链接 reconcile；只有一半 artifact 或链接不一致则 fail closed。进程中断遗留 lease 不会被静默复用，而是记录为 expiry 后重新 acquisition。

## 固定验证运行

工作负载保持为 v0.9 的 36 个 Retail/Travel resilience episode。正式首阶段完成 12 个 job，并故意留下 4 个 active lease；第二阶段从新进程 resume，回收这 4 个 lease，再固定执行：

- 1 次 worker crash，旧 partial attempt trace 保留；
- 1 次 lease expiry，旧 attempt 的 final commit 被明确拒绝；
- 1 次 heartbeat，延长对应 lease 的 logical expiry。

| Gate | 保存结果 |
|---|---:|
| 首阶段完成 / pending / leased | 12 / 20 / 4 |
| Resume 新完成 | 24 |
| Lease acquisition / expiry | 42 / 5 |
| Worker crash / stale commit rejection / heartbeat | 1 / 1 / 1 |
| 最大 active lease | 4 |
| 最终完成 / accepted commit | 36 / 36，各 1 次 |
| 保留的失败/过期 attempt trace | 2 |
| v0.9 episode / final trace 等价 | 36/36 / 36/36 |
| v0.1–v0.10 source manifest | 10/10 matched |

恢复前 12 个结果/trace 的组合哈希在恢复前后同为 `329ac0c4186f79c91edf92358bea25ff10195170d199335f964ff3edb3b78adb`。正式与 repeat 的中断 summary、最终 summary/state、36 个 result、36 条 final trace 和 2 条 attempt trace 均逐字节一致。

固定哈希：

```text
interrupted: de7e0eb2b3255d15aad57630516cd1855c941ac1887977f3db0f0d30c13b3a7f
summary:     5b199723774540d19f1c3f6916411703e0dc961f7b193fa6960bfb21d4156a6f
state:       a87acc7ce8a5d3c17f1bd1100651248302155728ebdbae77c31d4d65a37d7afd
source:      4eaf8bd306a7ddc4fcb7e9b589d063cd13031049c38a25396efdd8d863635375
```

## 证据

- [中断 checkpoint](../artifacts/parallel_study_v11/interrupted.json)
- [最终 summary](../artifacts/parallel_study_v11/summary.json)
- [完整 state、36 个 result、36 条 final trace 和 2 条 attempt trace bundle](../artifacts/release_bundle_v15/bundles/parallel-study-v11.zip)
- [独立 repeat](../artifacts/parallel_study_v11_repeat/)
- [命令、版本、哈希和验证日志](../artifacts/parallel_study_v11/validation.log)
- [逐文件 bundle manifest 与恢复目标](../artifacts/release_bundle_v15/manifest.json)

## 限制

- worker 是单进程内本地线程，不是多进程或分布式主机；
- lease 与 heartbeat 使用 logical tick，不代表真实 wall-clock 或网络 failure detector；
- checkpoint 仍在 job/lease 状态转换边界，不保存 episode 内部任意动作位置；
- 正式故障矩阵固定为一次 crash、一次 expiry 和一次 heartbeat；
- 工作负载仍是固定 oracle plan；没有模型、symbolic user、外部网络、账户、凭据或真实系统。
