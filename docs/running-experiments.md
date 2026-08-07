# ARL 实验运行与验证指南

## 环境

- macOS arm64
- Python `3.12.12`（v0.7–v0.9 正式 artifact；v0.1–v0.6 历史 artifact 使用 `3.12.2`）
- Python SQLite runtime `3.50.4`（v0.7–v0.9）
- Ruff `0.15.17`
- 根 project 保持 `0.3.0` 以保留 v0.3 manifest；Validity Gates v0.4、Retail v0.5、Travel v0.6、Schema Adapter v0.7、Conflict Recovery v0.8 与 Cross-Domain Resilience v0.9 使用独立包和源码/结果 manifest
- 第三方 Python runtime dependencies：无

代码只使用 Python 标准库。`pyproject.toml` 声明 `requires-python >= 3.11`；每个正式 artifact 的精确解释器版本保存在自身 `summary.json` 与 `validation.log`。

另以 Python `3.11.15` / SQLite `3.50.4` 运行当前 100 tests，全部通过；v0.7–v0.9 正式实验 JSON 采用固定的 Python 3.12.12 环境。

## 运行测试

```bash
ARL_PROJECT=/absolute/path/to/agent-reliability-lab
ARL_PYTHON="$(uv python find 3.12)"

cd "$ARL_PROJECT"
env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" -m unittest discover -s tests -p 'test_*.py' -v

ruff check src scripts tests
ruff format --check src scripts tests
```

当前实测 `Ran 100 tests ... OK`，Ruff check/format check 均通过。历史增量的当时测试数和解释器版本保留在各自 `validation.log` 中。

## 运行 v0.1 配对实验

输出路径必须尚不存在，脚本会拒绝覆盖已有证据：

```bash
ARL_RUN_DIR="$ARL_PROJECT/artifacts/workspace_paired_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_workspace_paired.py \
    --output "$ARL_RUN_DIR/summary.json" \
    --traces-dir "$ARL_RUN_DIR/traces"
```

预期输出：

```text
Wrote 12 episodes, 12 traces, and .../summary.json
```

正式保存结果位于：

- [summary.json](../artifacts/workspace_paired/summary.json)
- [12 条 JSONL trace](../artifacts/workspace_paired/traces/)
- [validation.log](../artifacts/workspace_paired/validation.log)

## 结果校验

```bash
jq '.aggregate, .validity' artifacts/workspace_paired/summary.json
find artifacts/workspace_paired/traces -type f -name '*.jsonl' | wc -l
```

正式 summary SHA-256：

```text
8c5fc93c7cb426e7cafd6d232da722394b9e32e00e6737bf3bac9e70f5ac8ba2
```

`metadata.source_manifest` 保存本次 `src/arl/**/*.py` 与 runner 的逐文件 SHA-256 及组合 SHA-256。第二次运行必须写到新目录；本次验证中 summary 和 12 条 trace 均与第一次逐字节一致。

## 运行 R2 提交后超时实验

同样必须使用尚不存在的输出路径：

```bash
ARL_R2_RUN_DIR="$ARL_PROJECT/artifacts/workspace_r2_postcommit_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_workspace_r2_paired.py \
    --output "$ARL_R2_RUN_DIR/summary.json" \
    --traces-dir "$ARL_R2_RUN_DIR/traces"
```

预期输出：

