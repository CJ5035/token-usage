# WorkBuddy 本地导入测试隔离缺陷修复实施计划

- 日期：2026-09-17
- 状态：**已复现并验证修法，待用户确认后实施**
- 影响：测试设施缺陷（非产品 bug），但会让定向调试结果不可信

## 一、问题现象

`tests/test_codex_server.py::test_dashboard_scope_all_dsh_contributes_only_today`
在按 `-k` 筛选子集运行时稳定失败，报出数十万级 token（多次运行值不同）：

```
tests\test_codex_server.py:485:
  assert d_7d["totals"]["total_tokens"] == 130 + 70
E  assert 1112424 == 200      # 另次 805545 / 611818 / 2049353
```

- **单独运行该用例**：通过
- **与前一用例一起运行**：失败（`assert 805545 == 200`）
- **整个文件顺序运行**：40 通过
- **全量套件**：845 通过 —— 完整运行会掩盖该问题

## 二、根因（已程序化验证）

`app/server.py` 有 4 个「读取端点按需触发后台导入」的函数，其中
`_maybe_trigger_workbuddy_import()`（server.py:1431）挂在多个只读端点上
（`/api/dashboard?scope=all`、`/api/report/{windows,daily,hourly,channels,channel-*}`
在 channel 为 `None`/`workbuddy` 时）。

该函数经 `workbuddy_import_async()` 起后台守护线程 → `_sync_workbuddy_local()`
→ `workbuddy_local_api.import_incremental()` → `scan_session_files()`，而
**`WORKBUDDY_PROJECTS` 默认为真实机器目录** `Path.home()/".workbuddy"/"projects"`
（本机实测存在 **33 个真实 .jsonl**）。后台线程把真实用量行写入测试用的临时库，
断言随即读到上万级 token。

关键点：`test_codex_server.py` 的 `api_call` 夹具会 patch
`server._maybe_trigger_codex_import`（35 处），但**从不 patch
`_maybe_trigger_workbuddy_import`**（该文件中出现 0 次）；`_wb_last_import_trigger`
的防抖状态是模块级全局，跨用例累积，因此是否泄漏取决于执行顺序与线程时序 ——
这解释了「单跑通过、配对失败、值随机漂移」。

对照实验（决定性证据）：

| 实验 | 结果 |
| --- | --- |
| 原样跑 `-k dsh` | 失败（611818 / 805545 / 999882，3/3 复现） |
| `WORKBUDDY_HOME` 指向空目录后同跑 | **2 passed** |
| 临时 pytest 插件把 `WORKBUDDY_PROJECTS` 指向空 tmp 目录后同跑 | **2 passed** |
| 合并前本地父提交 `04cc288` 上跑 `-k dsh` | 失败（非合并引入） |
| 更早提交 `8226e6e~1`（触发点尚未引入）上跑 | 2 passed |

## 三、影响范围

命中触发端点、且**未**隔离 WorkBuddy 扫描根的测试文件（共 10 个文件命中端点，
只有 2 个自带隔离）：

| 文件 | 端点命中 | 现有隔离 |
| --- | --- | --- |
| test_codex_server.py | 32 处 | 无（已确认泄漏） |
| test_report_api.py | 7 处 | 无（当前单独运行通过，属运气） |
| test_commandcode_sync.py | 2 处 | 无 |
| test_dsh_ui_contract.py / test_dsh_ui_playwright.py | 1 / 5 处 | 无 |
| test_theme_interactions.py / test_theme_rerender.py | 5 / 1 处 | 无 |
| test_ui_optimizations_20260915.py | 2 处 | 无 |
| test_workbuddy_ui_contract.py | 11 处 | 无 |
| test_workbuddy_local_server.py | 17 处 | **有**（autouse 夹具指向 tmp） |
| test_workbuddy_local_api.py | — | **有**（autouse 夹具指向 tmp） |

同类风险：`codex_api.sessions_dir()`（本机有 348 个真实文件）、
`dsh_api` 的 `~/.dsh/sessions`、`claudecode_api` 的 `~/.claude`。
Codex 侧目前未暴露，仅因各用例手动 patch 了 `_maybe_trigger_codex_import`，
属逐点防御而非结构性隔离。

## 四、修复方案（推荐：conftest 全局 autouse 夹具）

在 `tests/conftest.py` 增加一个 **autouse** 夹具，把「本机采集源」全部重定向到
临时空目录，并重置触发/节流全局状态。这样所有测试默认不触碰真实数据，
个别用例需要真实结构时再自行覆盖（现有 fixture 的 monkeypatch 优先级更高，
不会冲突）。

要点：

1. `WORKBUDDY_PROJECTS` → 空 tmp 目录（治本，覆盖全部 10 个文件）
2. 重置 `server._wb_last_import_trigger = None`（防抖全局跨用例累积）
3. 同步隔离 Codex/DSH/Claude 扫描根，消除同类隐患（可选，建议一并做）
4. 不动产品代码、不动任何现有断言

已在仓库外用临时插件验证：隔离后原失败子集 **2 passed**。

## 五、验证标准

1. `pytest tests/test_codex_server.py -k dsh` → 2 passed（修复前为失败）
2. `pytest tests/ -q` → 全量仍全绿（当前 845 通过）
3. 新增断言锚：隔离夹具生效时，`scan_session_files()` 返回空列表
4. 各文件单独运行与全量运行结果一致（消除顺序依赖）

## 六、风险

低。仅改测试设施，不触碰 `app/` 产品代码；隔离后的空目录让「无本地数据」
成为默认前提，与既有 fixture 的临时库语义一致。唯一注意点是 autouse 夹具
需避免与 `test_workbuddy_local_api.py` 等已自带夹具的文件重复 monkeypatch
（monkeypatch 同名属性后者覆盖前者，行为等价，无冲突）。
