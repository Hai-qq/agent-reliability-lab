# ARL 实验运行与验证指南

## 环境

- macOS arm64
- Python `3.12.12`（v0.7–v0.28 正式 artifact 与 v0.29 scripted preflight；v0.29 provider formal 记录为 `3.12.13`；v0.1–v0.6 历史 artifact 使用 `3.12.2`）
- Python SQLite runtime `3.50.4`（v0.7–v0.28 与 v0.29 scripted preflight；v0.29 provider formal 只冻结解释器版本，没有单列 SQLite 版本）
- Ruff `0.15.17`
- 根 project 保持 `0.3.0` 以保留 v0.3 manifest；v0.4–v0.29 使用独立包和源码/结果 manifest
- 第三方 Python runtime dependencies：无

代码只使用 Python 标准库。`pyproject.toml` 声明 `requires-python >= 3.11`；每个正式 artifact 的精确解释器版本保存在自身 `summary.json` 与 `validation.log`。

当前开发分支以 Python `3.11.15` 和 `3.12.12` 各运行 267 tests，全部通过；Ruff 0.15.17 check/format check 通过。v0.16–v0.24、v0.27、v0.28 正式实验 JSON、v0.29 scripted preflight 以及 v0.25/v0.28 canary 使用 Python 3.12.12；v0.29 provider formal 自身记录为 Python 3.12.13。v0.15 发布冻结时的 173-test、v0.16 初次验收时的 187-test 与 v0.17 验收时的 200-test 结果仍保存在各自 validation log 中。

## 运行测试

```bash
ARL_PROJECT=/absolute/path/to/agent-reliability-lab
ARL_PYTHON="$(uv python find 3.12)"

cd "$ARL_PROJECT"
if [ ! -d "$ARL_PROJECT/artifacts/study_runtime_v10/study" ]; then
  env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
    "$ARL_PYTHON" scripts/manage_artifact_bundles.py restore \
    --bundle-dir artifacts/release_bundle_v15 \
    --project-root "$ARL_PROJECT"
fi

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" -m unittest discover -s tests -p 'test_*.py' -v

ruff check src scripts tests
ruff format --check src scripts tests
```

公开 clone 不包含被 `.gitignore` 排除的完整 v0.10–v0.13 树；上述条件分支会先从四个确定性 bundle 恢复并校验它们。本地完整树已存在时不重复恢复。当前开发分支在 Python 3.11/3.12 均实测 `Ran 267 tests ... OK`，Ruff check/format check 均通过。历史增量的当时测试数和解释器版本保留在各自 `validation.log` 中。

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

## 运行 v0.10 Study Runtime

Study workspace、summary 和 viewer 路径必须尚不存在，且 output/viewer 必须位于 workspace 之外。正式验证分两次启动：

```bash
ARL_STUDY_RUN_DIR="$ARL_PROJECT/artifacts/study_runtime_v10_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_resilience_study.py \
    --workspace "$ARL_STUDY_RUN_DIR/study" \
    --output "$ARL_STUDY_RUN_DIR/interrupted.json" \
    --stop-after 13

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_resilience_study.py \
    --workspace "$ARL_STUDY_RUN_DIR/study" \
    --output "$ARL_STUDY_RUN_DIR/summary.json" \
    --viewer "$ARL_STUDY_RUN_DIR/viewer.html" \
    --resume
```

预期输出：

```text
Study interrupted: 13/36 jobs complete; wrote .../interrupted.json and .../study-state.json
Study complete: 36/36 jobs complete; wrote .../summary.json and .../study-state.json
```

正式结果与独立重复位于：

- [正式 artifact 说明](../artifacts/study_runtime_v10/README.md)
- [中断 summary](../artifacts/study_runtime_v10/interrupted.json)
- [最终 summary](../artifacts/study_runtime_v10/summary.json)
- [scheduler state、36 个 result 与 36 条 trace bundle](../artifacts/release_bundle_v15/bundles/study-runtime-v10.zip)
- [自包含只读 viewer](../artifacts/study_runtime_v10/viewer.html)
- [独立 repeat](../artifacts/study_runtime_v10_repeat/)
- [v0.10 validation.log](../artifacts/study_runtime_v10/validation.log)

查询结果：

```bash
jq '.status, .progress, .resume, .validity.all_selected_checks_passed' \
  artifacts/study_runtime_v10/summary.json
```

应看到首阶段 13/36 后停止，resume 只新增 23 个 job，恢复前 13 个 result/trace 组合哈希前后一致，最终 36/36 完成且 `all_selected_checks_passed=true`。36 个 episode/result/trace 与 v0.9 参考证据一致，每个 job 的 attempt count 都是 1，v0.1–v0.9 九份历史 source manifest 全部匹配。

正式与 repeat 的中断 summary、最终 summary、state、viewer、36 个 result 和 36 条 trace 均逐字节一致。固定 SHA-256：

