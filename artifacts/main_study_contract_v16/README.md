# Main Study Contract v0.16 artifact

- `summary.json`：12 个 scripted smoke episode、冻结主实验合同、24-task blueprint、聚合结果与 validity gates。
- 本地 `traces/`：12 条 append-only、digest-only JSONL trace；完整目录由 Git ignore，但保留在本机用于复验。
- `validation.log`：正式命令、双 Python 测试、重复性、哈希、隐私门禁和覆盖拒绝证据。

独立 repeat 位于 `../main_study_contract_v16_repeat/`。两次运行的 summary 和 12/12 traces 均逐字节一致。

本 artifact 只验证统一 Policy/Runtime harness 在两个已迁移合成任务上的公平性和故障恢复机制；它不是模型 pilot，也不是 864-episode 主实验结果。设计、冻结矩阵与限制见 [Main Study Contract v0.16](../../docs/main-study-v16.md)，完整命令见 [Experiment Guide](../../docs/running-experiments.md)。
