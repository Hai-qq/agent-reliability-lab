# Agent Reliability Lab

**Deterministic Agent Runtime × Stateful Reliability Benchmark**

[![CI](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Agent Reliability Lab（ARL）是一个**原创开源的 Agent 可靠性工程项目**。它在完全本地、合成、可重置的 SQLite 产品世界中，为工具型 Agent 提供类型化 Runtime、确定性故障注入、状态级 evaluator 和可复现实验门禁。

ARL 关注的不是“Agent 有没有说自己完成了任务”，而是：最终状态是否正确、是否产生越权或重复副作用、遇到模糊提交结果时能否安全恢复，以及相同实验能否稳定重现。

> 当前版本聚焦 runtime 与 benchmark 机制本身，使用固定策略隔离系统增益；无需模型、API 或真实账户即可完整运行。

**产品证据入口：** [在线 Evidence Explorer](https://hai-qq.github.io/agent-reliability-lab/) · [离线 artifact](./artifacts/evidence_explorer_v14/index.html)（所有数字均回链到冻结 JSON 与合同文档）。

## 核心能力

| 模块 | 当前实现 |
|---|---|
| Stateful environments | Workspace、Retail、Travel 三个合成业务域、6 个任务、确定性逻辑时间、reset/snapshot/state hash |
| Reliability runtime | R0/R1/R2 分层 runtime、类型化错误、有界重试、写入幂等、提交后确认、schema adapter、受控补偿与 guarded conflict rebase |
| Fault injection | 对固定写操作注入 deterministic timeout、不可用分支、输入/输出 schema drift 及兼容/不兼容并发更新 |
| State evaluator | 基于最终数据库差分验证 TaskSuccess、SafeSuccess、必要状态与禁止副作用 |
| Validity gates | evaluator mutation、random-valid-tool、dump-state、golden-trace、ground-truth isolation |
| Reproducible traces | append-only、digest-only JSONL journal；固定 seed、源码 manifest 与重复运行哈希 |
| Study runtime | 固定 manifest、原子 checkpoint、fail-closed resume、结果/trace 哈希校验与离线只读 viewer |
| Parallel study | 4 个本地 worker thread、确定性 lease/heartbeat/expiry、崩溃重试与 exactly-one final commit |
| Scenario pack | 4 个可审计任务模板、4 个冲突点、精确 public-read guard 与 4 步补偿 workflow |
| Stateful authorization | 结构化 symbolic user、完整意图澄清、revision-aware token fencing 与跨 repeat 配对统计 |
| Evidence explorer | v0.10–v0.13 聚合证据、864 对 trace 重验、离线筛选与 source/trace manifest 展示 |
| Compact release | 4 个确定性 ZIP、940-file manifest、无损恢复与公开 Git 树去重 |

## 快速开始

```bash
git clone https://github.com/Hai-qq/agent-reliability-lab.git
cd agent-reliability-lab

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/manage_artifact_bundles.py restore \
  --bundle-dir artifacts/release_bundle_v15 \
  --project-root .

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

全新 clone 需要先恢复 v0.10–v0.13 的完整 formal/repeat 证据树；恢复器会校验全部 bundle 和成员哈希，并拒绝覆盖已有目标目录。GitHub Actions 执行相同步骤后再运行测试。

运行最新的 stateful authorization matrix（目标路径必须尚不存在，runner 会拒绝覆盖已有证据）：

```bash
ARL_RUN=/tmp/arl-symbolic-user-v013

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_symbolic_user.py \
  --output "$ARL_RUN/summary.json" \
  --traces-dir "$ARL_RUN/traces"
```

完整运行会保存 720 个配对 session、跨 6 次 repeat 的统计与 720 条 digest-only trace。核心 runtime 仅使用 Python 标准库，需要 Python 3.11 或更高版本。并行 stop/resume 命令、全部实验版本与预期输出见 [Experiment Guide](./docs/running-experiments.md)。

公开 clone 先从 compact bundles 无损恢复完整 formal/repeat 树，再重新生成只读产品证据页；若本地完整树已存在，跳过 restore：

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/manage_artifact_bundles.py restore \
  --bundle-dir artifacts/release_bundle_v15 \
  --project-root .

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/build_evidence_explorer.py \
  --output-dir /tmp/arl-evidence-explorer-v014
```

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
| [v0.8 Conflict Recovery](./docs/conflict-recovery-v08.md) | 并发状态变化后的 guard 检查与有界 rebase | 兼容冲突恢复 3/3；目标冲突识别并安全停止 3/3 |
| [v0.9 Cross-Domain Resilience](./docs/cross-domain-resilience-v09.md) | Retail/Travel guard 与显式 compensation contract | 兼容冲突恢复 6/6；目标冲突分类停止 6/6；contract 6/9 完成、3/9 分类失败 |
| [v0.10 Study Runtime](./docs/study-runtime-v10.md) | 原子 checkpoint、确定性 stop/resume 与离线 trace viewer | 13/36 停止后仅续跑 23；原 13 个结果未变；正式/repeat 全部一致 |
| [v0.11 Parallel Study](./docs/parallel-study-v11.md) | 4 worker lease、heartbeat、expiry、crash retry 与 stale commit fencing | 12 完成 + 4 lease 后恢复；42 次 acquisition、5 次 expiry；36 个 final commit 各一次 |
| [v0.12 Scenario Pack](./docs/scenario-pack-v12.md) | 4 task templates、4 conflict sites 与 4-step compensation workflow | 72 episodes；compatible recovery 12/12；workflow 6/9 完成、3/9 分类停止 |
| [v0.13 Symbolic User](./docs/symbolic-user-v13.md) | Stateful intent、clarification 与 revision-aware authorization | 720 sessions；revision-aware 0 unsafe commit；非直接条件 192/240 SafeSuccess、48 safe abort |
| [v0.14 Evidence Explorer](./docs/evidence-explorer-v14.md) | 离线产品证据页与 fail-closed artifact aggregation | 4 个冻结增量、104 个 source 引用、864 对 traces 全部重验；桌面/移动端 QA 通过 |
| [v0.15 Compact Bundle](./docs/release-bundle-v15.md) | 确定性 ZIP、逐文件 manifest 与 lossless restore | 940 formal + 940 repeat 文件压成 4 个公开 bundle；恢复 1,880 文件后 tree hash 全匹配 |

Compact Artifact Bundle v0.15 将 v0.10–v0.13 的 940 个 formal 文件及其 940 个相同 repeat 文件压成 4 个确定性 ZIP。`manifest.json` 保留每个成员 SHA-256、tree hash、bundle hash 和两个恢复目标；验证从干净目录无损恢复全部 1,880 个文件，四组 formal/repeat tree 仍完全一致。这四个新增量在公开 Git 树中只展示 summary、验证日志、Evidence Explorer 和 4 个 bundle；v0.15 冻结门禁为 173 tests，Python 3.11/3.12 均通过。

这些数字只证明固定合成任务上的 runtime/evaluator 机制，不是 LLM 能力或排行榜成绩。

## 项目结构

```text
src/arl*                 Runtime、环境、evaluator、Resilience 与持久化 Study 实现
scripts/                 可拒绝覆盖的确定性实验入口
tests/                   Unit、integration、validity 与 golden gates
artifacts/               直接 summary/viewer、compact bundles、版本和哈希；完整 trace 本地保留
docs/                    架构、增量合同与完整实验命令
```

完整组件关系、状态合同和数据流见 [Architecture](./docs/architecture.md)。

## 设计边界

- 只使用本地、合成、隔离环境；不连接真实账户、真实业务系统或模型 API。
- 不把文本声明当成功；主要结论来自状态差分、过程约束与副作用检查。
- 所有公开任务和状态数据均为本项目独立编写的合成内容。
- 当前仍是固定 oracle plan；schema adapter 只覆盖两条静态注册映射，Scenario Pack 只覆盖 4 个固定任务/冲突点和一个固定 Travel fallback workflow。
- Symbolic user 是结构化有限状态用户；固定 engagement cohort 仅用于本地可靠性比较，不代表自然语言交互或真实人群行为。
- Parallel Study 使用单进程内 4 个本地线程、逻辑 tick lease 和确定性 coordinator commit；没有分布式主机、wall-clock lease、优先级或通用 DAG。viewer 是内嵌证据的只读 HTML，不是运行控制台。
- Evidence Explorer 只聚合指标、哈希和本地链接；每个冻结 artifact 才是详细证据记录，增量 headline gate 不能横向解释为排行榜。
- 公开仓库使用确定性 bundle 去重完整 trace/workspace；恢复会先校验哈希并拒绝覆盖已有目录，不做增量合并。
- 自动语义合并、动态补偿规划、自然语言用户与模型实验尚未实现。

## Roadmap

1. 扩充更多经人工审查的任务模板和 workflow 类型。
2. 为并行 Study 增加分布式/真实时间 lease 的独立实验合同。
3. 在单独授权和成本预算下接入自然语言/模型 adapter，保持环境与 evaluator 不变。

## 文档导航

- [Architecture](./docs/architecture.md)：组件、状态合同、运行时层级与数据流。
- [Experiment Guide](./docs/running-experiments.md)：测试、实验命令、固定版本和结果校验。
- [Evidence Explorer](./docs/evidence-explorer-v14.md)：离线产品页、聚合规则与 fail-closed 输入门禁。
- [Compact Artifact Bundle](./docs/release-bundle-v15.md)：公开证据包、逐文件校验和无损恢复。
- [Open-source Policy](./docs/open-source.md)：公开内容、发布门禁与项目边界。
- [Third-party Provenance](./THIRD_PARTY.md)：设计影响与独立实现声明。

## 开源与贡献

项目原创代码与文档采用 [MIT License](./LICENSE)。贡献前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，安全与授权边界见 [SECURITY.md](./SECURITY.md)，公开发布门禁见 [docs/open-source.md](./docs/open-source.md)。引用信息见 [CITATION.cff](./CITATION.cff)。
