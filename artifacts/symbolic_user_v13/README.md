# Symbolic User v0.13 artifact

- `summary.json`：720 个配对 session、跨 repeat 统计、Wilson 区间与 validity gates。
- 本地 `traces/`：720 条 append-only、digest-only JSONL trace；完整树由 Git ignore。
- `validation.log`：正式命令、双 Python 测试、重复性、哈希、载荷门禁和覆盖拒绝证据。

独立 repeat 位于 `../symbolic_user_v13_repeat/`。两次运行的 summary 和 720/720 traces 均逐字节一致。

公开 trace 位于 [v0.13 deterministic bundle](../release_bundle_v15/bundles/symbolic-user-v13-traces.zip)，逐文件清单与恢复目标见 [v0.15 manifest](../release_bundle_v15/manifest.json)。

设计与限制见 [Symbolic User v0.13](../../docs/symbolic-user-v13.md)，完整命令见 [Experiment Guide](../../docs/running-experiments.md)。
