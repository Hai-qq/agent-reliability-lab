# Travel Minimal v0.6 artifacts

- `summary.json`：24-episode clean/fault 配对结果、validity gates、source/trace manifest；
- `traces/`：24 条 digest-only JSONL trace；
- `validation.log`：固定环境、命令、结果、哈希、审计与限制；
- 独立重复结果位于 [`../travel_minimal_v06_repeat/`](../travel_minimal_v06_repeat/)。

这些 artifact 只来自本地固定合成任务，不包含模型调用、真实账户、外部网络或上游 benchmark 数据。
