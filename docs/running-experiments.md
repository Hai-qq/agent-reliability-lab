# ARL 实验运行与验证指南

## 环境

- macOS arm64
- Python `3.12.12`（v0.7–v0.15 正式 artifact；v0.1–v0.6 历史 artifact 使用 `3.12.2`）
- Python SQLite runtime `3.50.4`（v0.7–v0.15）
- Ruff `0.15.17`
- 根 project 保持 `0.3.0` 以保留 v0.3 manifest；v0.4–v0.15 使用独立包和源码/结果 manifest
- 第三方 Python runtime dependencies：无

代码只使用 Python 标准库。`pyproject.toml` 声明 `requires-python >= 3.11`；每个正式 artifact 的精确解释器版本保存在自身 `summary.json` 与 `validation.log`。

另以 Python `3.11.15` / SQLite `3.50.4` 运行 v0.15 冻结时的 173 tests，全部通过；v0.7–v0.15 正式实验 JSON 采用固定的 Python 3.12.12 环境。

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

公开 clone 不包含被 `.gitignore` 排除的完整 v0.10–v0.13 树；上述条件分支会先从四个确定性 bundle 恢复并校验它们。本地完整树已存在时不重复恢复。v0.15 冻结时实测 `Ran 173 tests ... OK`，Ruff check/format check 均通过。历史增量的当时测试数和解释器版本保留在各自 `validation.log` 中。

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

## 安全边界

- 不读取真实账户、浏览器会话、网络服务或第三方系统；
- 不需要 API key、token 或模型凭据；
- task、Workspace、Retail 与 Travel 记录均为固定合成数据；
- trace 只保存 digest 与类型化元数据；
- fault ID 仅写入 harness/evaluator trace，不出现在 policy observation 或 `StepResult` 中；
- 本实验不包含 prompt injection、attack/defense 或可迁移对抗材料。
