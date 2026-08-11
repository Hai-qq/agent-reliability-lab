# Open-source release

Agent Reliability Lab 的公开仓库为 <https://github.com/Hai-qq/agent-reliability-lab>，项目原创代码与文档采用 MIT License。

## 对外项目身份

公开仓库展示的是一个独立开发的 **Agent Runtime + Stateful Reliability Benchmark**。核心产品是 `src/arl*` 中的本地状态环境、可靠性 runtime、evaluator、故障注入、task-template/workflow/authorization contracts、validity gates、可恢复并行 Study、fail-closed Evidence Explorer 与可无损恢复的 compact release bundles。

GitHub 首页、项目描述、引用元数据和后续 release/PR 只报告 ARL 自身能够运行和验证的能力。公开产品树只保留代码、产品文档、测试和可核验 artifact；本地规划与调研过程不进入发布内容。

## 发布内容

- 自有 v0.1–v0.3 runtime、环境、evaluator、测试和 digest-only trace，v0.4–v0.9 reliability 增量、v0.10 Study Runtime、v0.11 Parallel Study、v0.12 Scenario Pack、v0.13 Symbolic User、v0.14 Evidence Explorer、v0.15 Compact Bundle，以及候选的 v0.16 Main Study Contract、v0.17 Pilot Preflight、v0.18/v0.19 Model Pilot、v0.20 Main Task Pack、v0.21 Mechanism Ablation、v0.24 24-task Single-Slot Study、v0.27/v0.28 OpenCode Go harness、v0.29 Prospective Holdout 与 v0.30 Independent Reliability Study；
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
- v0.15 已通过合并后的 CI、bundle 恢复与 Pages 部署门禁；完整本地 evidence 未删除，只通过 `.gitignore` 排除。

CI 中的 `actions/checkout` 与 `actions/setup-python` 使用完整 commit SHA 固定，并只授予 `contents: read` 权限。全新 checkout 会先校验并恢复四个 compact bundles，再运行完整测试。Pages workflow 同样固定全部 Action SHA；构建 job 只授予 `contents: read` 与 `pages: read`，部署 job 只授予 `pages: write` 与 GitHub OIDC `id-token: write`。

### v0.16–v0.30 候选增量的本地门禁

v0.16–v0.28 已提交并推送到远端分支 `agent/opencode-go-v028`（commit `df6ec14`）。v0.29 已提交并推送为 commit `1cb56bb`，当前位于 [Draft PR #9](https://github.com/Hai-qq/agent-reliability-lab/pull/9)；它尚未合并或部署。`main` 与 GitHub Pages 仍停留在已发布的 v0.15 Evidence Explorer。v0.30 位于本地开发分支 `agent/independent-replication-v030`，provider 阶段已经完成，但当前尚未提交或推送。测试与 Ruff 结果必须以 v0.30 validation log 的最新重跑记录为准。v0.16 的 12-episode、v0.17 的 48-episode、v0.20 的 144-episode 与 v0.21 的 168-episode formal/repeat 均 summary 和全部 traces 逐字节一致。

v0.18、v0.19、v0.24 与可选 v0.25 runner 使用明确授权的 DeepSeek-V4-Flash API，仅传输本项目合成任务。v0.18 的 144-episode 预检因一个 256-token 截断产生 protocol error，保留为失败证据；v0.19 用 512-token cap 全新运行 144/144 episodes，provider/protocol errors 均为 0。v0.24 在完整 24-task pack 上运行 432/432 episodes，14 项 validity 全部通过，公开候选只保存约 85 KiB compact aggregate、约 42 KiB analysis、README 与 validation log；约 4.0 MiB 完整摘要、432 result、432 digest-only trace 与 study state 留在本地 `.gitignore` 路径，并由公开摘要中的 SHA-256 回链。仓库不发布 key 或 provider request/response 正文。

24-task blueprint 已全部实现为 runnable fixture，scripted validity、逐机制消融和 task-cluster bootstrap 已完成。v0.27 的 OpenCode Go Flash/MiMo 矩阵完成 864/864 episodes，但一次 HTTP 503、一次 local model-protocol rejection 与 MiMo clean qualification failure 使 validity/readiness 为 false；公开候选保留 compact summary 与 validation，不生成 confirmatory analysis。

v0.28 的 Qwen protocol probe、12-job canary 和全新 Flash/Qwen 864-episode matrix 已完成。18 项 infrastructure checks 全过，正式运行只有一次经 bounded retry 恢复的 HTTP 503，0 unrecovered provider/protocol errors。Qwen clean `SafePass@3` 在 R0/R2 为 17/24，未达到预注册的每档 18/24 readiness；因此公开候选包含约 170 KiB compact summary、约 56 KiB 明确标注的 exploratory analysis、README 与 validation log，不包含确认性 `analysis.json`。约 9.2 MB full summary、864 results、864 digest-only traces 与 study state 继续由 `.gitignore` 留在本地。探索性区间不能写成确认性主结论，两个模型共享 OpenCode Go，也不能声明 cross-provider generalization。

v0.29 的公开候选包含 24-task × 3-seed holdout 的 compact preflight、双模型 protocol probe、formal compact summary、README 与 validation log。432/432 scripted episodes、4-call probe 和 36/36 canary 均通过；formal 2,592/2,592 经可核验 resume 完成，但两次 Qwen HTTP 503 未恢复、四个 Qwen episode 超过冻结成本上限，且 Qwen 三 seed clean readiness 未过。基础设施门禁因此为 false，确认性和探索性 builder 都拒绝输出。公开 compact formal summary 约 552 KB；约 27.8 MB full summary、2,592 results、2,592 digest-only traces、study state 与 canary 保留在 `.gitignore` 路径。描述性 point estimate 不能写成成功 replication 或主结论。

v0.30 是 ARL 自有研究问题的全新独立实验，不是上游论文排行榜复现。它冻结 24 个再次独立的 task ID/request、三个新 seed、此前未在 ARL 调用的 `deepseek-v4-pro` 与保留锚点 `deepseek-v4-flash`、预调度预算预留、最多四次 transport retry、12-call 重复 probe、36-episode canary 和 2,592-episode formal 合同。432/432 scripted preflight、12/12 probe calls 与 36/36 canary 均通过；formal 2,592/2,592 完成，5 次 transport retry 全部恢复且没有未恢复 provider/transport/parse error。四个 Pro clean episode 在同一合成取消任务上产生本地 `model_protocol_error`，使 infrastructure validity=false；Flash seed `30229` 的 R2 clean 为 17/24，也未过冻结 readiness。确认性和探索性 builder 因此都拒绝输出。公开候选包含预算校准、compact preflight、probe、约 564 KB formal compact summary、README 与 validation log；约 37 MB full summary、2,592 results、2,592 digest-only traces、study state 和 canary 留在 `.gitignore` 路径。Flash/Pro 的 `+0.716`/`+0.554` 只可写成描述性 point estimate，不能写成成功 replication 或主结论。

## 发布与开发流程

稳定、已验证的增量进入 `main`。后续开发使用 `agent/<description>` 分支和 draft pull request；PR 必须记录运行命令、测试结果、artifact、已知限制以及是否改变安全边界。

当前公开结果只证明固定合成任务上的 runtime/evaluator 机制，不代表 LLM 能力或真实业务系统表现。任何模型/API、真实系统集成或攻击/防御实验都需要单独授权，不能由贡献者默认开启。
