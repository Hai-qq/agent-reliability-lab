# Evidence Explorer v0.14 artifact

- `index.html`：自包含、只读、离线产品证据页；无外部脚本、资源或网络请求。
- `evidence.json`：v0.10–v0.13 的聚合指标、输入哈希、source/trace manifest 与重验结果。
- `validation.log`：正式命令、双 Python 测试、浏览器 QA、重复性、哈希和覆盖拒绝证据。

独立 repeat 位于 `../evidence_explorer_v14_repeat/`。两次生成的 `index.html` 与 `evidence.json` 均逐字节一致。

克隆仓库后可直接在浏览器中打开 `index.html`。设计与限制见 [Evidence Explorer v0.14](../../docs/evidence-explorer-v14.md)，完整命令见 [Experiment Guide](../../docs/running-experiments.md)。

公开 clone 若要重新运行 builder，先按 [v0.15 bundle guide](../../docs/release-bundle-v15.md) 恢复 Git ignore 的完整 trace/workspace 子树；预生成页面本身不需要恢复。
