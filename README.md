# Agent Reliability Lab

**Deterministic Agent Runtime × Stateful Reliability Benchmark**

[![CI](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml/badge.svg)](https://github.com/Hai-qq/agent-reliability-lab/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](./pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Agent Reliability Lab（ARL）是一个**原创开源的 Agent 可靠性工程项目**。它在完全本地、合成、可重置的 SQLite 产品世界中，为工具型 Agent 提供类型化 Runtime、确定性故障注入、状态级 evaluator 和可复现实验门禁。

ARL 关注的不是“Agent 有没有说自己完成了任务”，而是：最终状态是否正确、是否产生越权或重复副作用、遇到模糊提交结果时能否安全恢复，以及相同实验能否稳定重现。

> 核心 runtime、scripted benchmark 与 validity gates 无需模型、API 或真实账户即可完整运行；可选的模型 pilot 只把本项目合成任务发送给经单独授权的 provider，并保持 credential 与原始模型内容不落盘。

**产品证据入口：** [在线 Evidence Explorer（v0.10–v0.13）](https://hai-qq.github.io/agent-reliability-lab/) · [Flash + Qwen 864-episode summary（v0.28）](./artifacts/opencode_go_flash_qwen_v28/summary.json) · [明确标注的探索性 bootstrap](./artifacts/opencode_go_flash_qwen_v28/exploratory-analysis.json) · [v0.29 三种子 holdout summary](./artifacts/opencode_go_holdout_v29/summary.json)。每项结果均回链到冻结 JSON、源码/trace manifest 和实验合同；v0.28 未通过 readiness，v0.29 完成全部 2,592 episodes 但基础设施有效性与 Qwen readiness 均失败，所以二者都没有新的确认性主结论。

## 核心能力

| 模块 | 当前实现 |
|---|---|
| Stateful environments | Workspace、Retail、Travel 三个合成业务域、24 个可运行任务、确定性逻辑时间、reset/snapshot/state hash |
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
| Main-study contract | 24-task/6-fault blueprint、R0/R1/R2 公平性合同、模型绑定门禁与 12-episode 无模型 smoke |
| Pilot preflight | 8 个可运行任务、6 类故障、统一 Runtime、evaluator mutation 与 48-episode 零模型门禁 |
| Model pilot | DeepSeek-V4-Flash structured tool backend、环境变量凭据、有界 token/cost、可恢复 144-job study、digest-only provider audit 与 `SafePass@3` 聚合 |
| Main task pack | 24 个可运行 task card、每域 8 个任务、每故障族 4 个任务、状态 evaluator 与 144-episode scripted validity gate |
| Mechanism ablation | R2 baseline + 6 个 leave-one-out 变体、168 episodes、相同 policy digest 与逐机制目标任务检验 |
| Single-slot model study | DeepSeek-V4-Flash × 完整 24-task pack、432 episodes、硬预算、可恢复 checkpoint 与配对 task-cluster bootstrap |
| OpenCode two-model harness | 同一 OpenCode Go gateway 下的 Flash/Qwen 精确绑定、12-job canary、864-episode 完整矩阵、有界 transport retry、digest-only audit 与联合 task bootstrap |
| Prospective holdout | 24 个新 task ID/request、3 个冻结数据 seed、逐 seed readiness、432-episode 零模型门禁与已完成但 fail-closed 无效的 2,592-episode 矩阵 |

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

运行最新的 v0.20 scripted preflight（24 个本地合成任务、6 类故障，不调用模型）：

```bash
ARL_PREFLIGHT=/tmp/arl-main-pack-v020

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_main_pack_preflight.py \
  --output "$ARL_PREFLIGHT/summary.json" \
  --traces-dir "$ARL_PREFLIGHT/traces"
```

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

经单独授权后运行 24-task DeepSeek Flash single-slot study（密钥只从环境变量读取，输出路径必须不存在）：

```bash
ARL_MODEL_STUDY=/tmp/arl-deepseek-flash-v024

env DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:?set in the current shell}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/run_main_single_slot.py \
    --workspace "$ARL_MODEL_STUDY/study" \
    --summary "$ARL_MODEL_STUDY/full-summary.json"

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/compact_model_pilot_summary.py \
    --input "$ARL_MODEL_STUDY/full-summary.json" \
    --output "$ARL_MODEL_STUDY/summary.json"

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/build_main_single_slot_analysis.py \
    --input "$ARL_MODEL_STUDY/full-summary.json" \
    --output "$ARL_MODEL_STUDY/analysis.json" \
    --iterations 10000 --seed 20260808
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
| [v0.16 Main Study Contract](./docs/main-study-v16.md) | 24-task blueprint、统一三档 Runtime 与 fail-closed 模型门禁 | 12 scripted episodes；R0/R1 fault 0/2，R2 fault 2/2；0 model/network calls；18 planned tasks 未冒充实现 |
| [v0.17 Pilot Preflight](./docs/pilot-preflight-v17.md) | 8 runnable tasks、6 fault families 与 evaluator validity | 48 scripted episodes；clean 均 8/8；fault R0 0/8、R1 1/8、R2 8/8；0 model/network calls |
| [v0.18 Model Pilot Preflight](./docs/model-pilot-v19.md#v018-失败的预检证据) | DeepSeek-V4-Flash、256-token response cap、3 trials | 144/144 完成，但 1 次截断导致 protocol error；validity fail，结果不进入主结论 |
| [v0.19 DeepSeek Flash Pilot](./docs/model-pilot-v19.md) | 同一 8-task 矩阵、512-token cap、非思考模式 | 144/144 完成；R1/R2 fault `SafePass@3` 为 1/8 与 8/8；472 calls、466,143 tokens、0 provider/protocol errors |
| [v0.20 Main Task Pack](./artifacts/main_pack_preflight_v20/README.md) | 24 runnable tasks、6 fault families、scripted R0/R1/R2 gate | 144 episodes；clean 均 24/24；fault R0/R1/R2 为 0/24、4/24、24/24；formal/repeat byte-identical |
| [v0.21 Mechanism Ablation](./artifacts/main_pack_ablation_v21/README.md) | R2 baseline + 6 leave-one-out runtime variants | 168 episodes；baseline 24/24；每个单机制移除均降为 20/24，且只丢失预期目标任务；formal/repeat byte-identical |
| [v0.24 Single-Slot Study](./docs/main-single-slot-v24.md) | DeepSeek-V4-Flash、完整 24-task pack、3 trials、非思考模式 | 432/432；R1/R2 matched fault recovery 为 5/18 与 17/18；差值 `+0.667`，bootstrap 95% CI `[0.444, 0.882]`；0 provider/protocol errors |
| [v0.27 OpenCode Two-Model Run](./docs/opencode-go-main-v27.md) | Flash + MiMo、完整 864-episode 矩阵与 fail-closed analysis gate | 864/864 完成，但 1 次 HTTP 503、1 次协议错误且 MiMo clean qualification 未通过；整体无效，只保留探索性失败证据 |
| [v0.28 Flash + Qwen Main](./docs/opencode-go-main-v28.md) | 两个精确 model ID、24 tasks、R0/R1/R2、clean/fault、3 trials | 864/864；18/18 infrastructure checks 通过，0 unrecovered errors；Flash/Qwen 的 R2−R1 fault-recovery 增量为 `+0.667`/`+0.660`，但 Qwen clean readiness 未过，因此只发布探索性 CI，不声明确认性主结论 |
| [v0.29 Prospective Holdout](./docs/opencode-go-holdout-v29.md) | 24 个新 task ID/request、3 seeds、逐 seed readiness 与 2,592-episode 合同 | probe 与 36-job canary 通过；formal 2,592/2,592 完成，但 2 次未恢复 503、4 个成本超限和 Qwen readiness 失败使 analysis 全部 fail closed |

Compact Artifact Bundle v0.15 将 v0.10–v0.13 的 940 个 formal 文件及其 940 个相同 repeat 文件压成 4 个确定性 ZIP。`manifest.json` 保留每个成员 SHA-256、tree hash、bundle hash 和两个恢复目标；验证从干净目录无损恢复全部 1,880 个文件，四组 formal/repeat tree 仍完全一致。这四个新增量在公开 Git 树中只展示 summary、验证日志、Evidence Explorer 和 4 个 bundle；v0.15 冻结门禁为 173 tests，Python 3.11/3.12 均通过。

这些数字只证明固定合成任务上的 runtime/evaluator 机制与指定模型绑定的结果，不是通用 LLM 能力或排行榜成绩。24-task fixture、机制消融、v0.24 单模型矩阵和 v0.28 双模型矩阵均已完成。v0.28 的基础设施证据有效，且探索性配对区间显示两个模型的 R2 fault recovery 均高于 R1；但 Qwen readiness 未过，所以确认性分析按设计拒绝输出。v0.29 以新任务和三种子完成独立复核，Flash 的三 seed clean readiness 均通过，描述性 R2−R1 fault-recovery point estimate 为 `+0.690`；Qwen 对应 point estimate 为 `+0.685`，但三 seed readiness 失败。更重要的是，两次未恢复 HTTP 503 和四个单 episode 成本超限使整个 v0.29 infrastructure validity 为 false，因此 confirmatory 与 exploratory builder 均拒绝输出，上述 point estimate 不能作为推断结论。当前分支的完整测试与 Ruff 状态以本分支最新 validation log 为准。

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

- benchmark 环境始终为本地、合成、隔离 SQLite 世界；不连接真实账户、真实业务系统或网络目标。可选 model runner 仅在明确授权后调用 DeepSeek 或 OpenCode Go，发送内容限本项目合成任务与结构化工具合同。
- 不把文本声明当成功；主要结论来自状态差分、过程约束与副作用检查。
- 所有公开任务和状态数据均为本项目独立编写的合成内容。
- v0.20 preflight 使用 deterministic reactive oracle；v0.24 的 `arl_mainmodel` 将相同 24-task 结构化动作边界接入 DeepSeek-V4-Flash。Runtime 仍逐动作串行执行，provider 的 parallel tool calls 会先缓冲再受相同白名单、硬预算与 evaluator 约束。
- Symbolic user 是结构化有限状态用户；固定 engagement cohort 仅用于本地可靠性比较，不代表自然语言交互或真实人群行为。
- Parallel Study 使用单进程内 4 个本地线程、逻辑 tick lease 和确定性 coordinator commit；没有分布式主机、wall-clock lease、优先级或通用 DAG。viewer 是内嵌证据的只读 HTML，不是运行控制台。
- Evidence Explorer 只聚合指标、哈希和本地链接；每个冻结 artifact 才是详细证据记录，增量 headline gate 不能横向解释为排行榜。
- 公开仓库使用确定性 bundle 去重完整 trace/workspace；恢复会先校验哈希并拒绝覆盖已有目录，不做增量合并。
- 自动语义合并、动态补偿规划和自然语言用户尚未实现。模型 provider 不提供不可变 serving-weight hash 或可执行的统一 sampling seed，因此模型结果不能声明为逐字节确定性复现；同一 OpenCode Go gateway 的双模型结果也不能外推为跨 provider 泛化。

## Roadmap

1. 在任何新模型调用前冻结新的独立 replication：保留 v0.29 的失败处置，先用 canary 校准可行但不宽松的成本上限，并加入 provider availability gate；不得选择性重跑 v0.29 失败 cell。
2. 增加独立 provider gateway 的前瞻性复核；当前 Flash/Qwen 共享 OpenCode Go，只能支持 gateway 内的模型比较。
3. 将 v0.24、v0.27、v0.28 和 v0.29 的 public-safe aggregate 纳入下一版 Evidence Explorer，明确分栏显示有效、仅探索、基础设施无效与未完成状态。

## 文档导航

- [Architecture](./docs/architecture.md)：组件、状态合同、运行时层级与数据流。
- [Experiment Guide](./docs/running-experiments.md)：测试、实验命令、固定版本和结果校验。
- [Evidence Explorer](./docs/evidence-explorer-v14.md)：离线产品页、聚合规则与 fail-closed 输入门禁。
- [Compact Artifact Bundle](./docs/release-bundle-v15.md)：公开证据包、逐文件校验和无损恢复。
- [Main Study Contract](./docs/main-study-v16.md)：原创研究假设、24-task blueprint、模型门禁与无模型 smoke。
- [Pilot Preflight](./docs/pilot-preflight-v17.md)：8-task/6-fault 可运行门禁、结果与未完成项。
- [DeepSeek Flash Model Pilot](./docs/model-pilot-v19.md)：144-episode 实测、失败预检、token/cost、有效性与主实验剩余门禁。
- [24-Task DeepSeek Flash Study](./docs/main-single-slot-v24.md)：432-episode 单模型完整矩阵、硬预算、资源证据与配对 task-cluster bootstrap。
- [DeepSeek Flash Dual-Mode Amendment（历史）](./docs/dual-mode-main-v26.md)：未完成的同一模型双推理配置修订及其解释边界。
- [OpenCode Go Two-Model v0.27](./docs/opencode-go-main-v27.md)：完整但无效的 864-episode 运行、失败门禁与证据处置。
- [OpenCode Go Flash + Qwen v0.28](./docs/opencode-go-main-v28.md)：全新双模型合同、预算、transport retry、canary 与正式矩阵命令。
- [Prospective Holdout v0.29](./docs/opencode-go-holdout-v29.md)：新任务、三种子、完整 2,592-job 运行、失败门禁、恢复审计与证据处置。
- [Open-source Policy](./docs/open-source.md)：公开内容、发布门禁与项目边界。
- [Third-party Provenance](./THIRD_PARTY.md)：设计影响与独立实现声明。

## 开源与贡献

项目原创代码与文档采用 [MIT License](./LICENSE)。贡献前请阅读 [CONTRIBUTING.md](./CONTRIBUTING.md)，安全与授权边界见 [SECURITY.md](./SECURITY.md)，公开发布门禁见 [docs/open-source.md](./docs/open-source.md)。引用信息见 [CITATION.cff](./CITATION.cff)。
