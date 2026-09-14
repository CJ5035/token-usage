# Bug 诊断报告：首页三图表连续刷新 3 次 & Codex 本地用量重复"今日"行

- **日期**：2026-09-11
- **状态**：已修复（待人工验收：Task1/2 由并行会话按计划实施，Task3 补齐；全量回归 653 passed，语法门禁通过；代码审查结论见文末）
- **严重级别**：问题1 P2 一般（体验问题，图表反复重绘动画）；问题2 P3 轻微（重复数据行，历史决议未落地）
- **报告人**：Codex Agent（Bug Diagnosis Skill）
- **分支**：`feat/dark-theme-polish`（efead4f）

---

## 问题描述

1. **问题1（图1）**：首页 all 页签的三个图表（分渠道消耗趋势 / 渠道占比 / 今日趋势 24h）
   会"连续刷新 3 次"——即 destroy + 重建并播放完整入场动画，短时间内连续发生多次。
2. **问题2（图2）**：统计页「Codex 本地用量」区块出现**两行 KPI 卡**（第一行 1,670/311.23M
   为所选范围数据，第二行 67/13.15M 为当天数据）。预期：只显示右上角时间选择器所选范围
   的数据，当天行不应一直显示。

---

## 问题1：首页三图表连续刷新 3 次

### 可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | `pollUntilIdle` 空闲分支**双重调用** `loadDashboard`，每次同步完成连续重渲 2 次 | 高（实锤） | `app/web/app.js:2051` `await loadDashboard()` 之后 `app.js:2054` `refreshCodexVisible()`，后者 home 分支再次 `loadDashboard(true)`（`app.js:1615`）。两次调用各自走 `loadReportAll` → 三图 destroy+重建带动画 |
| 2 | DSH 调度器在首页 all 页签**每 15 秒**整页 `loadDashboard(true)`，三图每 15s 重绘一次 | 高（实锤） | `/api/report/windows` 在 home all 请求 (channel=None) 下恒定返回 `dsh_status`（`app/server.py:1383`，`channel in (None, "dsh")` 分支）→ `renderHomeDshStatus` 无条件 `scheduleDshRefresh(status)`（`app.js:1287`）→ 15s 后 `dshSchedulerTick("home")` → `loadDashboard(true)`（`app.js:1141`）→ `loadReportAll` 重建三图 → 再次 `scheduleDshRefresh`，无限循环 |
| 3 | 启动期叠加：`checkState` 先 `loadDashboard` 一次，轮询空闲后又双重刷新——**恰好 3 次** | 高（场景解释） | `app.js:2535-2536`：同步/导入进行中时先 `pollUntilIdle()` 再 `await loadDashboard()`（第 1 次）；轮询到空闲后原因 1 的双重刷新（第 2、3 次）。图1 顶栏"上次同步 刚刚"与该场景吻合 |
| 4 | 每次 `loadReportAll` 都 destroy + `new Chart(...)` 且带入场动画（`animation: undefined`），任何一次重渲都被用户感知为"刷新" | 高（放大因素） | `app.js:2958-2988`（cStack）、`2990-3025`（cDonut）、`3030-3055`（cHourly）；只有切主题走 `noAnim=true`，数据刷新路径全部带动画 |
| 5 | 主题/语言/货币切换 `rerenderCharts` 导致 | 低（已排除） | 仅在用户主动切换时触发一次，且 noAnim 无动画，与"连续 3 次"模式不符 |
| 6 | 窗口 resize 触发 | 低（已排除） | resize 只 `chart.resize()` 不重建实例（`app.js:3135-3155`），无入场动画 |

### "连续 3 次"的精确时序（同步完成场景）

```
用户点击「刷新」/ 自动同步到期 → startSync → pollUntilIdle (2.5s 轮询)
  └─ 检测到空闲 (app.js:2045)
      ├─ await loadDashboard()          ← 第 1 次刷新 (三图重建+动画) [app.js:2051]
      └─ refreshCodexVisible()          [app.js:2054]
          └─ home 分支: loadDashboard(true)  ← 第 2 次刷新 [app.js:1615]
                                            (quiet 仅免 toast, 图表照常重建+动画)
≤15s 后 DSH 定时器到点
  └─ dshSchedulerTick("home") → loadDashboard(true)  ← 第 3 次刷新 [app.js:1131→1141]
      └─ loadReportAll → renderHomeDshStatus → scheduleDshRefresh  ← 重新武装, 循环往复
```

