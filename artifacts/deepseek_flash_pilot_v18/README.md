# DeepSeek Flash Model Pilot v0.18 artifact

- `summary.json`：公开 compact aggregate，保留结果、validity、readiness、manifest 和完整证据哈希，不含逐 episode 记录。
- 本地 `full-summary.json`：144 个完整 digest-only episode record，由 Git ignore；SHA-256 `ac876b09b05539e5da57ed320bf217cd18014f49221ce83c1eb0086c3e1e2424`。
- 本地 `study/`：144 result、144 JSONL trace 与 checkpoint state，由 Git ignore。
- `validation.log`：命令、失败门禁、计费聚合修订、哈希、凭据/trace audit 与测试结果。

该版本是保留的**失败预检**：256-token response cap 导致一个 tool call JSON 被截断，产生 1 次 local protocol error，所以 validity/readiness 为 false。它不进入主结论，也没有被事后删去失败 episode。通过 512-token cap 全新运行的有效结果见 [v0.19 artifact](../deepseek_flash_pilot_v19/README.md) 与 [设计说明](../../docs/model-pilot-v19.md)。