```text
summary: c660aad0b8370670f7b10fc4352e11e1d969b8ca003d59d1e4bddf670ad279a5
state:   5a8ce7ab59a560eccaa1740b51b8b64c043e2b7dc4e296eb27aff44cafae117f
viewer:  62360ef83df60a702db0fea4326f8a4f8bf0ec04e6f51617f8e4b5d8ec2a9c65
```

Viewer 是本地静态 HTML，可直接用浏览器打开；它只包含 digest 和类型化元数据，页面代码不发起网络 API 请求，也不能修改实验状态。

## 运行 v0.11 Parallel Study

v0.11 的正式合同固定为 4 个 worker、100 logical-tick lease、首阶段 12 个完成任务和 4 个遗留 active lease。两阶段必须写入同一个 workspace，但两个 summary 路径必须分别是尚不存在的新文件：

```bash
ARL_PARALLEL_RUN_DIR="$ARL_PROJECT/artifacts/parallel_study_v11_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_parallel_study.py \
    --workspace "$ARL_PARALLEL_RUN_DIR/study" \
    --output "$ARL_PARALLEL_RUN_DIR/interrupted.json" \
    --stop-after 12 \
    --leave-leases 4

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_parallel_study.py \
    --workspace "$ARL_PARALLEL_RUN_DIR/study" \
    --output "$ARL_PARALLEL_RUN_DIR/summary.json" \
    --resume
```

预期输出：

```text
Parallel study interrupted: 12/36 complete, 4 leased; wrote ...
Parallel study complete: 36/36 complete, 0 leased; wrote ...
```

正式结果与独立重复位于：

- [正式 artifact 说明](../artifacts/parallel_study_v11/README.md)
- [中断 summary](../artifacts/parallel_study_v11/interrupted.json)
- [最终 summary](../artifacts/parallel_study_v11/summary.json)
- [scheduler state、result、final trace 与 attempt trace bundle](../artifacts/release_bundle_v15/bundles/parallel-study-v11.zip)
- [独立 repeat](../artifacts/parallel_study_v11_repeat/)
- [v0.11 validation.log](../artifacts/parallel_study_v11/validation.log)

查询结果：

```bash
jq '.progress, .resume, .parallel, .validity.all_selected_checks_passed' \
  artifacts/parallel_study_v11/summary.json
```

应看到 42 次 lease acquisition、5 次 expiry（4 次进程恢复回收和 1 次定向过期）、1 次 stale commit 拒绝、1 次 worker crash、1 次 heartbeat，最大同时 lease 为 4。worker crash 与定向 expiry 的 job 各执行两次，但 36 个 job 的 `commit_count` 都为 1。正式与 repeat 的中断 summary、最终 summary/state、36 个 result、36 条 final trace 和 2 条 attempt trace 均逐字节一致。固定 SHA-256：

```text
summary: 5b199723774540d19f1c3f6916411703e0dc961f7b193fa6960bfb21d4156a6f
state:   a87acc7ce8a5d3c17f1bd1100651248302155728ebdbae77c31d4d65a37d7afd
source:  4eaf8bd306a7ddc4fcb7e9b589d063cd13031049c38a25396efdd8d863635375
```

## 运行 v0.12 Scenario Pack

输出文件和 trace 目录必须尚不存在：

```bash
ARL_SCENARIO_RUN_DIR="$ARL_PROJECT/artifacts/scenario_pack_v12_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_scenario_pack.py \
    --output "$ARL_SCENARIO_RUN_DIR/summary.json" \
    --traces-dir "$ARL_SCENARIO_RUN_DIR/traces"
```

预期输出：

```text
Wrote 72 episodes, 72 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 artifact 说明](../artifacts/scenario_pack_v12/README.md)
- [正式 summary](../artifacts/scenario_pack_v12/summary.json)
- [72 条 digest-only trace bundle](../artifacts/release_bundle_v15/bundles/scenario-pack-v12-traces.zip)
- [独立 repeat](../artifacts/scenario_pack_v12_repeat/)
- [v0.12 validation.log](../artifacts/scenario_pack_v12/validation.log)

查询结果：

```bash
jq '.aggregate.by_runtime, .validity.compensation_workflow_audit, \
    .validity.all_selected_checks_passed' artifacts/scenario_pack_v12/summary.json
```

旧 R2 的 control 为 `12/12`，24 个 conflict 全部停止；template-guarded R2 的 control 与 compatible conflict 都为 `12/12`，12 个 incompatible conflict 全部分类停止。四步 Travel workflow 共触发 9 次，6 次成功并完成 36 个 terminal public-read probe，3 次因补偿目标被外部改变而拒绝。正式与 repeat summary 及 72/72 traces 逐字节一致。固定 SHA-256：

```text
summary: 02cb8306f0cb932a205aec81ad22de7ce6f767e8d0ba1c61c96278e1d814f13a
source:  97cd66807a665bf67b9ccc2d00d927b1b4ed041b5dfaa01b3eecc2af21dccd87
traces:  eac40997996f6071cf1cce9a3e082d89e02f46ebdad34fccb2dd31a1a14be4f0
```

## 运行 v0.13 Symbolic User

输出文件和 trace 目录必须尚不存在：

```bash
ARL_SYMBOLIC_RUN_DIR="$ARL_PROJECT/artifacts/symbolic_user_v13_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_symbolic_user.py \
    --output "$ARL_SYMBOLIC_RUN_DIR/summary.json" \
    --traces-dir "$ARL_SYMBOLIC_RUN_DIR/traces"
