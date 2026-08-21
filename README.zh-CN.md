# Agent Reliability Lab

面向有状态工具型 Agent 的故障注入 benchmark 与可靠性 Runtime。

[English](./README.md) · [Evidence Explorer](https://hai-qq.github.io/agent-reliability-lab/) · [方法学](./docs/methodology.md) · [Claim Registry](./docs/claims-registry.md)

```text
Agent / Policy
  → Reliability Runtime
  → Fault-Injected Stateful Environment
  → State Evaluator
  → Verifiable Evidence Bundle
```

ARL 的三个核心价值是：确定性故障注入、在相同任务/seed/trial/model 人群上比较
Runtime 干预，以及用最终状态和副作用证据取代 Agent 的自我完成声明。核心 Runtime
零第三方运行时依赖；smoke、验证和分析均在本地完成，不调用模型、provider、网络，
也不需要 credential。

## 五分钟开始

```bash
git clone https://github.com/Hai-qq/agent-reliability-lab.git
cd agent-reliability-lab
python -m pip install -e .

arl doctor
arl run smoke --output evidence/local-smoke
arl verify evidence/local-smoke
arl analyze evidence/local-smoke
```

仓库内置示例可以直接验证：

```bash
arl verify evidence/arl-smoke-v1
```

不再需要设置 `PYTHONPATH`。`arl run smoke` 会在 clean/fault 条件下运行本地 scripted
R0/R1/R2，生成严格的 `arl-evidence-v1` bundle，并拒绝覆盖已有输出路径。

## 当前证据状态

| Study | 已保存事实 | 可声明状态 | 公开 episode 证据 |
| --- | --- | --- | --- |
| v0.28 Flash + Qwen | infrastructure valid；Qwen readiness failed | **阻断：仅探索性，不得声明确认性结论** | 未转换为 v1 ledger |
| v0.29 prospective holdout | 2,592 个计划 episode 完成；2 次未恢复 Qwen HTTP 503；4 个 Qwen 金额预算超限；infrastructure 与 Qwen readiness 失败 | **推断无效：仅可报告描述性聚合** | **NOT_MATERIALIZED** |
| v0.30 | 48-template 合同与 scripted preflight | **没有模型结果** | 仅 scripted fixture |
| `arl-smoke-v1` | 54 个本地 scripted episode，bundle 验证通过 | 仅安装/验证器证据 | 已 materialize |

v0.28/v0.29 的正向描述性点估计不能覆盖失败门禁；没有失败 cell 被补跑、删除或改成
valid。公开 checkout 不含 ignored 的 v0.29 full summary/study ledger，因此仓库不会伪造
2,592-episode 公共 bundle。详见 [Claim Registry](./docs/claims-registry.md) 和
[有效性威胁](./docs/threats-to-validity.md)。

## 0.4.0 稳定接口

- `arl.runtime`：`AgentPolicy`、`ReliabilityRuntime` 与既有核心 Runtime。
- `arl.environments`：`StatefulEnvironment`。
- `arl.faults`：`FaultInjector`。
- `arl.evaluation`：`StateEvaluator`。
- `arl.providers`：可选的 `ModelBackend` 边界。
- `arl.studies`：token budget 与冻结的 blocked randomized schedule。
- `arl.evidence`：schema、默认拒绝式脱敏、确定性 bundle、迁移和验证器。
- `arl.analysis`：配对 estimand、task-template cluster bootstrap 与精确敏感性检验。
- `arl.cli`：统一离线优先命令入口。

历史包（例如 `arl_holdout_v29`）继续保留以复现实验；新扩展应使用稳定命名空间。
Python distribution、study contract、evidence schema、task catalog 与 artifact bundle
使用相互独立的版本。详见[兼容性政策](./docs/versioning.md)。

## 公开证据合同

`arl-evidence-v1` 包含 study contract、canonical gzip episode/provider ledger、aggregate、
analysis、redaction policy、schemas，以及绑定所有公开文件大小与 SHA-256 的 manifest。
发布策略默认拒绝：未知字段、非 allowlist 状态和疑似 secret 都会使生成失败。

```bash
arl verify BUNDLE
arl analyze BUNDLE
arl bundle NORMALIZED_PRIVATE_DIR --public-output NEW_DIR \
  --public-state-field status --public-state-field counter
```

验证器检查 schema、精确文件集、全部 digest、episode 数量与 cell 唯一性、冻结执行顺序、
aggregate 重算、analysis 输入、logical call 关联、脱敏策略和 evaluator clause。

## 本地扩展示例

- [最小 Environment](./examples/minimal_environment/)
- [自定义 Fault](./examples/custom_fault/)
- [自定义 Runtime](./examples/custom_runtime/)

## 开发与验证

```bash
python -m pip install -e ".[dev,validation]"
python scripts/manage_artifact_bundles.py restore \
  --bundle-dir artifacts/release_bundle_v15 --project-root .
python -m unittest discover -s tests -p "test_*.py"
ruff check src scripts tests examples
ruff format --check src scripts tests examples
mypy src/arl/evidence src/arl/analysis src/arl/studies src/arl/cli.py
```

CI 不调用真实 provider。未来若启动新的模型实验，必须先单独授权、冻结廉价模型/预算、
provider binding、价格快照、source commit 与公开证据方案；脚本仍不得保存 credential 或
raw model content。

文档入口：[架构](./docs/architecture.md)、[Benchmark Card](./docs/benchmark-card.md)、
[方法学](./docs/methodology.md)、[历史 study 索引](./docs/history/README.md)、
[v0.30 设计](./docs/studies/v030-design.md)、[安全](./SECURITY.md)、
[贡献指南](./CONTRIBUTING.md)、[引用](./CITATION.cff)。
