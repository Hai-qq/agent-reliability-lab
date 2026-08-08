# Parallel Study v0.11 artifact

- `interrupted.json`：12/36 完成并遗留 4 个 active lease 时的 summary。
- 本地 `study/`：恢复完成后的 state、36 个 result、36 条 final trace 与 2 条 attempt trace；完整树由 Git ignore。
- `summary.json`：最终聚合、resume/lease/fault 门禁、历史 source manifest 与 artifact manifest。
- `validation.log`：实际命令、版本、双 Python 测试、重复性、哈希和覆盖拒绝证据。

独立 repeat 保存在 `../parallel_study_v11_repeat/`。两次运行的中断 summary、最终 summary/state、36 个 result、36 条 final trace 和 2 条 attempt trace 均逐字节一致。

公开仓库中的完整 state/result/trace 位于 [v0.11 deterministic bundle](../release_bundle_v15/bundles/parallel-study-v11.zip)，逐文件清单与恢复目标见 [v0.15 manifest](../release_bundle_v15/manifest.json)。

设计与限制见 [Parallel Study v0.11](../../docs/parallel-study-v11.md)，完整运行命令见 [Experiment Guide](../../docs/running-experiments.md)。
