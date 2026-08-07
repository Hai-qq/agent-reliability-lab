# BrowserGym runtime/harness 最小复现报告

> 运行日期：2026-08-07；这是本地 runtime、evaluator、错误恢复与续跑验证，不是 LLM Agent 或论文排行榜复现。

## 结论

- 三个安全选取的官方 MiniWoB 测试文件：**15 passed in 37.09s**。
- `click-scroll-list`、`click-menu-2`、`use-colorwheel-2` 各运行 seeds `0,1,2`：**9/9 成功**，三个任务均通过全部三个固定 seed。
- `click-scroll-list::seed-0` 先触发一次 100 ms locator timeout，再在同一环境完成任务：**1/1 恢复成功**。
- 首次运行在 4/9 job 后主动中断；续跑跳过这 4 个结果并完成剩余 5 个。续跑前后已完成记录的 SHA-256 均为 `65ab0ad5bebb555c49a7610e52ff8f82e26f258d4168a2b59ec2894194415bb2`。
- 完整的两阶段流程再运行一次，三个 JSON 文件均与首次结果逐字节一致。

## 运行时与 evaluator 证据

| 证据 | 实测结果 |
|---|---:|
| BrowserGym / MiniWoB++ 提交 | `9e779f0` / `7fd85d7` |
| BrowserGym / Playwright | `0.14.3` / `1.44.0` |
| Chromium | `125.0.6422.26`（revision `1117`） |
| 官方安全测试子集 | 15/15 passed |
| 固定 harness jobs | 9/9 success |
| 通过全部 3 seeds 的任务 | 3/3 |
| 受控错误恢复 | 1/1 |
| action 阶段 HTTP(S) request | 0 |
| 模型调用 / 配置的外部目标 | 0 / 0 |

每个 job 都通过 BrowserGym 的真实 `gym.make`、`reset`、observation、`step` 和 MiniWoB reward/termination evaluator；脚本没有绕过 evaluator 直接写入成功标记。

## 中断—续跑证据

第一阶段状态为 `interrupted`，已完成 4 个、待运行 5 个；状态文件在每个完成 job 后原子更新。第二阶段的 `--resume`：

1. 按固定 job 顺序读取 4 个已有记录；
2. 对这些记录计算恢复前 SHA-256；
3. 跳过已有 job，只执行剩余 5 个；
4. 再计算已有记录 SHA-256，并断言与恢复前相同；
5. 断言最终 9 个 job 唯一且全部成功。

中断摘要、最终摘要和最终状态文件分别保留，不用“最终成功”覆盖中断证据。

## 隔离边界

- `MINIWOB_URL` 必须精确指向固定 MiniWoB++ checkout 的 `file://` 目录，否则脚本退出。
- Playwright BrowserContext 使用 `offline=True` 且禁用 service worker；每个初始观测均断言 URL scheme 为 `file`。
- 三个任务 HTML 的 script/style 引用已核验为本地相对路径。动作阶段记录到的 HTTP(S) request 为 0。
- 输出只保存 task ID、seed、哈希、计数、动作类别、reward/termination 与错误类别；不导出 goal 文本、截图、DOM、无障碍树或 Playwright 原始 trace。

## 不能推出的结论

- 固定 solver 从公开 goal 结构构造动作，作用是验证 runtime/harness，不代表通用 Agent 能力。
- 只有 3 个任务和 3 个固定 seed；“全部三 seed 通过”不是统计意义上的 `Pass^3`，不报告置信区间。
- 未安装或运行 AgentLab Study，未验证并行 worker、完整 trace viewer、模型 API、WebArena、WorkArena 或完整 BrowserGym 测试集。
- Chromium 与 Python 运行时是本机临时依赖；交付目录保留重建命令与结果，不保留 `.runtime`。

机器结果：[browsergym_repro_summary.json](./results/browsergym_repro_summary.json)。
