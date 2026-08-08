# Cross-Domain Resilience v0.9 artifact

- `summary.json`：36 个固定 episode 的聚合结果、逐 episode 结果、validity gates、source manifest 与 trace manifest。
- `traces/`：36 条 append-only、digest-only JSONL trace。
- `validation.log`：实际命令、解释器、测试、重复性、哈希和覆盖拒绝证据。

独立第二次运行保存在 `../cross_domain_resilience_v09_repeat/`；其 summary 与本目录逐字节一致，36/36 条同名 trace 也逐字节一致。

设计、结论与边界见 [Cross-Domain Resilience v0.9](../../docs/cross-domain-resilience-v09.md)，运行命令见 [Experiment Guide](../../docs/running-experiments.md)。
