# ABC × τ-bench 有效性复现报告

> 运行日期：2026-08-06；这是 benchmark evaluator 审计，不是 Agent 能力排行榜复现。

## 结论

历史版 τ-bench 的奖励函数只比较最终数据库哈希；当参考动作本身不改变数据库且没有必答字符串时，完全不行动也会与“正确结果”哈希相等。因此：

| 原始 evaluator 反例 | Airline | Retail |
|---|---:|---:|
| `no_op` | **19/50（38.0%）** | **7/115（6.1%）** |
| `dump_all` | **20/50（40.0%）** | **11/115（9.6%）** |

结果逐项复现了 ABC 仓库 README 报告的 38%/6% 与 40%/9.6%。这里的 `dump_all` 并不调用 Agent：实验把模拟数据库序列化为一条 `respond` 动作，再由原始 substring evaluator 和状态 evaluator 判分。

## 修复补丁验证

ABC 的 issue-1 补丁给 19 个 Airline 任务增加 `required_actions`，补丁后的 19 个 task index 与原始 `no_op` 满分集合完全相同。实跑结果：

| 补丁后 | Airline | Retail |
|---|---:|---:|
| `no_op` | **0/50** | **7/115（6.1%）** |
| `dump_all` | **1/50（2.0%）** | **11/115（9.6%）** |

这说明该补丁精确封住 Airline 的 issue 1，但有两个明确边界：

- 补丁没有修改 Retail，Retail 两类反例完全不变；
- Airline 仍有 1 个任务能被数据库全文倾倒通过，即 README 所述 issue 2，说明 required-action 门禁不能替代输出防泄漏设计。

另外，仓库中的补丁 hunk 行数已失配：普通 `git apply --check` 实测报 `corrupt patch at line 110`，使用 `git apply --recount --check` 才通过。复现工作树由 `--recount` 应用，未手工改写上游补丁。

## ABC 清单自身审计

当前 `ABC.md` 有 42 个检查项，分为 `I / II / III`；仓库内 10 份 YAML assessment 仍使用旧版 `O / T / R` schema。τ-bench assessment 只有 31 个打分项（20 个 1、11 个 0），存在版本漂移。

更关键的是，旧 assessment 的 `T.10` 给出 1 分并声称没有可利用漏洞，而同一 ABC 仓库随后提供了两个可复现 exploit。它不是“清单无效”的证明，恰恰说明 benchmark 审计也必须版本化、带回归基线，并在发现漏洞后同步修订 assessment。

## 对 Agent Reliability Lab 的直接设计约束

1. 必须运行 `no_op`、`dump_all`、随机动作等 trivial baselines；
2. 只读成功不能只比较最终状态，还要验证最小必要观测/动作证据；
3. 必答字符串不得来自 Agent 可整体枚举的数据空间；
4. 修复一个 domain 后必须对所有 domain 跑回归；
5. checklist、assessment schema、evaluator 版本和结果必须绑定同一 commit。

## 可复现性与边界

- 原始版和补丁版完整运行两次；去除生成时间后，两次 evaluator 结果一致。
- 运行过程把 `litellm.completion` 替换为必然报错的 stub，实际模型/用户模拟器调用数为 0。
- 机器结果只保存通过数量和公开 task index；没有复制任务提示、数据库或用户数据。
- ABC 仓库根目录在固定 commit 下未发现 `LICENSE*`/`COPYING*` 文件，因此本项目只引用、审计和记录 commit，不再分发其补丁或源码。
- 修复补丁本身只针对 issue 1，不能被表述为 τ-bench 的完整修复。

机器可读结果：[abc_repro_summary.json](./results/abc_repro_summary.json)。