```

预期输出：

```text
Wrote 720 sessions, 720 traces, and .../summary.json
```

正式结果与独立重复位于：

- [正式 artifact 说明](../artifacts/symbolic_user_v13/README.md)
- [正式 summary](../artifacts/symbolic_user_v13/summary.json)
- [720 条 digest-only trace bundle](../artifacts/release_bundle_v15/bundles/symbolic-user-v13-traces.zip)
- [独立 repeat](../artifacts/symbolic_user_v13_repeat/)
- [v0.13 validation.log](../artifacts/symbolic_user_v13/validation.log)

查询结果：

```bash
jq '.statistics.by_policy, .statistics.paired_safe_success_delta, \
    .validity.all_selected_checks_passed' artifacts/symbolic_user_v13/summary.json
```

One-shot direct approval 为 `120/120` SafeSuccess，但 clarification-required 与 pre-commit-revision 各产生 `120/120` unsafe commit。Revision-aware direct approval 为 `120/120` SafeSuccess；clarification 为 `107/120` SafeSuccess、13 次 safe abort，revision 为 `85/120` SafeSuccess、35 次 safe abort，全部 360 个 session 保持 0 unsafe commit。正式与 repeat summary 及 720/720 traces 逐字节一致。固定 SHA-256：

```text
summary: b74aa2ae26d6b5565000c06055da6fe8d69f2f060c0fdf3bd87edd08bf7d2d2c
source:  fd3f5f31031c4adc2bffc43ee365f26f89e88b41044be7eec6dd624e50e076f3
traces:  f69fea8f829ff047f734b30483c73ae75b4bed59fd361c5dcc720c6b67f1ae7b
```

## 生成 v0.14 Evidence Explorer

输出目录必须尚不存在。Builder 会重新读取仓库内 v0.10–v0.13 formal/repeat artifacts；任一记录缺失、哈希变化或 validity 失败都会停止：

```bash
ARL_EVIDENCE_DIR="$ARL_PROJECT/artifacts/evidence_explorer_v14_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/build_evidence_explorer.py \
    --output-dir "$ARL_EVIDENCE_DIR"
```

预期输出：

```text
Wrote 4 verified increments, 864 trace pairs, and .../index.html
```

正式结果与独立重复位于：

- [正式 artifact 说明](../artifacts/evidence_explorer_v14/README.md)
- [离线 Evidence Explorer](../artifacts/evidence_explorer_v14/index.html)
- [机器可读 evidence catalog](../artifacts/evidence_explorer_v14/evidence.json)
- [独立 repeat](../artifacts/evidence_explorer_v14_repeat/)
- [v0.14 validation.log](../artifacts/evidence_explorer_v14/validation.log)

查询结果：

```bash
jq '.increments[] | {version, headline_rate, metrics, integrity}, \
    .validity' artifacts/evidence_explorer_v14/evidence.json
```

应看到 v0.10–v0.13 四个增量、104 个 source 引用、4 对正式/重复 summary 与 864 对 trace 全部匹配；页面 audit 无外部脚本、网络 API 或可写控件。正式与 repeat 的 `evidence.json` 和 `index.html` 均逐字节一致。固定 SHA-256：

```text
evidence.json: 21375d1c64701f71dedcbd82182d7b3e84fabcf5dd3634b0c1721a926012881a
index.html:    bb1935446343c1901f38e8a5c0cc297cae436390979086513d676dff9ef7d2dd
source:        ca594a156126f9feb30be1fef4760b08b087abe7faa63c3e5de73c35376df2be
```

## 构建、验证与恢复 v0.15 Compact Artifact Bundle

完整本地 artifact 树存在时，可构建新的输出目录：

```bash
ARL_BUNDLE_DIR="$ARL_PROJECT/artifacts/release_bundle_v15_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/manage_artifact_bundles.py build \
    --output-dir "$ARL_BUNDLE_DIR"
```

预期输出：

```text
Wrote 4 deterministic bundles with 940 files to ...
```

公开 clone 可直接只读验证 committed bundles：

```bash
env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/manage_artifact_bundles.py verify \
    --bundle-dir "$ARL_PROJECT/artifacts/release_bundle_v15"
```

若需要重建 Git ignore 的 formal/repeat 完整树，目标目录必须尚不存在：

```bash
env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/manage_artifact_bundles.py restore \
    --bundle-dir "$ARL_PROJECT/artifacts/release_bundle_v15" \
    --project-root "$ARL_PROJECT"