```text
Wrote 12 episodes, 12 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 summary](../artifacts/workspace_r2_postcommit/summary.json)
- [正式 12 条 trace](../artifacts/workspace_r2_postcommit/traces/)
- [独立 repeat](../artifacts/workspace_r2_postcommit_repeat/)
- [R2 validation.log](../artifacts/workspace_r2_postcommit/validation.log)

正式 summary SHA-256：

```text
fd509bd662ca55e18c78f5ec70335970d52545795992417596ba8dfbc8e34b22
```

`metadata.source_manifest` 与 `metadata.trace_manifest` 都保存逐文件 SHA-256、canonical serialization 算法和组合 SHA-256。正式与 repeat 的 summary 逐字节一致，12/12 trace 逐字节一致；runner 对已有正式输出返回 `Refusing to overwrite output`。

查询结果：

```bash
jq '.aggregate, .validity' artifacts/workspace_r2_postcommit/summary.json
```

应看到 R1 clean/fault 为 `3/3`、`0/3`，R2 clean/fault 为 `3/3`、`3/3`，且 `all_selected_checks_passed=true`。

## 运行 v0.3 双任务实验

输出路径同样必须尚不存在：

```bash
ARL_V03_RUN_DIR="$ARL_PROJECT/artifacts/workspace_multitask_v03_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_workspace_multitask.py \
    --output "$ARL_V03_RUN_DIR/summary.json" \
    --traces-dir "$ARL_V03_RUN_DIR/traces"
```

预期输出：

```text
Wrote 24 episodes, 24 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 summary](../artifacts/workspace_multitask_v03/summary.json)
- [正式 24 条 trace](../artifacts/workspace_multitask_v03/traces/)
- [独立 repeat](../artifacts/workspace_multitask_v03_repeat/)
- [v0.3 validation.log](../artifacts/workspace_multitask_v03/validation.log)

正式 summary SHA-256：

```text
72201242549f6fd1df065fff0ce994a8738c6162e0cfc6fb1644ed396e6e8c62
```

查询结果：

```bash
jq '.aggregate, .validity' artifacts/workspace_multitask_v03/summary.json
```

应看到 24 episodes、2 tasks；R1 clean/fault 为 `6/6`、`0/6`，R2 为 `6/6`、`6/6`，且 `all_selected_checks_passed=true`。正式与 repeat 的 summary 及 24/24 traces 逐字节一致。v0.3 source manifest 覆盖 24 个 runtime/config 文件，并首次把 `pyproject.toml` 纳入 canonical manifest。

## 运行 v0.4 validity gates

输出文件必须尚不存在：

```bash
ARL_V04_RUN_DIR="$ARL_PROJECT/artifacts/workspace_validity_v04_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_workspace_validity.py \
    --output "$ARL_V04_RUN_DIR/summary.json"
```

预期输出：

```text
Wrote 120 random-valid rollouts, 12 dump-state cases, and .../summary.json
```

正式结果、独立重复和验证日志位于：

- [正式 summary](../artifacts/workspace_validity_v04/summary.json)
- [独立 repeat](../artifacts/workspace_validity_v04_repeat/summary.json)
- [v0.4 validation.log](../artifacts/workspace_validity_v04/validation.log)

正式 summary SHA-256：

```text
cf1108e91fb9fbc6c0bec8f473f68b202a6e80393f12b43d573c3c54b61c179a
```

查询结果：

```bash
jq '.validity.random_valid_tool, .validity.dump_state, .validity.golden_trace' \
  artifacts/workspace_validity_v04/summary.json
```

应看到 random-valid-tool TaskSuccess/SafeSuccess 为 `11/120`、`6/120`，schema errors 为 0；dump-state 12/12 被拒绝；4 条 golden trace 与 3 类 mutation 门禁通过。正式与 repeat summary 逐字节一致，v0.4 source manifest 覆盖 28 个文件。

## 运行 v0.5 Retail 双任务实验

输出路径必须尚不存在；正式运行使用 Python 3.12.2：

```bash
ARL_RETAIL_RUN_DIR="$ARL_PROJECT/artifacts/retail_minimal_v05_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_retail_minimal.py \
    --output "$ARL_RETAIL_RUN_DIR/summary.json" \
    --traces-dir "$ARL_RETAIL_RUN_DIR/traces"
```

预期输出：

