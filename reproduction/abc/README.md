# ABC × τ-bench 有效性漏洞复现

本实验复现 ABC 仓库对历史版 τ-bench 的两类反例，不调用 LLM：

1. `no_op`：Agent 不执行任何任务动作，直接结束；
2. `dump_all`：Agent 不改变数据库，但把整个模拟数据库序列化到回答里。

两种轨迹都直接交给 τ-bench 原始奖励函数判定。导出结果只有计数与公开 task index，不包含任务说明、用户数据或数据库内容。

## 固定版本

- ABC commit：`ae1124758098876db04336e1d8c6e419a139c6e3`
- 历史 τ-bench commit：`14bf0ef52e595922d597a38f32d3e8c0dce3a8f8`
- Python：3.11
- 模型调用：0

## 准备修复版工作树

ABC 提供的补丁用普通 `git apply --check` 会报 `corrupt patch at line 110`，但 `--recount` 可重新计算错误的 hunk 行数并正确应用：

```bash
git -C /absolute/path/to/tau-bench worktree add --detach \
  /absolute/path/to/tau-fixed \
  14bf0ef52e595922d597a38f32d3e8c0dce3a8f8

git -C /absolute/path/to/tau-fixed apply --recount \
  /absolute/path/to/agentic-benchmarks/benchmarks/tau-bench/tau-bench-issue-1-fix.patch
```

## 运行

需要 Python 3.10+ 和 `pydantic`。脚本会注入一个拒绝任何模型调用的 `litellm` stub，只执行本地 evaluator：

```bash
python run_abc_repro.py \
  --tau-original /absolute/path/to/tau-bench \
  --tau-fixed /absolute/path/to/tau-fixed \
  --abc-repo /absolute/path/to/agentic-benchmarks \
  --output /absolute/path/to/abc_repro_summary.json
```

实测摘要：

| 版本 | Domain | No-op | Dump-all |
|---|---|---:|---:|
| 原始 evaluator | Airline | 19/50（38.0%） | 20/50（40.0%） |
| 原始 evaluator | Retail | 7/115（6.1%） | 11/115（9.6%） |
| ABC issue-1 补丁 | Airline | 0/50 | 1/50（2.0%） |
| ABC issue-1 补丁 | Retail | 7/115（6.1%） | 11/115（9.6%） |

完整解释见 [RESULTS.md](./RESULTS.md)，机器可读证据见 [abc_repro_summary.json](./results/abc_repro_summary.json)。
