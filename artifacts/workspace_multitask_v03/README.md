# Workspace Multi-Task v0.3 artifacts

- `summary.json`：24 个 episode、按 runtime/task 聚合、15 项 selected validity checks、源码与 trace manifest。
- `traces/`：每个 episode 一条 digest-only JSONL trace，共 24 条、198 个事件。
- `validation.log`：真实命令、版本、结果、哈希、独立重复与限制。

独立第二次运行保存在 `../workspace_multitask_v03_repeat/`；其 summary 与本目录逐字节一致，24/24 traces 也逐字节一致。

设计、结论与边界见 [Workspace Multi-Task v0.3](../../docs/multitask-v03.md)，运行命令见 [Experiment Guide](../../docs/running-experiments.md)。
