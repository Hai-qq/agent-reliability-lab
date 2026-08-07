# Workspace R2 post-commit paired artifacts

- `summary.json`：12 个 episode、聚合结果、11 项 selected validity checks、源码与 trace manifest。
- `traces/`：每个 episode 一条 digest-only JSONL trace，共 12 条、87 个事件。
- `validation.log`：真实命令、版本、结果、哈希、独立重复与限制。

独立第二次运行保存在 `../workspace_r2_postcommit_repeat/`；其 summary 与本目录逐字节一致，12/12 traces 也逐字节一致。

实验设计与边界见 [R2 可靠性增量](../../docs/r2-reliability.md)，运行命令见 [Experiment Guide](../../docs/running-experiments.md)。
