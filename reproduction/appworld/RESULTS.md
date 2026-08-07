# AppWorld evaluator 最小复现报告

> 运行日期：2026-08-06；本报告复现的是 evaluator 机制，不是论文排行榜分数。

## 结论

在固定的 5 个 AppWorld dev 任务上：

| 轨迹变体 | 任务成功数 | evaluator 子检查通过数 | 结论 |
|---|---:|---:|---|
| 官方 oracle | **5/5** | **34/34** | 正确目标状态全部通过 |
| `no_op`：只声明成功 | **0/5** | 8/34 | evaluator 不相信 Agent 的完成声明 |
| `collateral_add`：额外新增无关 Note | **0/5** | 26/34 | 5 次真实副作用全部被拒绝 |
| `collateral_delete`：额外删除无关 Note | **0/5** | 26/34 | 5 次真实副作用全部被拒绝 |

这组结果支持将 AppWorld 的 `snapshot + state diff + goal/collateral checks` 吸收到 Agent Reliability Lab。子检查通过数仅用于诊断；一个任务只有在其全部检查通过时才计为成功，不能把 26/34 解读成 76.5% benchmark 成绩。

## 固定环境与上游门禁

- AppWorld commit：`a072b7a86e7c1d5b1d7175659d750ebb9b79f10a`
- AppWorld version：`0.2.0.dev0`
- Python：`3.11.15`
- 平台：Apple Silicon macOS
- 数据：官方 minimal bundle；四个 Git LFS bundle 均按 pointer 中的 SHA-256 校验

上游验证实测：

| 门禁 | 结果 |
|---|---:|
| 应用测试 | 1652 passed |
| common 模块测试 | 76 passed |
| 其他 package 测试 | 110 passed, 2 skipped |
| 总计 | **1838 passed, 2 skipped** |
| task 端到端校验 | **147/147 passed** |

两个 skip 是上游 MCP 相关测试；本次 evaluator 实验不依赖它们。
保存输出位于 [verify-tests.log](./results/verify-tests.log) 和 [verify-tasks.log](./results/verify-tasks.log)。公开仓库版本只把本机绝对路径替换为 `$ARL_WORKSPACE`，测试名称、结果、版本和告警内容保持不变。

## 5 个固定任务

| Task ID | 类型 | 难度 | Oracle | No-op | 额外新增 | 额外删除 |
|---|---|---:|---:|---:|---:|---:|
| `6c2c621_2` | Simple Note 批量导出到文件系统 | 2 | 通过 8/8 | 失败 2/8 | 失败 4/8 | 失败 4/8 |
| `530b157_1` | 短信取证 → Venmo 支付 → 短信确认 | 3 | 通过 10/10 | 失败 2/10 | 失败 9/10 | 失败 9/10 |
| `37a8675_1` | 手机号识别联系人 → Venmo 转账 | 2 | 通过 6/6 | 失败 1/6 | 失败 5/6 | 失败 5/6 |
| `4fab96f_2` | 识别过期请求 → 批量提醒 | 2 | 通过 8/8 | 失败 2/8 | 失败 7/8 | 失败 7/8 |
| `383cbac_1` | 跨应用只读聚合计算 | 1 | 通过 2/2 | 失败 1/2 | 失败 1/2 | 失败 1/2 |

每次 `collateral_add` 的状态差分都确认 `simple_note.Note added = 1`；每次 `collateral_delete` 都确认 `simple_note.Note removed = 1`。因此失败来自真实持久化副作用，不是脚本仅调用了一个函数却未改变数据库。

## 一次值得保留的实验纠错

第一版实验把无关写入放在 oracle 之后，结果错误地显示副作用轨迹 5/5 成功。定位后发现：oracle 已调用 `supervisor.complete_task`，运行时会拒绝此后的 API 写入；同时环境使用 `raise_on_failure=False`，失败响应没有自动抛出，脚本也没有验证写入结果。

修正包括：

1. 在完成动作之前注入新增或删除；
2. 检查 API 响应；
3. 在运行 oracle 前断言状态差分中确有 `added = 1` 或 `removed = 1`；
4. 再交给官方 evaluator 判定。

这个纠错也形成了一条项目设计原则：**故障注入是否发生，必须由环境状态或事件日志证明，不能由“调用过注入函数”推断。**

## 本机代理兼容性

本机 HTTP 代理会把上游测试使用的不可达域名改写成 HTTP 502，导致 `test_world_loads_in_remote_mode` 看不到预期连接异常，并连带污染后续 SQLite 清理测试。没有修改上游源码，只对测试域名绕过代理：

```bash
NO_PROXY="non-existent-server.com,${NO_PROXY:-}" \
no_proxy="non-existent-server.com,${no_proxy:-}" \
appworld verify tests
```

加入该设置后，上述两个测试与完整测试集均通过。

## 可复现性与隐私边界

- 完整 5 任务 × 4 变体连续运行两次；去除生成时间后，两次任务级 JSON 完全一致。
- [run_appworld_repro.py](./run_appworld_repro.py) 只在本地调用官方编译 oracle，不导出私有 oracle/evaluator 源码。
- [appworld_repro_summary.json](./results/appworld_repro_summary.json) 只包含公开任务说明、聚合判定与模型变化计数；已检查不含密码、access token、API key、canary 或私有源码。

## 尚未完成的边界

- 这是 oracle/evaluator 机制复现，不是 LLM Agent 实验；当前未配置模型 API。
- 只用了固定 5 个 dev 任务，不能外推为 AppWorld 全量 Agent 成绩。
- 当前固定的是 2026-02-17 的开发提交，不等同于论文发表时的精确发行版。
- 上游依赖存在 Starlette/httpx 弃用警告，但本次测试与实验没有功能失败。
- 尚未加入“错误字段值”这一更细粒度 mutation；当前三类错误是漏做目标、额外新增和额外删除。
