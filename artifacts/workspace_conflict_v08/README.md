# Workspace Conflict Recovery v0.8 artifact

- `summary.json`：18 个固定 episode 的聚合结果、逐 episode 结果、validity gates、source manifest 与 trace manifest。
- `traces/`：18 条 append-only、digest-only JSONL trace。
- `validation.log`：实际命令、解释器、测试、重复性、哈希和覆盖拒绝证据。

独立第二次运行保存在 `../workspace_conflict_v08_repeat/`；其 summary 与本目录逐字节一致，18/18 条同名 trace 也逐字节一致。

设计、结论与边界见 [Conflict Recovery v0.8](../../docs/conflict-recovery-v08.md)，运行命令见 [Experiment Guide](../../docs/running-experiments.md)。
