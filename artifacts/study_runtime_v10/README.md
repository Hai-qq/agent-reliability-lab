# Study Runtime v0.10 artifact

- `interrupted.json`：第 13/36 个 job 后主动停止时的 summary 与 validity gates。
- 本地 `study/`：恢复完成后的 state、36 个 result 和 36 条 digest-only trace；完整树由 Git ignore。
- `summary.json`：最终聚合、resume preservation、历史 manifest 与 artifact manifest。
- `viewer.html`：自包含、无网络依赖的只读 trace viewer。
- `validation.log`：实际命令、解释器、测试、重复性、哈希、浏览器 QA 和覆盖拒绝证据。

独立第二次运行保存在 `../study_runtime_v10_repeat/`。两次运行的中断 summary、最终 summary、scheduler state、viewer、36 个 result 和 36 条 trace 均逐字节一致。

公开仓库中的完整 state/result/trace 位于 [v0.10 deterministic bundle](../release_bundle_v15/bundles/study-runtime-v10.zip)，逐文件清单与恢复目标见 [v0.15 manifest](../release_bundle_v15/manifest.json)。

设计、结论与边界见 [Study Runtime v0.10](../../docs/study-runtime-v10.md)，完整运行命令见 [Experiment Guide](../../docs/running-experiments.md)。`viewer.html` 可直接在本地浏览器打开；它不连接 API，也不能修改实验状态。
