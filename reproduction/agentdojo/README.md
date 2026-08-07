# AgentDojo utility evaluator 最小复现

本复现只使用官方固定提交中的合成 `workspace` suite，不调用模型、不访问网络、不加载 injection task，也不生成攻击或防御材料。它验证三件事：

1. 固定提交的完整官方测试能否通过；
2. utility evaluator 对正确工具执行、空响应和“只给答案、不调用工具”三种固定轨迹的判定；
3. `benchmark_suite_without_injections` 作为库函数使用时的 logger 兼容性。

## 固定环境

- AgentDojo commit：`089ed468cf3ed0322acc66b0211f26d9d90dbf60`
- AgentDojo version：`0.1.35`
- benchmark version：`v1.2.2`
- suite：`workspace`
- Python：`3.12.2`
- 模型调用、外部网络调用、injection task：均为 `0`

## 官方测试

从 AgentDojo checkout 根目录执行：

```bash
env PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m pytest -q -p no:cacheprovider
```

实测 `32 passed in 5.02s`。原始输出见 [official-tests.log](./results/official-tests.log)。

## 运行固定合成样例

仍从 AgentDojo checkout 根目录执行：

```bash
.venv/bin/python /absolute/path/to/run_agentdojo_repro.py \
  --output /absolute/path/to/agentdojo_repro_summary.json
```

脚本固定使用两个只读任务 `user_task_0`、`user_task_1` 和一个状态写入任务 `user_task_6`，每个运行三种本地 pipeline：

| Variant | 行为 |
|---|---|
| `oracle` | 使用官方 `GroundTruthPipeline` 执行工具调用 |
| `empty` | 不调用工具，返回空答案 |
| `claim_only` | 不调用工具，只返回任务类中的公开 `GROUND_TRUTH_OUTPUT` |

三种 variant 各重复 3 次，共 27 个 episode。机器结果见 [agentdojo_repro_summary.json](./results/agentdojo_repro_summary.json)，分析与限制见 [RESULTS.md](./RESULTS.md)。

## 兼容性说明

AgentDojo 0.1.35 的 `benchmark_suite_without_injections` 若在没有 logger context 时直接作为库函数调用，会得到：

```text
AttributeError: 'NullLogger' object has no attribute 'logdir'
```

官方 CLI 会先进入 `OutputLogger` context，因此不受此问题影响。本脚本验证了两条非侵入式路径：

- 使用与官方 CLI 相同的 `OutputLogger` context，helper 可正常返回；
- 不需要原始 trace 文件时，直接调用 `TaskSuite.run_task_with_pipeline`。

本项目没有修改 AgentDojo 上游源码。完整探针结果已写入机器 JSON。