```

正式结果：

- [artifact 说明](../artifacts/release_bundle_v15/README.md)
- [机器可读 manifest](../artifacts/release_bundle_v15/manifest.json)
- [4 个确定性 ZIP](../artifacts/release_bundle_v15/bundles/)
- [独立 repeat manifest](../artifacts/release_bundle_v15_repeat/manifest.json)
- [v0.15 validation.log](../artifacts/release_bundle_v15/validation.log)

正式与 repeat 的 manifest 和 4/4 ZIP 均逐字节一致。干净临时根目录恢复 8 个目标、写回 1,880 个文件，四组 formal/repeat tree manifest 全部匹配；第二次向既有目标恢复被拒绝。固定 SHA-256：

```text
manifest:    573861bc63879e484cff5005700c88e486f3916777c655b4e356101aa0cfa7f8
v0.10 ZIP:   47042f7e203ac598fcaa1f2deeb3248a0148488b8987ec5a6cbee7362d0bd8d8
v0.11 ZIP:   bebd13cc1fead046c37076aa7d0ac25ba64c132a72f6ed3dd0e0032a33e042eb
v0.12 ZIP:   6b5f3e1602923a124c0767db2a006c0817ecd5c239103a0c9d9fbaa64eefec8d
v0.13 ZIP:   605a09b574f69e13cd44d8b52662af0c146b02b72816b6b5a65771320f6cbd24
source:      dd7ed3e47f63f0a45a22c81156aba44f272b6af3699f705c595395a092bfb8ca
```

## 运行 v0.16 Main Study scripted smoke

该 gate 使用 Workspace schedule 与 Retail discounted order 两个现有合成任务，固定同一 semantic policy，比较 R0/R1/R2 的 clean 与 post-commit response-loss 行为。它不调用模型或网络，不能报告为 pilot/main 结果。

```bash
ARL_MAIN_SMOKE_DIR="$ARL_PROJECT/artifacts/main_study_contract_v16_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_main_study_smoke.py \
    --output "$ARL_MAIN_SMOKE_DIR/summary.json" \
    --traces-dir "$ARL_MAIN_SMOKE_DIR/traces"
```

预期输出：

```text
Wrote 12 scripted episodes, 12 traces, and .../summary.json
```

查询合同、结果和 planned/implemented 边界：

```bash
jq '.contract.stages, .aggregate, \
    .validity.catalog.implementation_status_counts, \
    .validity.all_selected_checks_passed, .limitations' \
  "$ARL_MAIN_SMOKE_DIR/summary.json"
```

应看到 12 episodes、0 model calls、0 external network calls；三档 Runtime 的 clean 均为 `2/2` SafeSuccess，R0/R1 fault 为 `0/2`，R2 fault 为 `2/2` 且完成 2 次状态确认。24-task blueprint 只报告 6 个 `existing_core` 和 18 个 `planned`；pilot/main 会在精确模型 slot 未绑定时 fail closed。

正式结果位于 [summary.json](../artifacts/main_study_contract_v16/summary.json)，命令、双版本测试、重复性和覆盖拒绝证据位于 [validation.log](../artifacts/main_study_contract_v16/validation.log)。正式/repeat summary 与 12/12 traces 均逐字节一致；正式 summary SHA-256 为 `9066b70a2ca8b3f37ba05fb5e99fd2c4274418403851c3df09d356225701cf4d`。完整合同、统计口径和当前限制见 [Main Study Contract v0.16](./main-study-v16.md)。

## 运行 v0.17 Pilot scripted preflight

该 gate 从 24-task blueprint 中选择 8 个模板，补齐六类故障的本地 SQLite fixture、reactive oracle、状态 evaluator 与统一 R0/R1/R2 runtime。它不调用模型或网络，也不是 144-episode model pilot。

```bash
ARL_PREFLIGHT_DIR="$ARL_PROJECT/artifacts/pilot_preflight_v17_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_pilot_preflight.py \
    --output "$ARL_PREFLIGHT_DIR/summary.json" \
    --traces-dir "$ARL_PREFLIGHT_DIR/traces"
```

预期输出：

```text
Wrote 48 scripted preflight episodes, 48 traces, and .../summary.json
```

查询结果与机制门禁：

```bash
jq '.aggregate.by_runtime, .aggregate.by_fault_family, \
    .validity.mechanism_counts, .validity.all_selected_checks_passed, \
    .limitations' "$ARL_PREFLIGHT_DIR/summary.json"
