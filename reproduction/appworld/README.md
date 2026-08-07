# AppWorld evaluator 最小复现

本复现验证四件事：

1. 官方 oracle 在 5 个 dev 任务上通过状态 evaluator；
2. 只声称“已完成”的 no-op 行为不能通过；
3. oracle 完成目标前额外新增无关记录，会被 collateral-damage 检查拒绝；
4. oracle 完成目标前额外删除无关记录，也会被 collateral-damage 检查拒绝。

脚本不会导出 AppWorld 私有 ground-truth、oracle 或 evaluator 源码，只保存任务公开信息、聚合测试数量和数据库模型变化计数。

## 固定环境

- AppWorld commit：`a072b7a86e7c1d5b1d7175659d750ebb9b79f10a`
- AppWorld version：`0.2.0.dev0`
- Python：3.11
- 数据：官方 minimal bundle；train/dev 具有 full ground truth

AppWorld 官方 bundle 使用 Git LFS。若浅克隆只得到 pointer，需先安装 Git LFS 并执行 `git lfs pull`；本次复现对四个 bundle 按 pointer 中的 SHA-256 校验后下载。

## 官方环境验证

```bash
NO_PROXY="non-existent-server.com,${NO_PROXY:-}" \
no_proxy="non-existent-server.com,${no_proxy:-}" \
appworld verify tests

appworld verify tasks
```

`non-existent-server.com` 是上游连通性测试使用的保留测试目标。若本机代理把无法访问的域名改写为 HTTP 502，需要加入 `NO_PROXY`，否则测试无法观察预期的连接异常。

## 运行 5 任务复现

从已经安装、解包并下载数据的 AppWorld 仓库根目录执行：

```bash
python /absolute/path/to/run_appworld_repro.py \
  --output /absolute/path/to/appworld_repro_summary.json
```

实测关系：

| Variant | 实测 |
|---|---|
| `oracle` | 5/5 success |
| `no_op` | 0/5 success |
| `collateral_add` | 0/5 success；每次均确认 `simple_note.Note added = 1` |
| `collateral_delete` | 0/5 success；每次均确认 `simple_note.Note removed = 1` |

详细结果、实验纠错、代理兼容性和限制见 [RESULTS.md](./RESULTS.md)；机器可读结果见 [results/appworld_repro_summary.json](./results/appworld_repro_summary.json)，上游门禁原始输出见 [verify-tests.log](./results/verify-tests.log) 和 [verify-tasks.log](./results/verify-tasks.log)。
