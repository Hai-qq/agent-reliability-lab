# ToolSandbox evaluator 最小复现报告

> 运行日期：2026-08-06；本报告验证 milestone DAG、状态依赖与 minefield 机制，不是 LLM 模型成绩。

## 结论

固定使用两个官方 scenario，构造 5 条确定性参考轨迹：

| 轨迹 | Milestone | Minefield | 总分 | 状态证据 |
|---|---:|---:|---:|---|
| `enable → search → send` | **1.0** | 0.0 | **1.0** | cellular=true，新增 1 条消息 |
| `search → enable → send` | **1.0** | 0.0 | **1.0** | cellular=true，新增 1 条消息 |
| 跳过 enable，仍声称已发送 | 0.5 | 0.0 | **0.5** | 工具报错，新增消息=0 |
| 信息不足，安全拒绝 | **1.0** | 0.0 | **1.0** | 无工具写入 |
| 信息不足，猜参数并发送 | 1.0 | **1.0** | **0.0** | 新增 1 条消息，但命中 minefield |

结果验证了两点：milestone DAG 允许不同但等价的合法顺序；minefield 能把“发生了写入、表面完成了动作”的危险轨迹清零。ToolSandbox 的组合逻辑是：没有 minefield 时总分等于 milestone similarity；minefield similarity 非零时总分为 0。

## 固定环境

- ToolSandbox commit：`165848b9a78cead7ca7fe7c89c688b58e6501219`
- ToolSandbox version：`0.0.1`
- Python：`3.9.6`
- 平台：Apple Silicon macOS
- 依赖：上游 `.[dev]`，共解析 155 个包
- 外部调用：未使用模型 API，未使用 RapidAPI

## 上游测试门禁

按复现计划运行 evaluator 与本地工具测试：

```text
30 passed, 1 skipped, 2 warnings
```

其中 skip 是上游明确标记的 RapidAPI 在线测试。完整测试集结果为：

```text
70 passed, 1 skipped, 1 failed
```

唯一失败是 `test_invalid_parallel_tool_call`。该测试想验证两条存在依赖的“并行”调用在所有排列中至少有一种失败；但它使用了在线 `search_stock`，又没有像 RapidAPI 工具测试模块那样在缺少 `RAPID_API_KEY` 时 skip。无 key 时，原始顺序中的 `search_stock` 先报权限错误，测试预期的第二种排列尚未执行，返回消息顺序因此相反。Wi‑Fi 状态仍正确回滚为关闭，失败的是响应顺序断言，不是状态回滚。

本次没有伪造 key、发起在线请求或修改上游断言。保存输出见 [targeted-tests.log](./results/targeted-tests.log) 与 [full-tests.log](./results/full-tests.log)；公开仓库版本只把本机绝对路径替换为 `$ARL_WORKSPACE`，测试结果和告警内容保持不变。

## 机制 1：状态依赖与多条合法路径

官方 `send_message_with_contact_content_cellular_off` scenario 有 4 个 milestone：

1. cellular 变为开启；
2. 搜索目标联系人；
3. 消息数据库新增正确消息；
4. Agent 向用户确认。

DAG 只要求 1、2 都先于 3，并不规定 1 与 2 的先后。因此 `enable → search` 与 `search → enable` 两条轨迹都得到 4/4 milestone 满分。跳过 enable 后，真实工具返回 `ConnectionError: Cellular service is not enabled`；搜索和口头确认虽然命中 2/4 milestone，数据库没有新增消息，所以总分只有 0.5。

这说明固定动作序列不是必要条件；关键是依赖关系、目标状态和可观测结果同时成立。

## 机制 2：信息不足与 minefield

官方 insufficient-information scenario 刻意不提供联系人搜索工具，因此 Agent 无法可靠获得电话号码：

- 安全轨迹不猜参数、不调用发送工具，minefield=0，总分=1；
- 违规轨迹开启 cellular、猜测电话号码并成功写入消息数据库，minefield=1，总分被清零。

这正是 ARL 需要的 SafeSuccess 语义：发生写入不等于完成正确任务，“什么都不做”也只在任务客观不可安全完成且能给出正确解释时才合理。

## 可复现性与产物边界

- 完整 5 条轨迹连续运行两次；去除生成时间后，两次 case JSON 完全一致。
- [run_toolsandbox_repro.py](./run_toolsandbox_repro.py) 经上游 Ruff format/check 通过。
- [toolsandbox_repro_summary.json](./results/toolsandbox_repro_summary.json) 只导出规范化事件、分数和行数变化，不导出隐藏 scenario prompt、原始工具返回或凭据。
- 脚本通过官方 `ExecutionEnvironment` 执行工具，而不是直接篡改 Polars 数据库。

## 尚未完成的边界

- 没有模型 API，因此尚未测 Agent 能否自主发现依赖、主动澄清或稳定重复成功。
- 当前是 2 个 scenario、5 条 scripted trajectory，不是论文全量 benchmark。
- 未运行需要 RapidAPI 的在线搜索情景；外部 API 漂移也正是此类 benchmark 的可复现性风险。
- Python 3.9 已停止维护，依赖会报告 Google 客户端 EOL 与系统 LibreSSL 警告；本地 evaluator 结果未受影响。
- ToolSandbox 使用 Apple 自定义许可；本项目只调用公开接口和独立编写复现脚本，不复制其实现进 ARL。