```

应看到 clean R0/R1/R2 均 `8/8` SafeSuccess；fault R0 为 `0/8`、R1 为 `1/8`、R2 为 `8/8`，R2-R1 RecoveryRate 差值 `0.875`。三次 confirmation、两次 bounded retry、input/output schema 各一次、一次 compatible rebase 和三步 compensation 均有 typed trace evidence；model/network calls 为 0。

正式结果位于 [summary.json](../artifacts/pilot_preflight_v17/summary.json)，完整验证位于 [validation.log](../artifacts/pilot_preflight_v17/validation.log)。正式/repeat summary 与 48/48 traces 均逐字节一致；summary SHA-256 为 `3976f4ab9cbce28a430d7834cd712a0fe434bfd61c73d8a3af6b2cdeb2822fd4`。设计与限制见 [Pilot Preflight v0.17](./pilot-preflight-v17.md)。

## 运行 v0.19 DeepSeek Flash model pilot

该实验是 8-task 历史模型 pilot。必须先获得单独授权，并在当前 shell 或 secret manager 中设置 `DEEPSEEK_API_KEY`；runner 不接受命令行 key，也不将 key、原始 request 或原始 response 写入证据。模型固定为 `deepseek-api/deepseek-v4-flash/DeepSeek-V4-Flash/non-thinking`，`temperature=0`、`top_p=1`、response cap `512`，每 episode 最多 8 次外部调用、20,000 input tokens、2,000 output tokens 和 `$0.01`。

```bash
ARL_MODEL_DIR="$ARL_PROJECT/artifacts/deepseek_flash_pilot_v19_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_model_pilot.py \
    --workspace "$ARL_MODEL_DIR/study" \
    --summary "$ARL_MODEL_DIR/full-summary.json" \
    --timeout-seconds 60

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/compact_model_pilot_summary.py \
    --input "$ARL_MODEL_DIR/full-summary.json" \
    --output "$ARL_MODEL_DIR/summary.json"
```

中断后使用相同路径加 `--resume`；scheduler 会校验冻结 manifest 和已完成 result/trace 哈希，只执行 pending job。测试 runner 时可加 `--max-new-jobs N` 形成 checkpoint。完整 study 结束后，公开摘要压缩器删除逐 episode 记录，保留完整摘要和 episode 集合的 SHA-256；所有输出路径都拒绝覆盖。

正式 v0.19 实测：

- 8 tasks × 1 seed × 2 conditions × 3 runtimes × 1 model × 3 trials = 144/144 episodes；
- clean `SafePass@3`：R0/R1/R2 均 8/8；fault `SafePass@3`：R0 3/8、R1 1/8、R2 8/8；R2-R1 fault recovery delta `+0.875`，clean delta `0.0`；
- 472 次外部调用，428,517 input + 37,626 output = 466,143 tokens，reasoning tokens 为 0；按 2026-08-08 冻结的 [DeepSeek 定价](https://api-docs.deepseek.com/quick_start/pricing)估算 `$0.0164554936`；
- provider errors `0`、local model protocol errors `0`、144 条 digest-only trace、精确 credential audit 无命中，全部 validity 与模型质量 readiness gate 通过；
- 公开 [summary.json](../artifacts/deepseek_flash_pilot_v19/summary.json) SHA-256 为 `f265eb542d3250473feaf5d0774db1804627d84dbd418ee7fa61062b72b2af9e`；本地完整摘要 SHA-256 为 `3e3d89cfdce912b400ff987d89616779ecc2563f223c1359cf34dc29e67b07a1`，source/trace/study manifest 分别为 `7308794d3ad97ff6468b110eb63e45a37975188b526ead31a70020add05677f8`、`d83cde5d1cbbca4510f598e3dbf84e39fee62f863be67fb6c949a92d09f5982d`、`02c5cd1f14b814f1a0ccdafd29947d0c7fb1a3094604ff10e5882a4d6a50851f`。

v0.18 先以 256-token response cap 跑完同一 144 matrix，但一个 response 以 `finish_reason=length` 截断 tool JSON，产生 1 次 local protocol error；该次 validity/readiness 明确为 false，没有被事后放宽。v0.19 是全新 144-episode 运行，不复用 v0.18 episode。结果解释与失败证据见 [Model Pilot v0.19](./model-pilot-v19.md) 和两版 artifact validation log。

v0.19 readiness 通过不等于 864 main 可以开跑。后续 v0.20 已补齐 24 个 runnable fixture，v0.24 已运行完整 non-thinking slot；历史 v0.25 thinking-high 路径没有完成。v0.27 后来完成双模型 864 matrix 但门禁失败，当前前瞻性运行顺序以 v0.28 Flash + Qwen 合同为准。

## 运行 v0.20 24-task scripted preflight

该路径不调用模型，用固定 reactive oracle 验证全部 24 个 environment/fault/evaluator fixture 和 R0/R1/R2 公平性边界：

```bash
ARL_MAIN_PACK="$ARL_PROJECT/artifacts/main_pack_preflight_v20_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_main_pack_preflight.py \
    --output "$ARL_MAIN_PACK/summary.json" \
    --traces-dir "$ARL_MAIN_PACK/traces"
