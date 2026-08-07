# BrowserGym runtime/harness 最小复现

本复现只使用 BrowserGym 官方固定提交与 MiniWoB++ 本地静态页面。浏览器上下文强制 `offline=True`，页面入口为 `file://`，不调用模型、不访问真实网站、不使用真实账户。

它验证四件事：

1. 固定版本的 BrowserGym/Playwright/MiniWoB++ runtime 能运行官方本地测试；
2. `reset → observation → step → reward/termination` 路径能完成固定任务；
3. 一次受控 locator timeout 后，同一环境可以继续完成任务；
4. job 状态逐条落盘，中断后只运行未完成 job，已完成结果不变。

## 固定环境

- BrowserGym commit：`9e779f087de9a65668b6974d11f9ce9816026e96`
- MiniWoB++ commit：`7fd85d71a4b60325c6585396ec4f48377d049838`
- Python：`3.12.2`
- `browsergym-core` / `browsergym-miniwob`：`0.14.3`
- Playwright：`1.44.0`
- Chromium：`125.0.6422.26`，Playwright revision `1117`
- Gymnasium：`1.3.0`
- pytest / pytest-playwright：`7.3.2` / `0.8.0`
- 模型调用、配置的外部实验目标：均为 `0`

完整解析版本见 [runtime-versions.log](./results/runtime-versions.log)。

## 建立隔离运行时

下面的 clone 和浏览器下载只用于获取官方依赖；实验运行本身保持浏览器离线。变量名可按本机目录调整。

```bash
ARL_BG_DIR=/absolute/path/to/agent-reliability-lab/reproduction/browsergym
ARL_BG_REPO=/absolute/path/to/BrowserGym
ARL_BG_RUNTIME="$ARL_BG_DIR/.runtime"

git clone https://github.com/ServiceNow/BrowserGym "$ARL_BG_REPO"
git -C "$ARL_BG_REPO" checkout --detach 9e779f087de9a65668b6974d11f9ce9816026e96
git clone https://github.com/Farama-Foundation/miniwob-plusplus.git "$ARL_BG_RUNTIME/miniwob-plusplus"
git -C "$ARL_BG_RUNTIME/miniwob-plusplus" checkout --detach 7fd85d71a4b60325c6585396ec4f48377d049838

uv venv --python 3.12.2 "$ARL_BG_RUNTIME/.venv"
uv pip install --python "$ARL_BG_RUNTIME/.venv/bin/python" \
  "$ARL_BG_REPO/browsergym/core" \
  "$ARL_BG_REPO/browsergym/miniwob" \
  'pytest==7.3.2' pytest-playwright

PLAYWRIGHT_BROWSERS_PATH="$ARL_BG_RUNTIME/ms-playwright" \
  "$ARL_BG_RUNTIME/.venv/bin/python" -m playwright install chromium
```

`.runtime` 是可重建的临时依赖目录，不属于交付物。

## 官方本地测试

从 BrowserGym checkout 根目录运行三个仅引用本地 MiniWoB 资源的官方测试文件：

```bash
env \
  MINIWOB_URL="file://$ARL_BG_RUNTIME/miniwob-plusplus/miniwob/html/miniwob/" \
  PLAYWRIGHT_BROWSERS_PATH="$ARL_BG_RUNTIME/ms-playwright" \
  PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_BG_RUNTIME/.venv/bin/python" -m pytest -q -p no:cacheprovider \
    tests/miniwob/test_click-scroll-list.py \
    tests/miniwob/test_click-menu-2.py \
    tests/miniwob/test_use-colorwheel-2.py
```

实测 `15 passed in 37.09s`，原始输出见 [official-tests.log](./results/official-tests.log)。没有运行包含外部导航的测试。

## 中断与续跑

仍从 BrowserGym checkout 根目录执行。第一阶段在第 4 个 job 后主动结束：

```bash
ARL_BG_RESULTS="$ARL_BG_DIR/results"

env \
  MINIWOB_URL="file://$ARL_BG_RUNTIME/miniwob-plusplus/miniwob/html/miniwob/" \
  PLAYWRIGHT_BROWSERS_PATH="$ARL_BG_RUNTIME/ms-playwright" \
  PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_BG_RUNTIME/.venv/bin/python" "$ARL_BG_DIR/run_browsergym_repro.py" \
    --miniwob-repo "$ARL_BG_RUNTIME/miniwob-plusplus" \
    --state "$ARL_BG_RESULTS/browsergym_study_state.json" \
    --output "$ARL_BG_RESULTS/browsergym_interrupted_summary.json" \
    --stop-after 4
```

第二阶段读取同一状态文件，只运行剩余 5 个 job：

```bash
env \
  MINIWOB_URL="file://$ARL_BG_RUNTIME/miniwob-plusplus/miniwob/html/miniwob/" \
  PLAYWRIGHT_BROWSERS_PATH="$ARL_BG_RUNTIME/ms-playwright" \
  PYTHONDONTWRITEBYTECODE=1 \
  "$ARL_BG_RUNTIME/.venv/bin/python" "$ARL_BG_DIR/run_browsergym_repro.py" \
    --miniwob-repo "$ARL_BG_RUNTIME/miniwob-plusplus" \
    --state "$ARL_BG_RESULTS/browsergym_study_state.json" \
    --output "$ARL_BG_RESULTS/browsergym_repro_summary.json" \
    --resume
```

脚本固定 3 个任务 × seeds `0,1,2`，共 9 个 job。结果见 [RESULTS.md](./RESULTS.md)；机器结果为 [interrupted summary](./results/browsergym_interrupted_summary.json)、[final summary](./results/browsergym_repro_summary.json) 与 [state journal](./results/browsergym_study_state.json)。