启动场景（打开应用时后台同步/导入进行中，即图1"上次同步 刚刚"）：
`checkState` 的 `await loadDashboard()` 为第 1 次，轮询空闲后第 2、3 次接续 —— **恰好连续 3 次**。

### 验证动作

- **验证方式**：日志（DevTools Console）
- **位置**：`app/web/app.js:2770`（`loadReportAll` 入口）
- **具体操作**：
  ```js
  async function loadReportAll(quiet = false) {
    console.log(`[refresh] loadReportAll #${++allSeq} t=${new Date().toISOString().slice(11, 23)} quiet=${quiet} stack=${new Error().stack.split("\n")[2]}`);
    const seq = ++allSeq;
  ```
- **预期结果**：
  - 原因1成立：同步完成瞬间看到**连续两条**日志，间隔 <100ms，一条 `quiet=false` 一条 `quiet=true`，调用栈分别含 `pollUntilIdle` 与 `refreshCodexVisible`；
  - 原因2成立： thereafter 每 **15s** 一条 `quiet=true`、栈含 `dshSchedulerTick` 的日志，永不停歇；
  - 启动场景：应用启动后总计 **3 条**日志先后出现。

### 调用链与依赖分析

```
[触发A] 同步完成: pollUntilIdle (app.js:2039)
  → loadDashboard()                    [app.js:2051]        ← 刷新#1
  → refreshCodexVisible()              [app.js:2054]
    → loadDashboard(true)              [app.js:1615]        ← 刷新#2 (冗余)

[触发B] DSH 调度: renderHomeDshStatus (app.js:1268)
  → scheduleDshRefresh(w.dsh_status)   [app.js:1287]        ← windows 恒有 dsh_status (server.py:1383)
    → 15s 定时 → dshSchedulerTick("home") [app.js:1131]
      → loadDashboard(true)            [app.js:1141]        ← 刷新#3, 且每 15s 循环

[汇聚] loadDashboard(home+all) → loadReportAll (app.js:2770)
  → chartReportStack   destroy+new Chart(动画) [app.js:2958]  ← 分渠道消耗趋势
  → chartReportDonut   destroy+new Chart(动画) [app.js:2990]  ← 渠道占比
  → chartReportHourly  destroy+new Chart(动画) [app.js:3030]  ← 今日趋势 24h
  → renderHomeDshStatus → scheduleDshRefresh  [app.js:2795→1287]  ← 重新武装触发B