```

正式结果为 144 episodes、0 model/network calls。三档 Runtime clean 均为 24/24；fault R0/R1/R2 分别为 0/24、4/24、24/24，R2−R1 recovery-rate delta 为 `+0.8333333333333334`。正式/repeat summary 与 144 条 traces 逐字节一致。证据见 [artifact README](../artifacts/main_pack_preflight_v20/README.md) 与 [validation.log](../artifacts/main_pack_preflight_v20/validation.log)。

## 运行 v0.21 mechanism ablation

该路径只运行 faulted R2，比较完整 baseline 与六个 leave-one-mechanism-out 变体：

```bash
ARL_ABLATION="$ARL_PROJECT/artifacts/main_pack_ablation_v21_rerun"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_main_pack_ablation.py \
    --output "$ARL_ABLATION/summary.json" \
    --traces-dir "$ARL_ABLATION/traces"
```

正式结果为 168 episodes。完整 R2 通过 24/24；移除任一预注册机制均变为 20/24，并且只丢失对应的四个目标任务。所有 policy digest 跨变体相同，正式/repeat summary 与 168 条 traces 逐字节一致。证据见 [artifact README](../artifacts/main_pack_ablation_v21/README.md) 与 [validation.log](../artifacts/main_pack_ablation_v21/validation.log)。

## 运行 v0.24 24-task DeepSeek Flash single-slot study

这是经单独授权的完整任务目录模型实验。输出路径必须不存在；key 只能位于进程环境。中断后可对同一 workspace 使用 `--resume`，scheduler 会核验冻结 manifest 与既有 result/trace 哈希。

```bash
ARL_MAIN_SINGLE="$ARL_PROJECT/artifacts/deepseek_flash_main_single_v24_rerun"

env DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:?set in current shell}" \
  PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_main_single_slot.py \
    --workspace "$ARL_MAIN_SINGLE/study" \
    --summary "$ARL_MAIN_SINGLE/full-summary.json" \
    --timeout-seconds 60

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/compact_model_pilot_summary.py \
    --input "$ARL_MAIN_SINGLE/full-summary.json" \
    --output "$ARL_MAIN_SINGLE/summary.json"

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/build_main_single_slot_analysis.py \
    --input "$ARL_MAIN_SINGLE/full-summary.json" \
    --output "$ARL_MAIN_SINGLE/analysis.json" \
    --iterations 10000 --seed 20260808
```

正式结果为 432/432 episodes、1,684 provider calls、1,770,239 tokens、估算 `$0.06379268000000014`，provider/protocol errors 均为 0，14/14 validity checks 通过。Clean `SafePass@3` 在三档 Runtime 均为 18/24；matched fault recovery 在 R1/R2 为 5/18 与 17/18。R2−R1 差值为 `+0.6666666666666666`，10,000 次配对 task-cluster bootstrap 的 95% percentile interval 为 `[0.4444444444444444, 0.8823529411764706]`。

公开 [summary.json](../artifacts/deepseek_flash_main_single_v24/summary.json)、[analysis.json](../artifacts/deepseek_flash_main_single_v24/analysis.json) 与 [validation.log](../artifacts/deepseek_flash_main_single_v24/validation.log) 只保存 aggregate、task rows、digest 和 manifest。完整 summary、432 results、432 digest-only traces 与 state 保持本地忽略。结果解释见 [v0.24 文档](./main-single-slot-v24.md)。这仍只是一个推理配置，不能单独支持双模式结论。

## 历史 v0.25/v0.26 DeepSeek Flash dual-mode amendment

第二配置仍使用 `deepseek-v4-flash`，但精确 revision 为 `DeepSeek-V4-Flash/thinking-high`。先跑覆盖六类故障的 6-job canary；只有 canary validity 为 true，才运行正式 432 轮并与 v0.24 聚合。每个新输出路径都必须不存在。

```bash
ARL_FLASH_DUAL="$ARL_PROJECT/artifacts/deepseek_flash_dual_mode_rerun"

env DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:?set in current shell}" \
  PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_flash_thinking_slot.py \
    --stage canary \
    --workspace "$ARL_FLASH_DUAL/canary/study" \
    --summary "$ARL_FLASH_DUAL/canary/full-summary.json" \
    --timeout-seconds 120

env DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:?set in current shell}" \
  PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_flash_thinking_slot.py \
    --stage formal \
    --workspace "$ARL_FLASH_DUAL/thinking/study" \
    --summary "$ARL_FLASH_DUAL/thinking/full-summary.json" \
    --timeout-seconds 120

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/build_flash_dual_mode_main.py \
    --non-thinking artifacts/deepseek_flash_main_single_v24/full-summary.json \
    --thinking-high "$ARL_FLASH_DUAL/thinking/full-summary.json" \
    --full-output "$ARL_FLASH_DUAL/combined/full-summary.json" \
    --public-output "$ARL_FLASH_DUAL/combined/summary.json" \
    --iterations 10000 --seed 20260809
