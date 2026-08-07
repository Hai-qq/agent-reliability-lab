# Agent Reliability Lab

**Deterministic Agent Runtime × Stateful Reliability Benchmark**

[![CI](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Agent Reliability Lab（ARL）是一个**原创开源的 Agent 可靠性工程项目**。它在完全本地、合成、可重置的 SQLite 产品世界中，为工具型 Agent 提供类型化 Runtime、确定性故障注入、状态级 evaluator 和可复现实验门禁。

ARL 关注的不是“Agent 有没有说自己完成了任务”，而是：最终状态是否正确、是否产生越权或重复副作用、遇到模糊提交结果时能否安全恢复，以及相同实验能否稳定重现。

> 当前版本聚焦 runtime 与 benchmark 机制本身，使用固定策略隔离系统增益；无需模型、API 或真实账户即可完整运行。

## 核心能力

| 模块 | 当前实现 |
|---|---|
| Stateful environments | Workspace、Retail、Travel 三个合成业务域、6 个任务、确定性逻辑时间、reset/snapshot/state hash |
| Reliability runtime | R0/R1/R2 分层 runtime、类型化错误、有界重试、写入幂等、提交后确认、schema adapter 与受控补偿 |
| Fault injection | 对固定写操作注入 deterministic timeout、不可用分支及输入/输出 schema drift，构造 clean/fault 配对实验 |
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

运行最新的 schema drift / adapter 配对实验（目标路径必须尚不存在，runner 会拒绝覆盖已有证据）：

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_schema_adapter.py \
  --output /tmp/arl-schema-summary.json \
  --traces-dir /tmp/arl-schema-traces
```

核心 runtime 仅使用 Python 标准库，需要 Python 3.11 或更高版本。所有实验命令、固定版本与预期输出见 [Experiment Guide](./docs/running-experiments.md)。

## 当前可验证结果

| 增量 | 环境 / 门禁 | 结果 |
|---|---|---|
| [v0.1 Core MVP](./docs/core-mvp.md) | Workspace 单任务，R0/R1 | 12 episodes；R1 在 pre-commit timeout 下恢复 3/3 |
| [v0.2 R2](./docs/r2-reliability.md) | 幂等记录与提交后确认 | R1 fault 0/3；R2 fault 3/3 |
| [v0.3 Multi-Task](./docs/multitask-v03.md) | Workspace 双任务 | R1 fault 0/6；R2 fault 6/6；24/24 traces 可重复 |
| [v0.4 Validity Gates](./docs/validity-v04.md) | random/dump/golden 门禁 | random SafeSuccess 6/120；dump 12/12 被拒；trace mutation 全检出 |
| [v0.5 Retail](./docs/retail-v05.md) | 下单与政策内部分退款 | R1 fault 0/6；R2 fault 6/6；8/8 evaluator mutations |
| [v0.6 Travel](./docs/travel-v06.md) | 约束组合预订与航班失败恢复 | R1 fault 0/6；R2 fault 6/6；3 次确认 + 3 次补偿 |
| [v0.7 Schema Adapter](./docs/schema-adapter-v07.md) | 输入字段迁移与成功结果归一化 | R1 fault 0/6；R2 fault 6/6；3 次输入适配 + 3 次输出归一化 |

Schema Adapter v0.7 在既有 Travel 状态世界上只改变公开工具合同：3 个 `flights.book` fault 需要输入字段映射，3 个 `hotels.book` fault 需要成功结果归一化。R1 clean/fault 为 `6/6、0/6`，R2 为 `6/6、6/6`；正式与独立 repeat 的 summary 及 24/24 条 trace 均逐字节一致。当前仓库测试为 72 tests，GitHub Actions 在 Python 3.11/3.12 运行。

这些数字只证明固定合成任务上的 runtime/evaluator 机制，不是 LLM 能力或排行榜成绩。

## 项目结构

```text
src/arl*                 Runtime、Workspace、Validity、Retail、Travel 与 Schema Adapter 实现
scripts/                 可拒绝覆盖的确定性实验入口
tests/                   Unit、integration、validity 与 golden gates
artifacts/               固定 summary、digest-only traces、版本和哈希
docs/                    架构、增量合同与完整实验命令
```

完整组件关系、状态合同和数据流见 [Architecture](./docs/architecture.md)。

## 设计边界

- 只使用本地、合成、隔离环境；不连接真实账户、真实业务系统或模型 API。
- 不把文本声明当成功；主要结论来自状态差分、过程约束与副作用检查。
- 所有公开任务和状态数据均为本项目独立编写的合成内容。
- 当前仍是固定 oracle plan；schema adapter 只覆盖两条静态注册映射，补偿只覆盖一条预注册的可退款酒店取消。一般冲突恢复、symbolic user、scheduler、trace viewer 与模型实验尚未实现。

## Roadmap

1. 一般冲突恢复，并把单点酒店取消扩展为可审计的 compensation 合同。
2. Symbolic user、Study scheduler 与只读 trace viewer。
3. 扩充经人工审查的任务模板与跨 seed 重复统计。
4. 在单独授权和成本预算下接入模型 adapter，保持环境与 evaluator 不变。

## 文档导航

- [Architecture](./docs/architecture.md)：组件、状态合同、运行时层级与数据流。
- [Experiment Guide](./docs/running-experiments.md)：测试、实验命令、固定版本和结果校验。
- [Open-source Policy](./docs/open-source.md)：公开内容、发布门禁与项目边界。
- [Third-party Provenance](./THIRD_PARTY.md)：设计影响与独立实现声明。

## 开源与贡献

项目原创代码与文档采用 [MIT License](./LICENSE)。贡献前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，安全与授权边界见 [SECURITY.md](./SECURITY.md)，公开发布门禁见 [docs/open-source.md](./docs/open-source.md)。引用信息见 [CITATION.cff](./CITATION.cff)。
