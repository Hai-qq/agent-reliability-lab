# Agent Reliability Lab

**Deterministic Agent Runtime × Stateful Reliability Benchmark**

[![CI](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Agent Reliability Lab（ARL）是一个**原创开源的 Agent 可靠性工程项目**。它在完全本地、合成、可重置的 SQLite 产品世界中，为工具型 Agent 提供类型化 Runtime、确定性故障注入、状态级 evaluator 和可复现实验门禁。

ARL 关注的不是“Agent 有没有说自己完成了任务”，而是：最终状态是否正确、是否产生越权或重复副作用、遇到模糊提交结果时能否安全恢复，以及相同实验能否稳定重现。

> 当前公开版本为无需模型、无需 API、无需真实账户的机制原型。仓库中的论文调研与五项 benchmark 最小复现是项目的设计依据和验证来源，不是这个仓库的产品身份。

## 核心能力

| 模块 | 当前实现 |
|---|---|
| Stateful environments | Workspace 与 Retail 两个合成业务域、4 个任务、确定性逻辑时间、reset/snapshot/state hash |
| Reliability runtime | R0/R1/R2 分层 runtime、类型化错误、有界重试、写入幂等、提交后查询确认 |
| Fault injection | 对固定写操作注入 deterministic `timeout-after-commit`，构造 clean/fault 配对实验 |
| State evaluator | 基于最终数据库差分验证 TaskSuccess、SafeSuccess、必要状态与禁止副作用 |
| Validity gates | evaluator mutation、random-valid-tool、dump-state、golden-trace、ground-truth isolation |
| Reproducible traces | append-only、digest-only JSONL journal；固定 seed、源码 manifest 与重复运行哈希 |

## 快速开始

```bash
git clone https://github.com/Hai-qq/agent-reliability-lab.git
cd agent-reliability-lab

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

运行 Retail clean/fault 配对实验（目标路径必须尚不存在，runner 会拒绝覆盖已有证据）：

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_retail_minimal.py \
  --output /tmp/arl-retail-summary.json \
  --traces-dir /tmp/arl-retail-traces
```

核心 runtime 仅使用 Python 标准库，需要 Python 3.11 或更高版本。所有实验命令、固定版本与预期输出见 [Reproduction Guide](./docs/reproduction.md)。

## 当前可验证结果

| 增量 | 环境 / 门禁 | 结果 |
|---|---|---|
| [v0.1 Core MVP](./docs/core-mvp.md) | Workspace 单任务，R0/R1 | 12 episodes；R1 在 pre-commit timeout 下恢复 3/3 |
| [v0.2 R2](./docs/r2-reliability.md) | 幂等记录与提交后确认 | R1 fault 0/3；R2 fault 3/3 |
| [v0.3 Multi-Task](./docs/multitask-v03.md) | Workspace 双任务 | R1 fault 0/6；R2 fault 6/6；24/24 traces 可重复 |
| [v0.4 Validity Gates](./docs/validity-v04.md) | random/dump/golden 门禁 | random SafeSuccess 6/120；dump 12/12 被拒；trace mutation 全检出 |
| [v0.5 Retail](./docs/retail-v05.md) | 下单与政策内部分退款 | R1 fault 0/6；R2 fault 6/6；8/8 evaluator mutations |

Retail v0.5 的正式运行覆盖 `2 tasks × 3 seeds × 2 runtimes × clean/fault = 24 episodes`。R2 的 6 个 fault episode 均通过只读查询确认已提交状态，盲重试为 0；正式与独立 repeat 的 summary 及 24/24 条 trace 均逐字节一致。当前仓库测试为 49 tests，GitHub Actions 在 Python 3.11/3.12 运行。

这些数字只证明固定合成任务上的 runtime/evaluator 机制，不是 LLM 能力或排行榜成绩。

## 项目结构

```text
src/arl*                 Runtime、Workspace、Validity 与 Retail 实现
scripts/                 可拒绝覆盖的确定性实验入口
tests/                   Unit、integration、validity 与 golden gates
artifacts/               固定 summary、digest-only traces、版本和哈希
docs/                    架构、增量合同与完整复现命令
reproduction/            上游 benchmark 的本地最小验证证据
```

完整架构、指标合同与阶段路线见 [Project Blueprint](./04_完整项目蓝图.md)。

## 设计边界

- 只使用本地、合成、隔离环境；不连接真实账户、真实业务系统或模型 API。
- 不把文本声明当成功；主要结论来自状态差分、过程约束与副作用检查。
- 不分发上游 benchmark 源码、数据、私有 oracle 或完整任务载荷。
- 当前仍是固定 oracle plan；Travel、schema adapter、一般冲突恢复、补偿、symbolic user、scheduler、trace viewer 与模型实验尚未实现。

## Roadmap

1. Travel 最小域：两个本地状态任务、oracle/evaluator、clean/fault 配对。
2. Schema adapter、一般冲突恢复与 compensation 消融。
3. Symbolic user、Study scheduler 与只读 trace viewer。
4. 在单独授权和成本预算下接入模型 adapter，保持环境与 evaluator 不变。

## Research provenance

ARL 源于对 Agent runtime、stateful benchmark 与 evaluator validity 的本地研究，但当前 runtime、环境、测试与任务均为独立实现；没有 vendoring 上游源码、数据或 benchmark trace。五项最小复现仅用于确认哪些机制值得进入 ARL 的设计：

- [AppWorld](./reproduction/appworld/RESULTS.md)：状态差分与副作用 evaluator；
- [ToolSandbox](./reproduction/toolsandbox/RESULTS.md)：milestone、minefield 与状态依赖；
- [ABC × τ-bench](./reproduction/abc/RESULTS.md)：弱基线与 evaluator 漏洞审计；
- [AgentDojo](./reproduction/agentdojo/RESULTS.md)：utility evaluator 与兼容性门禁；
- [BrowserGym](./reproduction/browsergym/RESULTS.md)：本地 runtime/harness、恢复与续跑。

更完整的研究证据保存在 [30-paper evidence matrix](./01_30篇论文证据矩阵.csv)、[field review](./02_领域综述.md)、[selected-five plan](./03_精选5篇与复现计划.md) 与 [references.bib](./references.bib)。第三方边界见 [THIRD_PARTY.md](./THIRD_PARTY.md)。

## 开源与贡献

项目原创代码与文档采用 [MIT License](./LICENSE)。贡献前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，安全与授权边界见 [SECURITY.md](./SECURITY.md)，公开发布门禁见 [docs/open-source.md](./docs/open-source.md)。引用信息见 [CITATION.cff](./CITATION.cff)。