```

截至 2026-08-09，代码与本地双版本门禁已通过；第一次 canary 因剪贴板不是 API key 得到 6 次 `provider_http_401`，0 accepted calls、0 tokens、`$0`，因此其 validity 为 false，正式 432/864 均未启动。该尝试保留在本地忽略路径，不能进入模型结果。设计、预算差异和解释边界见 [Dual-Mode Main Amendment](./dual-mode-main-v26.md)。

## v0.27 OpenCode Go 双模型失败证据

v0.27 使用 OpenCode Go 的 `deepseek-v4-flash` 与 `mimo-v2.5`，从空目录完成全部 864 episodes：

```bash
env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current shell}" \
  PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_main.py \
    --stage formal \
    --workspace artifacts/opencode_go_main_v27/study \
    --summary artifacts/opencode_go_main_v27/full-summary.json \
    --timeout-seconds 120
```

运行共 3,703,051 tokens，usage-value estimate 为 `$0.3720984904`。一次 MiMo HTTP 503 与另一次 MiMo local `model_protocol_error` 使基础设施 validity 为 false；MiMo clean `SafePass@3` 的 R0/R1 为 16/24 与 17/24，也未达每档 75% readiness 门槛。`build_opencode_go_analysis.py` 正确拒绝输入，没有生成 `analysis.json`。完整证据、hash 与限制见 [v0.27 文档](./opencode-go-main-v27.md) 和 [validation log](../artifacts/opencode_go_main_v27/validation.log)。

## 运行 v0.28 OpenCode Go Flash + Qwen main

v0.28 不复用 v0.27 的 Flash episodes。它在观察 Qwen benchmark outcome 前冻结 `deepseek-v4-flash` + `qwen3.7-plus`、相同 8-call/20k-input/8192-output/`$0.01` logical budget，以及每 logical call 最多两次 transport retry。先运行六类故障 × 两模型的 12-job canary；validity 为 true 后才启动全新 864-job formal：

```bash
ARL_OPENCODE_V28="$ARL_PROJECT/artifacts/opencode_go_flash_qwen_v28"

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current shell}" \
  PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/probe_opencode_go_v28.py \
    --output "${ARL_OPENCODE_V28}_probe/probe.json" \
    --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current shell}" \
  PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v28.py \
    --stage canary \
    --protocol-probe "${ARL_OPENCODE_V28}_probe/probe.json" \
    --workspace "${ARL_OPENCODE_V28}_canary/study" \
    --summary "${ARL_OPENCODE_V28}_canary/full-summary.json" \
    --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current shell}" \
  PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v28.py \
    --stage formal \
    --protocol-probe "${ARL_OPENCODE_V28}_probe/probe.json" \
    --canary-summary "${ARL_OPENCODE_V28}_canary/full-summary.json" \
    --workspace "$ARL_OPENCODE_V28/study" \
    --summary "$ARL_OPENCODE_V28/full-summary.json" \
    --timeout-seconds 120
```

只有 formal 的 infrastructure validity 与 model-quality readiness 同时为 true，才允许运行确认性分析：

```bash
env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/build_opencode_go_v28_analysis.py \
    --input "$ARL_OPENCODE_V28/full-summary.json" \
    --output "$ARL_OPENCODE_V28/analysis.json" \
    --iterations 10000 --seed 20260809
```

本次命令因 Qwen clean readiness 未过而按设计非零退出，且未生成 `analysis.json`。基础设施有效的失败门禁结果可以运行明确标注的探索性分析：

```bash
env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/build_opencode_go_v28_exploratory_analysis.py \
    --input "$ARL_OPENCODE_V28/full-summary.json" \
    --output "$ARL_OPENCODE_V28/exploratory-analysis.json" \
    --iterations 10000 --seed 20260809

env PYTHONPATH="$ARL_PROJECT/src" PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/compact_model_pilot_summary.py \
    --input "$ARL_OPENCODE_V28/full-summary.json" \
    --output "$ARL_OPENCODE_V28/summary.json"
```

实测 protocol probe、12-job canary 和 864-job formal 均完成；18 项 infrastructure validity 全过，0 unrecovered provider/protocol errors，唯一一次 Flash HTTP 503 经预注册 retry 恢复。Flash/Qwen clean `SafePass@3` 的 R0/R1/R2 分别为 18/18/18 与 17/18/17；R2−R1 matched fault-recovery 增量分别为 `+0.667` 与 `+0.660`，探索性 95% task-bootstrap CI 为 `[0.438, 0.882]` 与 `[0.429, 0.875]`。完整处置、hash 与限制见 [v0.28 结果](./opencode-go-main-v28.md) 和 [validation log](../artifacts/opencode_go_flash_qwen_v28/validation.log)。不能在观察结果后静默换模型或把探索性区间写成确认性结论。

## v0.29 三种子 independent holdout

v0.29 不选择性重跑 v0.28 失败任务。它冻结 24 个新 task ID/request 和三个
data seed，并继续使用相同 tool schema、runtime、evaluator、模型 binding 与预算。
完整证据链按以下顺序运行：

```bash
ARL_PYTHON="$(uv python find 3.12)"

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_holdout_v29_preflight.py \
  --output artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --traces-dir artifacts/opencode_go_holdout_v29_preflight/traces

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/compact_model_pilot_summary.py \
  --input artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --output artifacts/opencode_go_holdout_v29_preflight/summary.json
