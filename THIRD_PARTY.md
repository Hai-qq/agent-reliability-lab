# Third-party provenance

The 0.4.0 stable runtime, CLI, evidence implementation, paired analysis, budget logic,
schedule PRNG, v0.30 design, and smoke bundle use only the Python standard library at
runtime. Optional `dev`, `docs`, `validation`, and `security` extras are development
tools and are resolved in `uv.lock`; they are not imported by the core runtime.
Build/release tooling may generate an SBOM and provenance, but does not vendor those
tools into the wheel.

ARL Core v0.1、R2 v0.2、Multi-Task v0.3、Validity Gates v0.4、Retail v0.5、Travel v0.6、Schema Adapter v0.7、Conflict Recovery v0.8、Cross-Domain Resilience v0.9、Study Runtime v0.10、Parallel Study v0.11、Scenario Pack v0.12、Symbolic User v0.13、Evidence Explorer v0.14、Compact Bundle v0.15、Main Study Contract v0.16、Pilot Preflight v0.17、Model Pilot v0.18/v0.19、Main Task Pack v0.20、Mechanism Ablation v0.21、Single-Slot Study v0.24、Dual-Mode Amendment v0.25、OpenCode Go studies v0.27/v0.28 与 Prospective Holdout v0.29 没有 vendoring 第三方源码、数据、benchmark trace 或模型输出正文，也没有第三方 Python runtime dependency。当前实现为独立编写的本地合成原型；仓库根目录的 MIT License 只覆盖本项目原创代码与文档，不改变链接、服务或引用材料的许可。

以下公开项目影响了 ARL 的设计术语和评测思路，但不作为运行时依赖：

| 项目 | 设计影响 | 是否复制源码/数据 |
|---|---|---|
| [BrowserGym](https://github.com/ServiceNow/BrowserGym) | reset/step runtime、实验 manifest、可恢复 study 与 trace 组织 | 否 |
| [AppWorld](https://github.com/StonyBrookNLP/appworld) | 确定性状态、最终状态 evaluator、side effect | 否 |
| [ToolSandbox](https://github.com/apple/ToolSandbox) | milestone、minefield、typed tool failure | 否 |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | utility 与 security 分离 | 否 |
| [ABC](https://github.com/uiuc-kang-lab/agentic-benchmarks) | validity gates 与弱基线 | 否 |

v0.18、v0.19、v0.24 与 v0.25 通过标准库 HTTP client 调用 DeepSeek 的 OpenAI-compatible Chat Completions API；这是一项经单独授权、可选的外部服务，不是 vendored SDK 或核心运行时依赖。实现依据官方 [Chat Completion API](https://api-docs.deepseek.com/api/create-chat-completion)、[Tool Calls](https://api-docs.deepseek.com/guides/tool_calls)、[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode) 和 [Pricing](https://api-docs.deepseek.com/quick_start/pricing) 文档，精确绑定 `deepseek-v4-flash`：v0.24 显式关闭 thinking，v0.25 则为第二配置启用 thinking 并固定 `reasoning_effort=high`。公开 artifact 只记录 model ID、system fingerprint、usage、latency、cost estimate 与 request/response digest；不分发 credential 或 provider 内容。

v0.27–v0.29 通过同一标准库 client 调用 OpenCode Go 的 OpenAI-compatible Chat Completions endpoint，并通过 authenticated models endpoint 核验当日 catalog；同样不引入 SDK 或核心依赖。实现依据官方 [OpenCode Go documentation](https://dev.opencode.ai/docs/go/) 和 [provider configuration](https://opencode.ai/docs/providers/)。v0.27 精确绑定 Flash/MiMo；v0.28 在观察 Qwen benchmark outcome 前改为全新的 Flash/Qwen matrix，并预注册 bounded transport retry。v0.28 完成后因 Qwen clean readiness 未过而拒绝确认性 analysis，另行发布的 bootstrap 明确标为 exploratory。v0.29 保持相同 Flash/Qwen binding 与 transport，新增项目自有 holdout task/data seeds；其 probe、canary 和 2,592-episode formal 已完成，但两次未恢复 503、四个成本超限与 Qwen readiness 失败使 infrastructure validity=false，两种 analysis 均拒绝输出。两个 model slot 共享 OpenCode Go gateway，因此只允许进行 gateway 内模型比较，不声明 cross-provider generalization。公开 artifact 仍只保存 binding、usage、latency、typed error 与 request/response digest。

ARL 的 runtime、任务、状态数据、故障合同、evaluator、测试和 artifact 均为本项目独立实现。公开仓库不包含上述项目的源码、数据、任务载荷或 benchmark trace，也不生成可迁移的攻击材料。
