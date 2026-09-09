# 用量统计页分层视图代码回退实施文档

**文档编号**: 20260909-stats-layered-view-rollback  
**创建日期**: 2026-09-09  
**任务类型**: 代码回退（手术式，非 git 整文件回退）  
**回退对象**: [20260908-stats-layered-view-plan.md](20260908-stats-layered-view-plan.md) 实施计划执行的全部代码改动  
**回退原因**: 分层视图方案导致 Key 维度用量聚合视图缺失（用户原始需求"哪个 Key 用量最大"未满足），用户要求回退代码后另议方向

---

## 一、现状与回退约束

### 1.1 代码现状（已核实）

- 实施计划已执行：新接口（`/api/stats/sources*`、`/api/stats/models`）、新前端视图、`tests/test_stats_sources.py` 均在位
- **未提交任何 commit**（HEAD 仍为 `2cb1c37`），全部改动混在未提交工作区
- 旧代码已被删除：`loadZcodeSummary/renderZcodeSummary` 等四个本地区块渲染器（app.js diff `@@ -845,521 +875,16`，521 行）、`renderStatsTotal/renderDetail6/chartModel/chartTrend`（`@@ -1420,155 +945,43`，155 行）及全部调用点

### 1.2 关键约束（决定回退方式）

**工作区同时混有其他会话的未提交工作，禁止 `git checkout -- <file>` 整文件回退**，会连带销毁以下不属于本计划的工作（均已核实存在）：

| 文件 | 需保留的他人工作 |
|---|---|
| `app/web/style.css` | 渠道配色调整（`--ch-bai/--ch-claudecode/--ch-codex` 等多轮演变，diff `@@ -29`/`@@ -60` 区域） |
| `app/web/index.html` | 记录页改造（来源/渠道/速度列、`rec-source-filter`、`usage-scroll`，diff `@@ -173` 区域——本会话开始前已存在） |
| `app/web/app.js` | titlebar/pywebview/骨架屏等小改动（diff `@@ -6`/`@@ -432`/`@@ -478`/`@@ -538` 区域）、记录页来源筛选（`SOURCE_OPTIONS/syncSourceFilter`，会话开始前已存在） |
| `app/server.py` | claudecode 同步工作（diff `@@ -756`/`@@ -764`/`@@ -781` 区域） |
| `app/db.py` | claudecode/渠道明细工作（534 行新增中仅约 120 行属本计划） |
| `tests/*` | `test_data_since_column_copy_clarified` 等他人用例（diff `@@ -44` 区域） |
| `app/main.py`、`README*` | 与本计划无关（计划未涉及这些文件） |

**回退方法**：手术式逐符号回退——删除计划新增的代码，从 `git diff` 的删除行（即 HEAD 内容）恢复被计划删除的旧代码。旧代码恢复源 = diff `-` 行（与 HEAD 版本一致；这些区域在计划执行前未被他人工作修改的假设已通过 hunk 归属核对确认，执行时逐 hunk 复核）。

---

## 二、回退清单

### 2.1 app/server.py

**删除（计划新增，diff `@@ -1170,6 +1219,109` 函数块）**：
- 注释块 `# 用量统计页数据源分层视图 ...`
- 常量：`_STATS_SOURCE_NAMES`、`_STATS_REMOTE_SOURCES`、`_STATS_LOCAL_TABLE_SOURCES`、`_STATS_ALL_SOURCES`
- 函数：`_weighted_hit_rate`、`_stats_sources_payload`、`_stats_sources_with_dsh`、`_remote_source_detail`、`_local_source_detail`、`_dsh_source_detail`、`_stats_models_payload`

**删除（计划新增路由，diff `@@ -1681`/`@@ -1775`/`@@ -1789` 区域内的计划行）**：
- `/api/stats/sources`、`/api/stats/sources/{id}/detail`、`/api/stats/models` 三组路由注册

**执行时核对**：diff `@@ -1291,14 +1443,16`（`_report_channels_response` 区域 +2 行）——若该 2 行属计划改动（如 DSH 并入逻辑提取），按 diff `-` 行恢复；若属他人工作则保留。

### 2.2 app/db.py

**删除（计划新增，约 120 行）**：
- `source_account_stats`、`source_key_stats`、`source_model_stats`
- `_LOCAL_SOURCE_TABLES`、`local_provider_stats`、`local_model_stats`
- `report_models`

### 2.3 app/web/index.html