```

### 边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 并发 | 同步完成与 DSH tick 同时到期 | 两个 `loadDashboard` 并发，`allSeq` 守卫只丢弃**后发先至**的旧响应，不阻止重复渲染 | 是 | 修复后单一路径触发即消除 |
| 单渠道页签 | bai/zcode 等页签的 DSH tick | `renderHomeDshStatus(totals.dsh_status)`，非 all/dsh 页签 status 为空 → 不武装定时器 | 否 | 仅 all/dsh 页签受影响 |
| quiet 语义 | `loadDashboard(true)` 被理解为"静默" | quiet 仅免 toast + 免错误占位，**不省略图表重建与动画** | 是（语义误导） | DSH 周期刷新不应走全量重建 |
| 空数据 | 三图空态 | destroy 后显示占位，不抛错 | 否 | — |
| 长期停留 | 用户停在首页 all 不操作 | 每 15s 三图重播入场动画，CPU/GPU 持续消耗 | 是 | 周期刷新应无动画或跳过未变化数据 |

### 修复方向（待确认；含 2026-09-11 review 第 1 轮修正）

| 方案 | 改动 | 说明 |
|------|------|------|
| **A（推荐，两项组合）** | ① **消除同步完成双连发**：删除 `refreshCodexVisible` 的 home 分支（`app.js:1615` `else if (state.page === "home") loadDashboard(true);`），保留 `pollUntilIdle` 空闲分支的 `await loadDashboard()`（`app.js:2051`）作为 home/stats 共同的唯一主刷新入口。⚠️ review 修正：~~不能反向删除 2051~~——`refreshCodexVisible` 的 stats 分支只调 `loadCodexSummary()`，stats 页主区块（stats-total-cards/chartTrend/chartModel）依赖 2051 的 `loadDashboard()`，删除它会造成 stats 页同步后主数据不刷新的回归；删除 home 分支后 home 单次刷新、stats 仍双路各刷各的数据，无重复。② **DSH 周期刷新与首页图表解耦（按页签区分）**：`dshSchedulerTick("home")` 在 **all 页签**不再整页 `loadDashboard(true)`，改为仅拉 `/api/report/windows` 静默更新 `home-dsh-status` 状态条并重新武装调度器；**dsh 页签**保留 `loadDashboard(true)` 但传入 `noAnim`（新增 loadDashboard→loadReportAll 透传参数），保持 §3.4 的 DSH 数据 15s 新鲜度、只去掉可感知动画 | ① home 同步完成 2 次→1 次；② all 页签 15s 循环不再重绘三图。合计改动约 15 行 |
| B（保守） | 仅做 A①；`dshSchedulerTick("home")` 保持 `loadDashboard(true)` 但统一透传 `noAnim` | 保留 15s 数据新鲜度，只去掉可感知动画；图表实例仍每 15s 重建（CPU/GPU 有持续开销） |
| C（兜底） | `loadReportAll` 入口加 2~3s 防抖/去重 | 治标，触发源冗余仍在，不推荐单独使用 |

### Review 记录

- **第 1 轮 (2026-09-11)**：发现方案 A① 原表述（删除 2051 的 `await loadDashboard()`）会使 stats 页同步后主数据
  不刷新（`refreshCodexVisible` stats 分支仅覆盖 Codex 区块），已修正为"删除 refreshCodexVisible 的 home 分支"；
  方案 A② 补充 dsh 页签数据新鲜度区分；更正 `dsh_status` 引用行号（server.py:1412→1383）。

---

## 问题2：Codex 本地用量两行 KPI（今日行常驻）

### 结论先行

**这是 2026-09-07 已诊断并已决议的问题，但修复从未落到当前代码库。**
历史报告 `doc/bug-diagnosis-codex-duplicate-kpi-20260907.md` 最终决议："今日行在所有
range 档位整体移除，后端 today 字段保留（契约不变），全量回归 541 passed"。
但 `git log --all -S "todayKpis"` 显示全仓库（main + 当前分支）只有引入该行的
`bf7472f feat: render codex statistics` 一个提交——**修复代码不存在于任何分支**，
属"已决议未落地（或实施在未提交的工作区被丢失）"。

### 可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | 前端 `renderCodexSummary` 无条件渲染两行：`#codex-kpis` ← `data.totals`（所选范围），`#codex-today-kpis` ← `data.today`（恒为当天） | 高（实锤） | `app/web/app.js:1547-1548`；`app.js:1533` `todayKpis.hidden = false` 无 range 条件 |
| 2 | 后端契约同时下发 `totals` 与 `today` | 高（事实，非缺陷） | `app/server.py:1298-1299`；契约测试 `tests/test_codex_server.py` 固定键集含 `today`，按历史决议保留 |
| 3 | DOM 中存在独立容器 `#codex-today-kpis` | 高（事实） | `app/web/index.html:184`；`tests/test_codex_ui_contract.py:21` 断言该元素存在 |

### 验证动作

- **验证方式**：代码比对 + git 取证（已完成）
- **位置**：`app/web/app.js:1547-1548`
- **具体操作**：
  ```bash
  git log --all --oneline -S "todayKpis" -- app/web/app.js
  # 仅输出 bf7472f（引入），无移除提交 → 20260907 决议未落库
  ```
- **预期结果**：与图2 现象一致——第二行数值恒等于"当天"聚合（`db.codex_totals("today")`），
  不随右上角 range 变化。

### 调用链与依赖分析

```
统计页 range 选择器 → state.statsRange
  → loadCodexSummary()                       [app.js:1463]
    → GET /api/codex/summary?range=<statsRange>
      → _codex_summary_payload               [server.py:1272]
        → totals: db.codex_totals(range)     [server.py:1298]  ← 应显示的行
        → today:  db.codex_totals("today")   [server.py:1299]  ← 恒为当天(冗余行)
    → renderCodexSummary(d)                  [app.js:1507]
      → kpis.innerHTML      = cards(totals)  [app.js:1547]  ← 第一行 (随 range 变)
      → todayKpis.innerHTML = cards(today)   [app.js:1548]  ← 第二行 (恒为当天) ★ 问题行
```

