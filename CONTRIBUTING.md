# Contributing

感谢参与 Agent Reliability Lab。项目接受能提高本地 Agent runtime、stateful benchmark 和 reliability evaluation 可复现性的改进。

## 本地开发

需要 Python 3.11 或更高版本，核心运行时没有第三方 Python 依赖。

```bash
git clone https://github.com/Hai-qq/agent-reliability-lab.git
cd agent-reliability-lab

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python scripts/manage_artifact_bundles.py restore \
  --bundle-dir artifacts/release_bundle_v15 \
  --project-root .

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  python -m unittest discover -s tests -p 'test_*.py' -v

ruff check src scripts tests
ruff format --check src scripts tests
```

恢复命令面向不含本地完整 evidence 树的全新 clone；它会先验证四个公开 bundle，并拒绝覆盖已有 artifact 目标。

完整实验命令和固定版本见 [Experiment Guide](./docs/running-experiments.md)。

## 贡献边界

- 只使用官方开源 benchmark 的本地、合成、隔离环境。
- 不提交真实账户、真实网络目标、凭据、cookie、私钥或第三方私有数据。
- 不把 prompt-injection、攻击/防御或模型/API 集成混入普通可靠性实验；新增此类范围必须先单独讨论授权、成本和安全边界。
- 已授权的模型 runner 只能从环境变量读取 credential、只能处理本项目合成 payload，并必须记录精确 model binding、硬预算、provider/协议错误和 digest-only audit；下一次 provider response 必须在调用前纳入预算检查，禁止将 key 放入 CLI、配置、日志、trace 或 artifact。
- 新 runner 必须拒绝覆盖已有结果路径；trace 默认只保存 digest 与类型化元数据。
- 行为变更应带定向测试，并同步 README、相关文档、结果 manifest 和限制说明。
- 不复制上游 benchmark 源码、数据或受限许可内容；引用边界见 [THIRD_PARTY.md](./THIRD_PARTY.md)。

提交 pull request 前，请确认 Python 3.11/3.12 测试和 Ruff 均通过，并在 PR 中写明命令、结果、限制及是否产生新 artifact。