**恢复（diff `@@ -97,75 +98,55`，即 page-stats 整段）**：按 diff `-` 行恢复原结构——4 个时间范围 pill（无"昨天"）、`stats-total-cards`、`stats-detail6` Token 构成卡、`mr-dim` 维度切换 + `mr-chart/mr-list` 模型用量、`trend-chart` 用量趋势、**四个本地区块**（`zcode-stats`/`dsh-stats`/`claudecode-stats`/`codex-stats` 及内部全部 id）。

**删除（计划新增）**：`share-card` 占比条、`stats-charts-panel` 全局图表折叠面板、`sources-container`、`empty-zone` 收纳区。

**不动**：`@@ -27`/`@@ -74`/`@@ -173` 三个 hunk（他人工作）。

### 2.4 app/web/app.js

**删除（计划新增）**：
- `state.statsView`（diff `@@ -260` 区域；注意 `state.statsRange` 是旧状态、未被计划移除，**保留**）
- `SOURCE_COLOR` 常量（`@@ -239` 区域）
- I18N 计划新增键（zh/en 两处）。**以 diff `+` 行为准逐键核对**，实际新增集合为：`shareTitle/shareCostNote/globalChartsTitle/trendAllChannels/estimated/costUnavailable/todayOnly/emptySources/accountDist/topKeys/providerDist/viewRecords` **以及** `srcDsh/reasoning/cacheRead/cacheWrite/loading`（执行会话发现缺失后补齐的键）。**删除前先 grep 残留引用**：恢复旧代码后若仍有 `t("reasoning")`/`t("cacheRead")` 等引用则保留对应键，无引用才删
- 新函数块（diff `@@ -1608,13 +1024,235`）：`loadStatsSources/renderStatsSources/expandSource/loadSourceDetail/renderSourceDetail/_dimRows/gotoRecords/renderStatsCharts/renderStatsDetail6/chartStatsModels/chartStatsTrend/cStatsTrend/cStatsModels`
- 新绑定：`#share-metric`、`#stats-charts-head`、`#empty-zone-head`；`stats-pills` 新处理器（恢复旧处理器）
- `switchPage` 的 `loadStatsSources` 调用（`@@ -515` 区域）
- sync 完成回调的新 stats 分支（当前 882 行 `if (state.page === "stats") loadStatsSources().catch(() => {});` 及相关注释）

**恢复（从 diff `-` 行；行号以 diff hunk 锚定，原实施计划中的行号已因执行偏移失效）**：
- `switchPage` stats 分支 5 行：`if (page === "home" || page === "stats") loadDashboard();` + `loadZcodeSummary/loadDshUsage/loadClaudecodeSummary/loadCodexSummary` 四行（diff `-` 行，`@@ -515` 区域）
- sync 完成回调旧 stats 分支：`loadCodexSummary` 调用及其注释行（原"stats→loadCodexSummary"）
- `applyCurrency` 中 `renderStatsTotal/renderDetail6/renderZcodeSummary/renderClaudecodeSummary/renderCodexSummary` 调用行（`@@ -500` 区域）及 `zcodeSummaryLast` 等缓存变量
- `applyLang` 中 claudecode/codex 摘要重渲行（`@@ -384` 区域）
- 四个本地 summary 的 loader/renderer 函数群（`@@ -845,521` 大块，521 行，含 `zcodeSummaryLast/zcodeSumSeq/cZcodeTrend` 等模块级变量）
- `renderStatsTotal/renderDetail6/chartModel/chartTrend/updateStatsScopeHint` 函数群（`@@ -1420,155` 大块，155 行）及其在 `loadDashboard` 回调、可见性/resize 分支的调用
- `#mr-dim`/`#dsh-dim` 的 `addEventListener` 绑定块（**已被执行删除，仅存在于 diff `-` 行**）
- stats-pills 旧处理器（联动 `loadDashboard` 与 `statsRange`；恢复后 645 行 `state.statsRange` 读取恢复正常——当前实现中该值因新处理器不再更新而陈旧，回退顺带修复）

**执行时核对**：diff `@@ -1576`/`@@ -1589`/`@@ -1623`（loadSessions/loadRecords 区域）——按 hunk 内容归属判断，与计划无关则保留。

### 2.5 app/web/style.css

**删除（计划新增）**：`.share-card/.share-head/.share-bar/.share-seg/.share-legend/.share-dot/.share-note`、`.panel/.panel-head/.panel-body/.arrow`（计划新增部分）、`.source-panel` 系列、`.badge/.badge-muted`、`.detail-grid/.detail-block/.dim-*`、`.src-link`、`.empty-zone/.zone-head/.zone-body/.empty-src`。

