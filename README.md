# Agent Reliability Lab：论文复现与可靠性 Runtime 原型

[![CI](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

> 调研快照：2026-08-06；复现状态更新：2026-08-07

## 一句话结论

最值得做的不是再封装一个“会调用工具的聊天 Agent”，而是做一个**可复现、可注入故障、可验证状态、能度量稳定成功率的 Agent Runtime + Stateful Benchmark**。它同时对应 JD 中的 Agent Environment、Runtime、Infra、数据、Benchmark、用户体验与效果定义。

## 快速开始

```bash
git clone https://github.com/Hai-qq/agent-reliability-lab.git
cd agent-reliability-lab

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest discover -s tests -p 'test_*.py' -v
```

核心 runtime 只使用 Python 标准库，需要 Python 3.11 或更高版本。完整实验命令见 [复现说明](./docs/reproduction.md)。项目只允许官方 benchmark 的本地、合成、隔离复现；不连接真实账户、真实网络目标或模型 API。贡献要求见 [CONTRIBUTING.md](./CONTRIBUTING.md)，安全边界见 [SECURITY.md](./SECURITY.md)。项目原创代码与文档采用 [MIT License](./LICENSE)，上游材料仍遵循各自许可，详见 [THIRD_PARTY.md](./THIRD_PARTY.md)。

## 交付物

1. [01_30篇论文证据矩阵.csv](./01_30篇论文证据矩阵.csv)：30 篇论文逐篇记录，含分组、贡献、代码、局限与复现优先级。
2. [02_领域综述.md](./02_领域综述.md)：从 Agent 运行时、状态化环境、可靠性评测到基准有效性的中文综述。
3. [03_精选5篇与复现计划.md](./03_精选5篇与复现计划.md)：精选 5 篇的筛选依据、代码核验结果、逐篇最小复现实验和验收条件。
4. [04_完整项目蓝图.md](./04_完整项目蓝图.md)：可直接开工的 Agent Reliability Lab 项目定义、架构、任务集、指标、排期和简历表达。
5. [references.bib](./references.bib)：30 篇论文的 BibTeX 索引。
6. [AppWorld evaluator 复现](./reproduction/appworld/RESULTS.md)：5 个 dev 任务、4 组对照、状态差分与官方测试证据。
7. [ToolSandbox evaluator 复现](./reproduction/toolsandbox/RESULTS.md)：2 个官方 scenario、5 条确定性轨迹、多路径、状态依赖与 minefield 证据。
8. [ABC × τ-bench 有效性复现](./reproduction/abc/RESULTS.md)：历史 evaluator 的 165 个任务、两类弱基线与 issue-1 补丁回归。
9. [AgentDojo utility evaluator 复现](./reproduction/agentdojo/RESULTS.md)：32 个官方测试、27 个固定合成 episode 与 library logger 兼容性探针。
10. [BrowserGym runtime/harness 复现](./reproduction/browsergym/RESULTS.md)：15 个官方本地测试、9 个固定 MiniWoB job、受控错误恢复与中断续跑证据。
11. [ARL Core MVP v0.1](./docs/core-mvp.md)：确定性 Workspace、状态 evaluator、event journal、R0/R1 runtime 和首组 clean/fault 配对实验。
12. [ARL R2 可靠性增量 v0.2](./docs/r2-reliability.md)：原子幂等记录、timeout-after-commit、查询确认及 R1/R2 配对实验。
13. [Workspace Multi-Task v0.3](./docs/multitask-v03.md)：第二任务、通知/邀请幂等、allowed change、evaluator mutation 与 24-episode 配对实验。
14. [Workspace Validity Gates v0.4](./docs/validity-v04.md)：random-valid-tool、dump-state、golden-trace 与 mutation 门禁。
15. [Retail Minimal v0.5](./docs/retail-v05.md)：第二业务域、优惠后下单、政策内部分退款、事务回滚与 24-episode 配对实验。
16. [THIRD_PARTY.md](./THIRD_PARTY.md)：ARL Core 的概念来源、未复制上游源码/数据的 provenance 说明。
17. [Open-source release](./docs/open-source.md)：公开仓库范围、发布前门禁、CI 固定方式与后续 PR 流程。

## 精选 5 篇

| 论文 | 项目吸收的核心机制 |
|---|---|
| BrowserGym Ecosystem | 标准化浏览器 POMDP 接口、实验编排、轨迹与版本记录 |
| AppWorld | 可控数据库世界、状态差分、目标状态与副作用联合评测 |
| ToolSandbox | 有状态工具、受约束用户模拟器、里程碑与雷区评测 |
| AgentDojo | 动态攻击/故障注入、效用与安全双目标评测 |
| ABC（Agentic Benchmark Checklist） | 任务有效性、结果有效性、报告透明度与反作弊审计 |

ReAct 仍作为基础 Agent baseline；τ-bench 的用户—策略—工具结构与 `pass^k` 指标仍会吸收。但旧版 τ-bench 的评分器已被后续审计发现存在明显可钻空子，因此不把它列为五个实现支柱。

## 当前完成边界

- 已核验 30 篇论文的官方论文页或 arXiv 页面。
- 已核验 26 个相关官方代码仓库可访问。
- 已下载并精读 6 篇核心原文；已浅克隆 7 个关键仓库并固定提交号。
- 已形成复现命令、验收条件和工程蓝图。
- 已安装 AppWorld Engine/minimal 数据并通过上游门禁：1838 tests passed、2 skipped，147/147 tasks passed。
- 已完成 AppWorld evaluator 最小复现：oracle 5/5；只声明成功、无关新增、无关删除均为 0/5；两次完整运行结果一致。
- 已完成 ToolSandbox evaluator 最小复现：两条合法顺序均为 1.0，缺少前置状态为 0.5，安全拒绝为 1.0，minefield 违规清零；两次运行一致。
- 已完成 ABC × 历史 τ-bench evaluator 审计：原始 `no_op` 为 Airline 19/50、Retail 7/115；`dump_all` 为 20/50、11/115；issue-1 补丁只封住 Airline 的 `no_op`，未覆盖 Retail 与剩余输出泄漏问题。
- 已完成 AgentDojo utility evaluator 最小复现：官方测试 32 passed；3 个固定合成任务 × 3 条本地轨迹 × 3 次重复中，oracle 9/9、空响应 0/9、claim-only 6/9；确认直接 library helper 的 `NullLogger` 兼容性限制。
- 已完成 BrowserGym runtime/harness 最小复现：官方本地测试 15 passed；3 个 MiniWoB 任务 × 3 seeds 为 9/9；一次 locator timeout 后恢复成功；4/9 主动中断后只续跑剩余 5 个，既有记录哈希不变。
- 已完成 ARL Core 首个可运行增量：1 个 Workspace 任务 × 3 seeds × clean/fault × R0/R1，共 12 episodes；R0 clean 3/3、fault 0/3，R1 clean/fault 均为 3/3；10 tests passed，第二次运行的 summary 与 12 条 trace 均逐字节一致。
- 已完成 R2 可靠性增量：对首次日历写入注入一次提交后 timeout；R1 clean 3/3、fault 0/3，R2 clean/fault 均为 3/3。R2 的 3 个 fault episode 各做 1 次查询确认、0 次盲重试；幂等重放保持 1 条事件，复用同 key 的不同请求返回类型化冲突。正式与 repeat 的 summary、12/12 traces 均逐字节一致。
- 已完成 Workspace Multi-Task v0.3：新增“会议改期并通知”任务，把幂等扩到邀请、改期通知、更新时间和请求关闭；2 tasks × 3 seeds × clean/fault × R1/R2 共 24 episodes，R1 clean/fault 为 6/6、0/6，R2 为 6/6、6/6；正式与 repeat 的 summary、24/24 traces 均逐字节一致。
- 已通过 allowed metadata change 与 5 个 evaluator mutation；通知/邀请幂等重放不重复写，批量通知失败完整回滚。
- 已完成 Workspace Validity Gates v0.4：120 个 random-valid-tool rollout 的 TaskSuccess 为 11/120、SafeSuccess 为 6/120；12/12 dump-state case 被拒绝；4/4 golden trace 通过 digest/schema/chain 校验，3 类 trace mutation 均被检出；正式与 repeat summary 逐字节一致。
- 已完成 Retail Minimal v0.5：新增优惠后最优下单与政策内部分退款；2 tasks × 3 seeds × clean/fault × R1/R2 共 24 episodes，R1 clean/fault 为 6/6、0/6，R2 为 6/6、6/6；order/refund 幂等重放、事务回滚、政策拒绝、8 个 evaluator mutation、reset/snapshot 与 digest-only trace 门禁均通过，正式与 repeat summary、24/24 traces 逐字节一致。
- **尚未**实现 Travel、schema adapter、一般冲突恢复、补偿、用户模拟器、scheduler/trace viewer，也未运行 LLM Agent、AgentLab 完整 Study、AgentDojo attack/defense 或论文排行榜实验。当前结果是离线机制证据，不冒充模型成绩。

## 质量检查

- CSV：30 行、30 个唯一标题、30 个论文链接；
- BibTeX：30 个条目，Pandoc/Citeproc 解析通过；
- 链接：57 个唯一论文/代码/数据 URL 实际请求均返回 HTTP 200；
- 代码：AgentDojo 固定提交的完整官方测试 32 passed；BrowserGym 安全选取的官方本地测试 15 passed；ARL 当前 49 tests passed；五个上游复现和自有 v0.1–v0.5 增量均保存版本、断言与机器结果；
- 文档：相对链接均能解析，无缺失交付文件。

语法编译仅验证源码可被当前 Python 解析，不替代依赖安装、单元测试或端到端复现。

## 推荐下一步

下一步按 [04_完整项目蓝图.md](./04_完整项目蓝图.md) 进入 Travel 最小域：先实现两个本地状态任务及 oracle/evaluator，再接 clean/fault runtime 配对。首次面向模型的展示仍应在单独授权和成本预算后进行。
