# Third-party provenance

ARL Core v0.1、R2 v0.2、Multi-Task v0.3、Validity Gates v0.4、Retail v0.5 与 Travel v0.6 没有 vendoring 第三方源码、数据或 benchmark trace，也没有 Python runtime dependency。当前实现为独立编写的本地合成原型；仓库根目录的 MIT License 只覆盖本项目原创代码与文档，不改变链接或引用的上游材料许可。

设计概念来自本项目已审计的上游工作：

| 上游 | 本实现吸收的概念 | 是否复制源码/数据 |
|---|---|---|
| [BrowserGym](https://github.com/ServiceNow/BrowserGym) | reset/step runtime、实验 manifest、trace | 否 |
| [AppWorld](https://github.com/StonyBrookNLP/appworld) | 确定性状态、最终状态 evaluator、side effect | 否 |
| [ToolSandbox](https://github.com/apple/ToolSandbox) | milestone、minefield、typed tool failure | 否 |
| [AgentDojo](https://github.com/ethz-spylab/agentdojo) | utility 与 security 分离 | 否 |
| [ABC](https://github.com/uiuc-kang-lab/agentic-benchmarks) | validity gates 与弱基线 | 否 |

各上游复现实验、固定提交和许可边界仍以 `reproduction/` 下的独立报告为准。ARL 当前只含一次 Workspace 预提交 timeout、Workspace/Retail/Travel 共五个提交后 timeout site，以及一条首选航班不可用后取消可退款酒店的受控恢复路径；不复用或生成上游攻击材料。
