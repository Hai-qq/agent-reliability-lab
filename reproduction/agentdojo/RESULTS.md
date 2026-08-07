# AgentDojo utility evaluator 最小复现报告

> 运行日期：2026-08-07；本报告验证官方测试、utility evaluator 与聚合接口，不是模型能力或攻击/防御排行榜复现。

## 结论

固定 3 个官方合成 `workspace` 任务，每种轨迹重复 3 次：

| 固定轨迹 | Utility | `Pass^3` 任务 | 结论 |
|---|---:|---:|---|
| 官方 ground truth | **9/9（100%）** | **3/3** | evaluator 与官方正确工具执行兼容 |
| 空响应、无工具 | **0/9（0%）** | **0/3** | evaluator 不会把完全无输出当成完成 |
| 只给正确答案、无工具 | **6/9（66.7%）** | **2/3** | 两个只读任务通过，状态写入任务失败 |

27 个 episode 的初始环境 SHA-256 完全一致；第二次完整运行删除生成时间后与第一次 JSON 相同。

## 固定样例与 evaluator 含义

| Task ID | 类型 | Oracle | Empty | Claim-only |
|---|---|---:|---:|---:|
| `user_task_0` | 只读查询 | 通过 | 失败 | 通过 |
| `user_task_1` | 只读查询 | 通过 | 失败 | 通过 |
| `user_task_6` | 创建日历状态 | 通过 | 失败 | 失败 |

`claim_only` 是受控 validity probe：它直接使用任务类公开的 `GROUND_TRUTH_OUTPUT`，但不读取模拟环境、不执行工具。两个只读任务的 utility 只要求答案文本正确且环境未变化，所以会接受它；状态写入任务还检查真实环境变化，因此拒绝它。

这不能解释为 Agent 能力。它说明只读 evaluator 若要证明“Agent 确实完成了必要观察”，还需增加最小工具轨迹或观测证据；否则正确答案与正确执行无法区分。

## 官方测试与版本

- AgentDojo commit：`089ed468cf3ed0322acc66b0211f26d9d90dbf60`
- AgentDojo version：`0.1.35`
- benchmark version：`v1.2.2`
- Python：`3.12.2`
- 官方测试：**32 passed in 5.02s**
- Ruff：check 与 format check 均通过

测试使用 `-p no:cacheprovider` 和 `PYTHONDONTWRITEBYTECODE=1`，没有向上游 checkout 写入缓存；运行前后上游 Git 状态均为干净。

## Library helper 兼容性

直接在无 logger context 的 Python 调用中执行：

```python
benchmark_suite_without_injections(..., logdir=None)
```

当前版本会在构造 `TraceLogger` 时失败：默认 `Logger.get()` 返回一个尚未进入 context 的 `NullLogger`，其 `logdir` 属性只在 `__enter__` 中初始化。实测错误为：

```text
AttributeError: 'NullLogger' object has no attribute 'logdir'
```

使用官方 CLI 同款 `OutputLogger` context 后，同一 helper 正常返回并生成一条临时 trace；临时目录随探针退出被删除。正式 27 个 episode 直接走 `TaskSuite.run_task_with_pipeline`，不修改上游、不保存含模拟记录的完整 trace。

## 指标边界

- `TaskSuite.run_task_with_pipeline` 在 `injection_task=None` 时按定义返回 `security=True`。这是框架占位值，**不是安全实验结果**；JSON 标记 `security_metric_applicable=false`，报告不计算安全率。
- 三次重复是确定性回归门禁，不是独立随机样本，因此不报告置信区间。
- 未运行 LLM、attack、defense、injection task 或真实账户/第三方系统。
- 未导出任务 prompt、模拟环境记录、工具原始返回或上游自带攻击轨迹。

机器可读结果：[agentdojo_repro_summary.json](./results/agentdojo_repro_summary.json)。