```text
Wrote 24 episodes, 24 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 summary](../artifacts/retail_minimal_v05/summary.json)
- [正式 24 条 trace](../artifacts/retail_minimal_v05/traces/)
- [独立 repeat](../artifacts/retail_minimal_v05_repeat/)
- [v0.5 validation.log](../artifacts/retail_minimal_v05/validation.log)

正式 summary SHA-256：

```text
19c823b0570504153403295d511fd2af31383be504288022ed90755d74d5fcdc
```

查询结果：

```bash
jq '.aggregate, .validity' artifacts/retail_minimal_v05/summary.json
```

应看到 24 episodes、2 tasks；R1 clean/fault 为 `6/6`、`0/6`，R2 为 `6/6`、`6/6`，且 `all_selected_checks_passed=true`。正式与 repeat summary 及 24/24 traces 逐字节一致；v0.5 source manifest 覆盖 8 个实际依赖文件，v0.1–v0.4 已记录 manifest 均保持匹配。

## 运行 v0.6 Travel 双任务实验

输出路径必须尚不存在；正式运行使用 Python 3.12.2：

```bash
ARL_TRAVEL_RUN_DIR="$ARL_PROJECT/artifacts/travel_minimal_v06_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_travel_minimal.py \
    --output "$ARL_TRAVEL_RUN_DIR/summary.json" \
    --traces-dir "$ARL_TRAVEL_RUN_DIR/traces"
```

预期输出：

```text
Wrote 24 episodes, 24 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 summary](../artifacts/travel_minimal_v06/summary.json)
- [正式 24 条 trace](../artifacts/travel_minimal_v06/traces/)
- [独立 repeat](../artifacts/travel_minimal_v06_repeat/)
- [v0.6 validation.log](../artifacts/travel_minimal_v06/validation.log)

正式 summary SHA-256：

```text
51a5bd6aabca4b243c79325aa8446dd652ecefddfc9dba3d55303fd60e8b3bda
```

查询结果：

```bash
jq '.aggregate, .validity' artifacts/travel_minimal_v06/summary.json
```

应看到 24 episodes、2 tasks；R1 clean/fault 为 `6/6`、`0/6`，R2 为 `6/6`、`6/6`。R2 fault 中有 3 次提交后查询确认、3 条航班失败 recovery branch 与 3 次酒店取消补偿；`all_selected_checks_passed=true`。正式与 repeat summary 及 24/24 traces 逐字节一致；v0.6 source manifest 覆盖 8 个实际依赖文件。

## 运行 v0.7 Schema Adapter 实验

输出路径必须尚不存在；正式运行使用 Python 3.12.12：

```bash
ARL_SCHEMA_RUN_DIR="$ARL_PROJECT/artifacts/schema_adapter_v07_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_schema_adapter.py \
    --output "$ARL_SCHEMA_RUN_DIR/summary.json" \
    --traces-dir "$ARL_SCHEMA_RUN_DIR/traces"
```

预期输出：

```text
Wrote 24 episodes, 24 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 summary](../artifacts/schema_adapter_v07/summary.json)
- [正式 24 条 trace](../artifacts/schema_adapter_v07/traces/)
- [独立 repeat](../artifacts/schema_adapter_v07_repeat/)
- [v0.7 validation.log](../artifacts/schema_adapter_v07/validation.log)

正式 summary SHA-256：

```text
a0b25f440651bfbe6776e2a4cb21c89630451775ad246fd4ae4735c4791b13d6
```

查询结果：

```bash
jq '.aggregate, .validity' artifacts/schema_adapter_v07/summary.json
```

应看到 24 episodes、2 tasks；R1 clean/fault 为 `6/6`、`0/6`，R2 schema-adapted 为 `6/6`、`6/6`。R2 fault 中有 3 次输入 schema 映射与 3 次成功结果归一化；九个 malformed-contract case、non-oracular descriptor、reset/snapshot、baseline rejection、digest-only trace 与 v0.1–v0.6 历史 source manifest 门禁全部通过。正式与 repeat summary 及 24/24 traces 逐字节一致；v0.7 source manifest 覆盖 13 个实际依赖文件。

## 运行 v0.8 Conflict Recovery 实验

输出路径必须尚不存在；正式运行使用 Python 3.12.12：

```bash
ARL_CONFLICT_RUN_DIR="$ARL_PROJECT/artifacts/workspace_conflict_v08_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_conflict_recovery.py \
    --output "$ARL_CONFLICT_RUN_DIR/summary.json" \
    --traces-dir "$ARL_CONFLICT_RUN_DIR/traces"
