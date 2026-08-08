# Third-party provenance

ARL Core v0.1、R2 v0.2、Multi-Task v0.3、Validity Gates v0.4、Retail v0.5、Travel v0.6、Schema Adapter v0.7、Conflict Recovery v0.8、Cross-Domain Resilience v0.9、Study Runtime v0.10、Parallel Study v0.11、Scenario Pack v0.12、Symbolic User v0.13、Evidence Explorer v0.14 与 Compact Bundle v0.15 没有 vendoring 第三方源码、数据或 benchmark trace，也没有 Python runtime dependency。当前实现为独立编写的本地合成原型；仓库根目录的 MIT License 只覆盖本项目原创代码与文档，不改变链接或引用的上游材料许可。

以下公开项目影响了 ARL 的设计术语和评测思路，但不作为运行时依赖：

| 项目 | 设计影响 | 是否复制源码/数据 |
|---|---|---|
| [BrowserGym](https://github.com/ServiceNow/BrowserGym) | reset/step runtime、实验 manifest、可恢复 study 与 trace 组织 | 否 |
| [AppWorld](https://github.com/StonyBrookNLP/appworld) | 确定性状态、最终状态 evaluator、side effect | 否 |
| [ToolSandbox](https://github.com/apple/ToolSandbox) | milestone、minefield、typed tool failure | 否 |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | utility 与 security 分离 | 否 |
| [ABC](https://github.com/uiuc-kang-lab/agentic-benchmarks) | validity gates 与弱基线 | 否 |

ARL 的 runtime、任务、状态数据、故障合同、evaluator、测试和 artifact 均为本项目独立实现。公开仓库不包含上述项目的源码、数据、任务载荷或 benchmark trace，也不生成可迁移的攻击材料。
