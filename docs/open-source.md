# Open-source release

Agent Reliability Lab 的公开仓库为 <https://github.com/Hai-qq/agent-reliability-lab>，项目原创代码与文档采用 MIT License。

## 对外项目身份

公开仓库展示的是一个独立开发的 **Agent Runtime + Stateful Reliability Benchmark**，而不是论文复现合集。核心产品是 `src/arl*` 中的本地状态环境、可靠性 runtime、evaluator、故障注入与 validity gates；`reproduction/` 和根目录的调研材料只用于说明设计来源、验证上游机制并保留研究可追溯性。

ARL 没有 vendoring 上游 benchmark 源码、数据或 trace，也不把上游结果冒充为本项目能力。GitHub 首页、项目描述、引用元数据和后续 release/PR 应始终先说明 ARL 自身能运行和验证什么，再链接研究依据。

## 发布内容

- 自有 v0.1–v0.3 runtime、环境、evaluator、测试和 digest-only trace，v0.4 validity gates、v0.5 Retail、v0.6 Travel 与 v0.7 Schema Adapter；
- Python 3.11/3.12 GitHub Actions CI；
- 贡献规则、第三方 provenance 和安全边界。

作为支持性研究证据，仓库同时保留 AppWorld、ToolSandbox、ABC、AgentDojo、BrowserGym 的本地最小复现脚本、聚合结果与固定版本说明，以及论文证据矩阵、领域综述、项目蓝图和 BibTeX 索引。这些内容不进入 ARL 的产品能力计数。

仓库不再分发上游 benchmark 源码、数据、私有 oracle 或完整任务载荷。三份上游测试日志中的本机绝对路径已统一替换为 `$ARL_WORKSPACE`；测试名称、版本、结果与告警内容未改变。

## 本地发布前门禁

2026-08-07 的公开前审计结果：

- Python 3.12.12：72 tests passed；
- Python 3.11.15：72 tests passed；
- Ruff 0.15.17：check 和 format check 均通过；
- 未发现真实 token、私钥或密码字面量；
- 未发现残留的本机用户主目录绝对路径；
- 没有超过 1 MiB 的单文件；
- v0.1–v0.6 六份已记录源码 manifest 全部匹配，v0.7 使用覆盖 13 个实际依赖文件的独立 manifest。

CI 中的 `actions/checkout` 与 `actions/setup-python` 使用完整 commit SHA 固定，并只授予 `contents: read` 权限。

## 发布与开发流程

稳定、已验证的增量进入 `main`。后续开发使用 `agent/<description>` 分支和 draft pull request；PR 必须记录运行命令、测试结果、artifact、已知限制以及是否改变安全边界。

当前公开结果只证明固定合成任务上的 runtime/evaluator 机制，不是 LLM、产品系统或论文排行榜成绩。任何模型/API、真实系统集成或攻击/防御实验都需要单独授权，不能由贡献者默认开启。
