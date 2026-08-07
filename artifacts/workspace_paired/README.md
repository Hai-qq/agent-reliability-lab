# Workspace clean/fault paired artifacts

- `summary.json`：12 个 episode、聚合结果、validity checks 和源码 manifest。
- `traces/`：每个 episode 一条 digest-only JSONL trace，共 12 条。
- `validation.log`：实际测试、静态检查、结果和逐字节复现证据。

实验设计、结论和限制见 [ARL Core MVP](../../docs/core-mvp.md)，重现命令见 [reproduction](../../docs/reproduction.md)。