### 边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| range=今日 | totals 与 today 等价 | 两行数值完全相同（历史报告已实锤） | 是 | 移除今日行后自然消解 |
| range=其他档 | 两行不同但第二行无"今日"标识 | 用户误读为重复渲染/统计翻倍 | 是 | 本次用户明确要求仅显示所选范围 |
| 缺数据分支 | `db_found=false` 空态 | `todayKpis` 已被隐藏+清空（`app.js:1522-1523`） | 否 | 移除逻辑与其一致 |
| 契约测试 | `/api/codex/summary` 固定键集 | `today` 键被 `tests/test_codex_server.py` 断言 | 需覆盖 | 后端契约不动（按 20260907 决议），仅前端停止渲染 |
| UI 契约测试 | index.html 元素清单 | `tests/test_codex_ui_contract.py:21` 断言 `codex-today-kpis` 存在 | 需覆盖 | 若彻底删 DOM 需同步改测试；若仅隐藏则不动 |
| 语言/货币切换重渲 | `codexSummaryLast` 重渲路径 | 走同一 `renderCodexSummary` | 否 | 修复内聚于该函数，自动一致 |

### 修复方向（待确认）

| 方案 | 改动 | 说明 |
|------|------|------|
| **A（推荐，最小改动）** | `app.js renderCodexSummary`：删除 `app.js:1548` 的 today 行渲染，`app.js:1533` 改为 `todayKpis.hidden = true`（并可清空 innerHTML）；后端契约、DOM、测试全不动 | 与 20260907 决议"今日行整体移除"效果一致；改动约 2 行；`#codex-today-kpis` 成为永不显示的空容器（保留 DOM 契约） |
| B（彻底移除） | 删除 `index.html:184` + `app.js` 中 `todayKpis` 全部引用 + 更新 `tests/test_codex_ui_contract.py:21` | DOM 干净，但多改一处测试；与历史决议"整体移除"字面更贴合 |

两方案视觉效果相同（今天行不再显示），A 改动面最小且不触碰任何测试。

---

## 总结与建议

1. **问题1**：三图"连续刷新 3 次" = `pollUntilIdle` 空闲分支双重 `loadDashboard`
   （`app.js:2051` + `2054→1615`）叠加 DSH 调度器每 15s 整页刷新（`app.js:1141`），
   每次 `loadReportAll` 都以带入场动画的方式重建三个 Chart.js 实例。推荐方案 A：
   删除 `refreshCodexVisible` 的 home 分支去重（保留 2051 的 `loadDashboard`，stats 页
   主数据刷新不受影响）+ DSH 周期刷新按页签解耦（all 仅刷状态条、dsh 保留刷新但 noAnim）。
2. **问题2**：2026-09-07 已决议移除的 Codex"今日行"从未实际落库。推荐方案 A：前端
   `renderCodexSummary` 停止渲染 today 行（约 2 行改动），后端契约与测试不动。

两个修复均为前端 `app/web/app.js` 小改动，互不耦合，可一次实施、一次编译回归
（`node scripts/check_codex_ui.cjs` / pytest 前端契约测试）。**等待用户确认修复方案后执行。**

## 实施记录（2026-09-11）

- 按实施计划 `doc/20260911-首页图表连续刷新修复与Codex今日行移除实施计划.md` 执行完毕：
  Task1（refreshCodexVisible 移除 home 分支）、Task2（dshSchedulerTick 按页签分流 +
  refreshHomeDshStrip + noAnim 透传）由并行执行会话完成；Task3（renderCodexSummary
  停渲 today 行 + UI 契约测试）补齐；Task4 文档收尾本段。
- 新增回归锚：`tests/test_home_refresh_lifecycle.py`（2 用例）、
  `test_dsh_ui_contract.py::test_dsh_home_tick_avoids_full_dashboard_reload`、
  `test_codex_ui_contract.py::test_codex_summary_renders_only_range_row`；
  `test_empty_state.py` hourly 断言同步 noAnim。
- 验证：`node --check app/web/app.js` 通过；`python -m pytest tests/ -q` 全量
  **653 passed, 0 failed**。
- 已知取舍（方案A② 声明）：首页 all 的渠道明细/KPI 条/三图不再随 DSH 15s 周期自动
  刷新，更新时机收敛为同步完成/切页/切 range/手动刷新。
- 遗留：人工验收清单（实施计划 Task4 Step3 的 6 项）待用户执行；签入待用户确认。