**恢复（从 diff `-` 行）**：被计划删除的 `.zcode-stats/.dsh-stats/.claudecode-stats/.codex-stats` 系列及 `.zcode-missing` 等样式块。

**不动**：渠道配色 hunks（`@@ -29`/`@@ -60`）。

### 2.6 tests/

- **删除**：`tests/test_stats_sources.py`（计划新建）
- **恢复**：`tests/test_codex_ui_contract.py` 的 `test_codex_stats_nodes`（diff `@@ -15` hunk；`@@ -44` hunk 是他人用例，保留）
- **执行时核对**：`test_dark_theme.py`/`test_i18n_consistency.py`/`test_report_api.py`/`test_zcode_sync.py` 等 diff hunks 逐个归属判断——仅回退计划相关行（如 dark_theme 中 `.badge` 对比度用例若为计划新增则回退）

---

## 三、验证标准

1. **符号清零**：`grep -rn "statsView\|loadStatsSources\|SOURCE_COLOR\|_stats_sources\|_STATS_\|source_account_stats\|report_models\|_LOCAL_SOURCE_TABLES\|gotoRecords\|share-bar\|empty-zone\|stats-charts-panel" app/ tests/` → 0 命中
2. **旧功能回归**：`grep -n "function loadZcodeSummary\|function renderStatsTotal\|function chartModel\|function chartTrend\|function renderDetail6\|zcode-stats" app/web/app.js app/web/index.html` → 全部命中（旧代码已恢复）
3. **编译**：`python -m py_compile app/server.py app/db.py` 通过；`node --check app/web/app.js`（有 node 时）
4. **测试**：`python -m pytest tests/ -q` 通过（回退后旧测试全部恢复有效）
5. **冒烟**：启动服务，统计页显示旧结构（KPI 卡 + Token 构成 + 模型用量含维度切换 + 用量趋势 + 四个本地区块），记录页正常
6. **他人工作无损**：`git diff -- app/web/style.css` 仍含渠道配色改动；`rec-source-filter` 等仍在

## 四、执行顺序

1. server.py → 2. db.py → 3. index.html → 4. app.js（最大，含两段大块恢复）→ 5. style.css → 6. tests → 7. 验证

**⚠️ 中间态警告**：步骤 3-6 期间 DOM（旧结构）、JS（新旧混合）、测试（断言新旧交替）不一致——**期间不可启动应用、不可跑 UI 契约测试**（`#share-metric` 等绑定对不存在元素 null 解引用会中断初始化）。每步完成后只做 grep 符号核对与 `py_compile`/`node --check`，全量 pytest 与冒烟仅在步骤 7 执行。

## 五、风险与备注

- 恢复源是 `git diff` 删除行（= HEAD 内容）。若计划执行前的"他人未提交工作"恰好修改过被删除区域，恢复 HEAD 版本会丢失那部分——已通过 hunk 归属核对（被删区域 hunk 均为计划 Task 9 的删除动作），执行时若发现 `-` 行中混有与计划无关的修改，逐行判断保留
- **行号失效**：本文档及原实施计划中引用的 app.js 行号（如 2322/2328、530-536、1379）均为计划执行前位置，执行后已整体偏移；一切定位以 diff hunk（`@@ -a,b +c,d`）与符号名为准
- 计划文档 `20260908-stats-layered-view-plan.md` 已于今日误删后从上下文完整恢复（含评审记录），并加"回退存档"说明，保留作历史参考
- 回退后 Key 维度需求（"哪个 Key 用量最大"）回到未解决状态，后续方向（渠道面板下钻 / 独立 Key 视图）另行讨论，不在本文档范围

## 六、评审修订记录

- **R1-R2（2026-09-09）**：4 项修复——① i18n 回退键清单补全（执行会话实际新增含 `srcDsh/reasoning/cacheRead/cacheWrite/loading`）并增加"删除前 grep 残留引用"协议；② 恢复清单补 sync 完成回调旧 stats 分支（`loadCodexSummary`）；③ 行号失效说明（以 diff hunk 与符号定位，原行号仅历史参考）；④ 新增中间态警告（步骤 3-6 期间不可启动应用/跑 UI 契约测试）。另核实 `state.statsRange` 未被计划移除（保留），且回退恢复旧 pills 处理器后顺带修复当前实现中 `statsRange` 不更新的陈旧读取问题。
