# ToolSandbox evaluator 最小复现

本复现不调用 LLM 或 RapidAPI，直接使用上游固定提交中的官方 scenario、`ExecutionEnvironment`、状态快照、milestone DAG 和 minefield matcher。它验证：

1. 状态依赖满足后，`enable → search` 与 `search → enable` 两条合法路径都能满分；
2. 跳过 cellular 前置状态时，工具真实失败，最终口头声称成功也不能满分；
3. 信息不足时安全拒绝可通过；
4. 猜测参数并执行禁用动作时，即使数据库发生写入，minefield 仍把总分清零。

## 固定环境

- ToolSandbox commit：`165848b9a78cead7ca7fe7c89c688b58e6501219`
- ToolSandbox version：`0.0.1`
- Python：3.9

## 运行

从已经按上游 `.[dev]` 安装的 ToolSandbox 仓库根目录执行：

```bash
python /absolute/path/to/run_toolsandbox_repro.py \
  --output /absolute/path/to/toolsandbox_repro_summary.json
```

详细实测见 [RESULTS.md](./RESULTS.md)，机器可读结果见 [results/toolsandbox_repro_summary.json](./results/toolsandbox_repro_summary.json)。
