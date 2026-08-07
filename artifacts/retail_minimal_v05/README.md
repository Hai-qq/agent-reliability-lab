# Retail Minimal v0.5 artifacts

- `summary.json`：24 个 episode、按 runtime/task 聚合、Retail validity gates、源码与 trace manifest。
- `traces/`：每个 episode 一条 digest-only JSONL trace，共 24 条、222 个事件。
- `validation.log`：真实命令、固定版本、测试结果、哈希、独立重复和限制。

独立第二次运行保存在 `../retail_minimal_v05_repeat/`；其 summary 与本目录逐字节一致，24/24 条同名 trace 也逐字节一致。

设计、结论与边界见 [Retail Minimal v0.5](../../docs/retail-v05.md)，运行命令见 [Experiment Guide](../../docs/running-experiments.md)。
