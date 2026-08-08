# Compact Artifact Bundle v0.15

- `manifest.json`：4 个确定性 ZIP 的逐文件 SHA-256、tree hash、bundle hash、恢复目标与 validity gates。
- `bundles/`：v0.10 Study、v0.11 Parallel、v0.12 traces、v0.13 traces 的无损公开证据包。
- `validation.log`：正式命令、双 Python 测试、正式/重复、无损恢复、大小与覆盖拒绝证据。

四个 formal 目录共 940 个文件，均与各自 repeat 目录逐字节相同；因此每个增量只公开一份 bundle。完整本地树继续保留，但由 `.gitignore` 排除，避免 GitHub 展示 1,880 个重复文件。

设计、验证和恢复命令见 [Compact Artifact Bundle v0.15](../../docs/release-bundle-v15.md) 与 [Experiment Guide](../../docs/running-experiments.md)。
