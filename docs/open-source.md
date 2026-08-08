# Open-source release

Agent Reliability Lab 的公开仓库为 <https://github.com/Hai-qq/agent-reliability-lab>，项目原创代码与文档采用 MIT License。

## 对外项目身份

公开仓库展示的是一个独立开发的 **Agent Runtime + Stateful Reliability Benchmark**。核心产品是 `src/arl*` 中的本地状态环境、可靠性 runtime、evaluator、故障注入、task-template/workflow/authorization contracts、validity gates、可恢复并行 Study、fail-closed Evidence Explorer 与可无损恢复的 compact release bundles。

GitHub 首页、项目描述、引用元数据和后续 release/PR 只报告 ARL 自身能够运行和验证的能力。公开产品树只保留代码、产品文档、测试和可核验 artifact；本地规划与调研过程不进入发布内容。

## 发布内容

- 自有 v0.1–v0.3 runtime、环境、evaluator、测试和 digest-only trace，v0.4–v0.9 reliability 增量、v0.10 Study Runtime、v0.11 Parallel Study、v0.12 Scenario Pack、v0.13 Symbolic User、v0.14 Evidence Explorer 与 v0.15 Compact Bundle；
- Python 3.11/3.12 GitHub Actions CI；
- 由 GitHub Pages 托管的只读 [Evidence Explorer](https://hai-qq.github.io/agent-reliability-lab/)，只发布已跟踪的 `artifacts/`、`docs/` 和根跳转页；
- 产品架构、实验指南、贡献规则、第三方 provenance 和安全边界；
- 直接 summary/validation、只读聚合页面和 4 个确定性 bundle，用于核验 README 中的结果数字并按需恢复完整 artifacts。

公开仓库不分发第三方 benchmark 源码、数据、私有 oracle、完整任务载荷或本地研究过程文件。

## 本地发布前门禁

2026-08-08 的公开前审计结果：

- Python 3.12.12：173 tests passed；
- Python 3.11.15：173 tests passed；
- Ruff 0.15.17：check 和 format check 均通过；
- 未发现真实 token、私钥或密码字面量；
- 未发现残留的本机用户主目录绝对路径；
- 没有超过 1 MiB 的单文件；
- v0.10–v0.13 四个冻结输入的 104 个 source 引用、4 对 summary 与 864 对 trace 已由 v0.14 重新核验；v0.14 formal/repeat HTML 与 evidence JSON 逐字节一致；
- Evidence Explorer 桌面与 390×844 移动端渲染、筛选/详情交互、本地证据链接和 console gate 均通过。
- v0.15 将 940 个 formal 与 940 个 byte-identical repeat 文件压为 4 个确定性 ZIP；干净目录恢复 1,880 个文件后 tree manifest 全匹配，所有 bundle 均低于 1 MiB；
- Git status 的待发布文件由约 1,971 个降至 112 个（含 CI 恢复步骤、Pages workflow 与根入口）；完整本地 evidence 未删除，只通过 `.gitignore` 排除。

CI 中的 `actions/checkout` 与 `actions/setup-python` 使用完整 commit SHA 固定，并只授予 `contents: read` 权限。全新 checkout 会先校验并恢复四个 compact bundles，再运行完整测试。Pages workflow 同样固定全部 Action SHA；构建 job 只授予 `contents: read` 与 `pages: read`，部署 job 只授予 `pages: write` 与 GitHub OIDC `id-token: write`。

## 发布与开发流程

稳定、已验证的增量进入 `main`。后续开发使用 `agent/<description>` 分支和 draft pull request；PR 必须记录运行命令、测试结果、artifact、已知限制以及是否改变安全边界。

当前公开结果只证明固定合成任务上的 runtime/evaluator 机制，不代表 LLM 能力或真实业务系统表现。任何模型/API、真实系统集成或攻击/防御实验都需要单独授权，不能由贡献者默认开启。
