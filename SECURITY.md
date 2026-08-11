# Security policy

## Supported scope

Agent Reliability Lab 是本地、合成、隔离的研究原型。benchmark 不连接真实账户或真实业务系统，也不授权对第三方系统进行扫描、凭据获取或对抗操作。v0.18、v0.19、v0.24/v0.25 提供可选的 DeepSeek runner；v0.27–v0.29 提供可选的 OpenCode Go runner。只有在用户明确授权并分别提供环境变量 `DEEPSEEK_API_KEY` 或 `OPENCODE_GO_API_KEY` 时才调用 provider，发送内容限本项目固定合成任务与结构化工具合同。

模型 runner 不接受命令行 key，不把 credential、原始 provider request 或 response 写入 summary/trace；公开证据只含 digest 与类型化资源元数据。每次 provider 请求前按最大 response cap 预留硬预算，并将完整 result/trace 树保留在本地忽略路径。v0.28/v0.29 把 logical model calls 与 physical network attempts 分开计数，只对预注册 transport 类别做最多两次 retry；任何未恢复错误或单 episode 预算超限都会使 study 无效，不能通过删除记录或重跑个别 cell 改写处置。DeepSeek 和 OpenCode Go 都是外部数据处理方，因此不得把真实用户内容、账户数据、凭据或第三方私有数据代入 runner。

如果问题涉及仓库代码本身的漏洞，请使用 GitHub 的 **Private vulnerability reporting**，不要在公开 issue 中披露敏感细节。

## Out of scope

- 对真实网站、账户、网络目标或第三方服务进行测试；
- 提交真实凭据、用户数据或可识别个人的信息；
- 把本项目的合成故障注入机制迁移为面向真实系统的攻击材料；
- 第三方项目自身的问题。此类问题应按对应项目的安全政策报告。

报告中请提供最小本地复现、受影响版本、预期行为和实际行为。不要附带真实秘密或第三方数据。
