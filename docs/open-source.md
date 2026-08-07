# Open-source release

Agent Reliability Lab 的公开仓库为 <https://github.com/Hai-qq/agent-reliability-lab>，项目原创代码与文档采用 MIT License。

## 对外项目身份

公开仓库展示的是一个独立开发的 **Agent Runtime + Stateful Reliability Benchmark**。核心产品是 `src/arl*` 中的本地状态环境、可靠性 runtime、evaluator、故障注入、schema adapter 与 validity gates。

GitHub 首页、项目描述、引用元数据和后续 release/PR 只报告 ARL 自身能够运行和验证的能力。公开产品树只保留代码、产品文档、测试和可核验 artifact；本地规划与调研过程不进入发布内容。

## 发布内容

- 自有 v0.1–v0.3 runtime、环境、evaluator、测试和 digest-only trace，v0.4 validity gates、v0.5 Retail、v0.6 Travel、v0.7 Schema Adapter、v0.8 Conflict Recovery 与 v0.9 Cross-Domain Resilience；
- Python 3.11/3.12 GitHub Actions CI；
- 产品架构、实验指南、贡献规则、第三方 provenance 和安全边界；
- 小型正式/repeat artifacts，用于核验 README 中的结果数字。

公开仓库不分发第三方 benchmark 源码、数据、私有 oracle、完整任务载荷或本地研究过程文件。

## 本地发布前门禁

2026-08-07 的公开前审计结果：

- Python 3.12.12：100 tests passed；
- Python 3.11.15：100 tests passed；
- Ruff 0.15.17：check 和 format check 均通过；
- 未发现真实 token、私钥或密码字面量；
- 未发现残留的本机用户主目录绝对路径；
- 没有超过 1 MiB 的单文件；
- v0.1–v0.8 八份已记录源码 manifest 全部匹配，v0.9 使用覆盖 20 个实际依赖文件的独立 manifest；正式与 repeat summary 及 36/36 traces 逐字节一致。

CI 中的 `actions/checkout` 与 `actions/setup-python` 使用完整 commit SHA 固定，并只授予 `contents: read` 权限。

## 发布与开发流程

稳定、已验证的增量进入 `main`。后续开发使用 `agent/<description>` 分支和 draft pull request；PR 必须记录运行命令、测试结果、artifact、已知限制以及是否改变安全边界。

当前公开结果只证明固定合成任务上的 runtime/evaluator 机制，不代表 LLM 能力或真实业务系统表现。任何模型/API、真实系统集成或攻击/防御实验都需要单独授权，不能由贡献者默认开启。
