# Pilot Preflight v0.17 artifact

- `summary.json`：8 个可运行任务、6 类故障、48 个 scripted episode、聚合结果与 validity gates。
- 本地 `traces/`：48 条 append-only、digest-only JSONL trace；完整目录由 Git ignore，但保留在本机用于复验。
- `validation.log`：正式命令、双 Python 测试、重复性、哈希、evaluator mutation、隐私和覆盖拒绝证据。

独立 repeat 位于 `../pilot_preflight_v17_repeat/`。两次运行的 summary 和 48/48 traces 均逐字节一致。

本 artifact 是 144-episode 模型 pilot 之前的**零模型基础设施门禁**。它使用相同的 R0/R1/R2 policy/runtime 边界和 deterministic reactive oracle，证明 8 个任务的环境、fault、oracle 与 evaluator 能一起运行；它不报告模型能力、`SafePass^3` 或置信区间。设计与限制见 [Pilot Preflight v0.17](../../docs/pilot-preflight-v17.md)，完整命令见 [Experiment Guide](../../docs/running-experiments.md)。