```

预期输出：

```text
Wrote 18 episodes, 18 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 summary](../artifacts/workspace_conflict_v08/summary.json)
- [正式 18 条 trace](../artifacts/workspace_conflict_v08/traces/)
- [独立 repeat](../artifacts/workspace_conflict_v08_repeat/)
- [v0.8 validation.log](../artifacts/workspace_conflict_v08/validation.log)

正式 summary SHA-256：

```text
91d72d86f156377416344669c9bd0517a298b1e4f7af5816993eca53e57ad6f7
```

查询结果：

```bash
jq '.aggregate, .validity' artifacts/workspace_conflict_v08/summary.json
```

应看到 18 episodes、1 task、3 conditions。旧 R2 clean 为 `3/3`、compatible conflict 为 `0/3`；Conflict-aware R2 clean 与 compatible conflict 均为 `3/3`，对 3 个 incompatible conflict 全部返回 `conflict_precondition_changed` 并保持零通知、零请求关闭。四个 guard contract、reset/snapshot、baseline rejection、digest-only trace 与 v0.1–v0.7 历史 source manifest 门禁全部通过。正式与 repeat summary 及 18/18 traces 逐字节一致；v0.8 source manifest 覆盖 20 个实际依赖文件。

## 运行 v0.9 Cross-Domain Resilience 实验

输出路径必须尚不存在；正式运行使用 Python 3.12.12：

```bash
ARL_RESILIENCE_RUN_DIR="$ARL_PROJECT/artifacts/cross_domain_resilience_v09_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_cross_domain_resilience.py \
    --output "$ARL_RESILIENCE_RUN_DIR/summary.json" \
    --traces-dir "$ARL_RESILIENCE_RUN_DIR/traces"
```

预期输出：

```text
Wrote 36 episodes, 36 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 summary](../artifacts/cross_domain_resilience_v09/summary.json)
- [正式 36 条 trace](../artifacts/cross_domain_resilience_v09/traces/)
- [独立 repeat](../artifacts/cross_domain_resilience_v09_repeat/)
- [v0.9 validation.log](../artifacts/cross_domain_resilience_v09/validation.log)

正式 summary SHA-256：

```text
33c0cf3b4902418d8506a9582df9b21b37b0f2fd6d72c135ab38046211bf3676
```

查询结果：

```bash
jq '.aggregate, .validity' artifacts/cross_domain_resilience_v09/summary.json
```

应看到 36 episodes、2 domains、2 runtimes、3 conditions。旧 R2 的 control 为 `6/6`、compatible conflict 为 `0/6`；Contract-guarded R2 的 control 与 compatible conflict 均为 `6/6`，对 6 个 incompatible conflict 全部返回 `conflict_precondition_changed` 并保留外部目标状态。Travel 的 9 次 compensation contract attempt 中 6 次通过 pre/postcondition 并完成，3 次分类失败。guard/contract mutation、reset/snapshot、baseline rejection、digest-only trace、ground-truth isolation 与 v0.1–v0.8 历史 source manifest 门禁全部通过。正式与 repeat summary 及 36/36 traces 逐字节一致；v0.9 source manifest 覆盖 20 个实际依赖文件。

## 安全边界

- 不读取真实账户、浏览器会话、网络服务或第三方系统；
- 不需要 API key、token 或模型凭据；
- task、Workspace、Retail 与 Travel 记录均为固定合成数据；
- trace 只保存 digest 与类型化元数据；
- fault ID 仅写入 harness/evaluator trace，不出现在 policy observation 或 `StepResult` 中；
- 本实验不包含 prompt injection、attack/defense 或可迁移对抗材料。
