# Scenario Pack v0.12 artifact

- `summary.json`：72 个 episode、4-template aggregate、workflow 与 validity gates。
- 本地 `traces/`：72 条 append-only、digest-only JSONL trace；完整树由 Git ignore。
- `validation.log`：正式命令、双 Python 测试、重复性、哈希和覆盖拒绝证据。

独立 repeat 位于 `../scenario_pack_v12_repeat/`。两次运行的 summary 和 72/72 traces 均逐字节一致。

公开 trace 位于 [v0.12 deterministic bundle](../release_bundle_v15/bundles/scenario-pack-v12-traces.zip)，逐文件清单与恢复目标见 [v0.15 manifest](../release_bundle_v15/manifest.json)。

设计与限制见 [Scenario Pack v0.12](../../docs/scenario-pack-v12.md)，完整命令见 [Experiment Guide](../../docs/running-experiments.md)。
