# DeepSeek Flash Model Pilot v0.19 artifact

- `summary.json`：37,705-byte 公开 compact aggregate，含聚合、validity、readiness、manifests 和完整证据哈希。
- 本地 `full-summary.json`：144 个完整 digest-only episode record，由 Git ignore；SHA-256 `3e3d89cfdce912b400ff987d89616779ecc2563f223c1359cf34dc29e67b07a1`。
- 本地 `study/`：144 result、144 JSONL trace 与 checkpoint state，由 Git ignore。
- `validation.log`：正式命令、模型 binding、资源用量、哈希、凭据/trace audit、测试与限制。

固定矩阵为 8 tasks × 1 seed × 2 conditions × 3 runtimes × 1 model × 3 trials = 144 episodes。clean `SafePass@3` 三档均为 8/8；fault R0/R1/R2 分别为 3/8、1/8、8/8。全部 validity 和模型质量 readiness gate 通过。v0.19 冻结时仍缺 16 个 fixture 与第二模型 binding；后续 v0.20 已补齐 task pack，v0.24 已完成 432-episode single-slot study，目前只剩第二 binding 阻止 864 main。完整历史解释见 [v0.19 文档](../../docs/model-pilot-v19.md)，最新结果见 [v0.24 文档](../../docs/main-single-slot-v24.md)。