```

最终零模型 gate 实测 432/432 episodes 与 16/16 checks 通过；source manifest 为
`d2b413603354baf07e1c08932b0cb12070fafe77f609f232016636e095ffbf20`。
Provider 阶段继续使用相同 source hash：

```bash
env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/probe_opencode_go_v29.py \
  --preflight-summary artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --output artifacts/opencode_go_holdout_v29_probe/probe.json \
  --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v29.py --stage canary \
  --preflight-summary artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --protocol-probe artifacts/opencode_go_holdout_v29_probe/probe.json \
  --workspace artifacts/opencode_go_holdout_v29_canary/study \
  --summary artifacts/opencode_go_holdout_v29_canary/full-summary.json \
  --timeout-seconds 120

env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v29.py --stage formal \
  --preflight-summary artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --protocol-probe artifacts/opencode_go_holdout_v29_probe/probe.json \
  --canary-summary artifacts/opencode_go_holdout_v29_canary/full-summary.json \
  --workspace artifacts/opencode_go_holdout_v29/study \
  --summary artifacts/opencode_go_holdout_v29/full-summary.json \
  --timeout-seconds 120
```

Formal 算式是 `24 × 3 × 2 × 3 × 3 × 2 = 2,592`。中断后只允许对相同
workspace、参数和 manifest 使用 `--resume`：

```bash
env OPENCODE_GO_API_KEY="${OPENCODE_GO_API_KEY:?set in current process}" \
  PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_PYTHON" scripts/run_opencode_go_v29.py --stage formal --resume \
  --preflight-summary artifacts/opencode_go_holdout_v29_preflight/full-summary.json \
  --protocol-probe artifacts/opencode_go_holdout_v29_probe/probe.json \
  --canary-summary artifacts/opencode_go_holdout_v29_canary/full-summary.json \
  --workspace artifacts/opencode_go_holdout_v29/study \
  --summary artifacts/opencode_go_holdout_v29/full-summary.json \
  --timeout-seconds 120
```

实测结果：

- probe：4 次逻辑调用、4 次网络尝试、0 retry，passed=true；
- canary：36/36，infrastructure validity=true，formal readiness=true；
- formal：2,592/2,592，经 2,322 个既有结果后的 checkpoint resume 完成；
- 10,402 logical calls、10,422 network attempts、18 retries；
- 11,622,114 total tokens，usage-value estimate USD 4.1171332752；
- 两个 Qwen episode 在 bounded retry 后仍为 HTTP 503；四个 Qwen episode
  超过冻结的 USD 0.01 usage-value cap；
- infrastructure validity=false，Qwen 三 seed clean readiness=false；
- Flash/Qwen R2−R1 matched fault-recovery point estimate 为 `+0.6897`/
  `+0.6847`，只作描述性诊断。

确认性与探索性 builder 都先检查 infrastructure validity：

```bash
env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/build_opencode_go_v29_analysis.py \
  --input artifacts/opencode_go_holdout_v29/full-summary.json \
  --output artifacts/opencode_go_holdout_v29/analysis.json \
  --iterations 10000 --seed 20260810

env PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$ARL_PYTHON" \
  scripts/build_opencode_go_v29_exploratory_analysis.py \
  --input artifacts/opencode_go_holdout_v29/full-summary.json \
  --output artifacts/opencode_go_holdout_v29/exploratory-analysis.json \
  --iterations 10000 --seed 20260810
```

两条命令均按设计非零退出并报告
`RuntimeError: v0.29 analysis requires infrastructure-valid input`，没有生成分析文件。
完整处置、逐 seed readiness、失败 episode、恢复审计和哈希见
[v0.29 holdout](./opencode-go-holdout-v29.md) 与
[validation log](../artifacts/opencode_go_holdout_v29/validation.log)。后续不得通过
选择性重跑、删除错误记录、调整预算或降低门槛把这次运行改写为有效。

## 安全边界

- 所有 benchmark world 都不读取真实账户、浏览器会话、真实网络目标或第三方业务系统；
- v0.1–v0.17、v0.20/v0.21 与 v0.29 preflight scripted 路径不需要 API key；v0.18、v0.19、v0.24/v0.25 使用单独授权的 `DEEPSEEK_API_KEY`，v0.27–v0.29 provider runner 使用单独授权的 `OPENCODE_GO_API_KEY`，并只发送本项目合成 payload；
- task、Workspace、Retail 与 Travel 记录均为固定合成数据；
- trace 与公开模型证据只保存 digest 与类型化元数据，不保存 provider request/response 正文；
- fault ID 仅写入 harness/evaluator trace，不出现在 policy observation 或 `StepResult` 中；
- 本实验不包含 prompt injection、attack/defense 或可迁移对抗材料。
