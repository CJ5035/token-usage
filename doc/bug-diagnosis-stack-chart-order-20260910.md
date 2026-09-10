# Bug 诊断报告：首页堆叠柱状图未将占比最大渠道垫底（昨日修复丢失）

- **日期**：2026-09-10
- **状态**：已确认（根因已定位并经代码/版本历史双重取证）
- **严重级别**：P3 轻微（纯展示层观感问题，数据无误）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）
- **关联文档**：[20260909-stack-chart-order.md](20260909-stack-chart-order.md)（昨日实施文档，声称已实施但代码已不存在）、[bug-diagnosis-stats-bar-chart-order-20260909.md](bug-diagnosis-stats-bar-chart-order-20260909.md)

---

## 问题描述

用户截图（2026-09-10）显示：

- **分渠道消耗趋势**（堆叠柱状图）：垫底的是 bai（1.24M，**最小**），zcode（14.43M，**最大**）居中，claudecode（11.14M）压顶——头轻脚重，视觉重心错位；
- **今日趋势 24h**：claudecode 垫底、zcode 在上，最大渠道同样不在底部；
- **渠道占比**环形图：扇区起始顺序为 bai → zcode → claudecode（图例顺序）。

用户预期：占比最大的渠道应堆叠在**最下方**。

## 环境信息

- 分支/版本：`feat/dark-theme-polish`，HEAD `c3c92bb`；`app/web/app.js` 有未提交修改（但与本问题区域无关，diff 未触及三个图表函数）
- 相关模块：
  - 前端渲染：`chartReportStack`（app.js:2730）、`chartReportDonut`（app.js:2762）、`chartReportHourly`（app.js:2801）
  - 后端数据：`report_daily`（app/db.py:2435）、`report_hourly`（app/db.py:2866）
- 复现步骤：首页任意 range/metric，观察三图分段顺序并与"渠道明细"表总量对照

---

## 实测验证结果（代码与版本历史取证）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 当前工作区是否有排序 | 读 app.js:2744 / 2765 / 2811 | 三处均为 `Object.keys(d.series)` **原序渲染，无任何排序** ✗ |
| HEAD 是否有排序 | `git show HEAD:app/web/app.js` 提取 chartReportStack | 同样 `Object.keys(d.series)`，无排序 ✗ |
| 修复是否进过版本库 | `git log --all -S "sort((a, b)" -- app/web/app.js` | 仅命中 v1.0.0 无关提交，**排序修复从未被任何 commit 记录** ✗ |
| 后端 series 键序来源 | 读 db.py:2511 / 2923 | `series.setdefault(r["ch"], ...)` —— 键序 = **查询结果中渠道首次出现的顺序**（数据驱动，与用量大小无关） |
| 昨日实施文档行号 | 20260909-stack-chart-order.md 引用 app.js:2282/2314/2353 | 当前函数已偏移至 2730/2762/2801（+448 行，与同日分层视图回退恢复的大块代码量级吻合） |

**结论**：昨日（2026-09-09）实施文档声称"已实施（方案 A，用户已确认）"的降序堆叠修复，**既不在 HEAD、也不在当前工作区、也从未进入任何 commit**。当前三图完全按后端 `series` 键序（渠道在查询结果中的首现顺序）堆叠，与用量无关——与截图现象完全吻合。

---

## 第一步：可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | **昨日"方案 A"修复未持久化，在 9-09 当天的文件变动中丢失** | 高（已实锤） | 修复只存在于（至多）当时未提交的工作区；当天 `app.js` 经历了"分层视图实施 → 手术式回退（从 git diff `-` 行恢复大块 HEAD 代码）→ 多会话并发编辑 → 深色主题 D1/D3 提交"的连续变动。修复从未被 commit 固化，任一次从中间快照重建文件都会将其冲掉。代码现状（三处无排序）与截图行为互为印证 |
| 2 | **用户昨日验证时看到的是含修复的中间版文件，今日实例回到无排序版本** | 中 | 这解释"昨天确认过修好了、今天又不对了"的体感；不影响今日代码现状的结论，属原因 1 的表现面 |
| 3 | **后端 series 键序按数据首现顺序是设计现状（非固定渠道优先级），前端无排序兜底则顺序必然数据相关** | 高（属背景事实） | db.py:2511/2923 的 `setdefault` 建键逻辑决定了：不同 range、不同日期集合下键序都可能不同（截图中趋势图 [bai,zcode,claudecode] 与 24h 图 [claudecode,zcode,bai] 顺序不一致即为直接证据） |

## 第二步：验证动作

### 针对原因 1：修复丢失（已验证成立）

- **验证方式**：代码检索 + 版本历史检索
- **具体操作**：
  ```bash
  grep -n "Object.keys(d.series)" app/web/app.js        # 3 处（2744/2765/2811）均无 .sort
  git log --all -S "sort((a, b)" -- app/web/app.js      # 无相关命中
  ```
- **预期结果**：确认降序排序逻辑不存在（已确认）。

### 针对原因 1/3 的浏览器复核（可选，端到端复现）

- **验证方式**：首页浏览器 console 执行
  ```js
  Chart.getChart(document.getElementById("report-stack")).data.datasets.map(d => d.label)
  ```
- **预期结果**：返回 `["bai", "zcode", "claudecode"]`（数据首现序），与渠道明细表总量降序 `[zcode, claudecode, bai]` 不符 → 复现。

## 第三步：调用链与依赖分析

```
首页 range/metric 变化
  → loadReportAll（回调）                    [app/web/app.js:2599-2601 调用点]
    → GET /api/report/daily → db.report_daily()      [app/db.py:2435]
      → series.setdefault(r["ch"], ...) [db.py:2511]  ← 键序 = 查询结果首现顺序（与用量无关）
    → GET /api/report/hourly → db.report_hourly()    [app/db.py:2866]
      → series.setdefault(r["ch"], ...) [db.py:2923]  ← 同上
  → chartReportStack(daily)                  [app/web/app.js:2730]
    → Object.keys(d.series).map(...)         [app.js:2744]  ← 无排序，原序即 dataset 顺序
      → Chart.js stacked bar: dataset[0] 垫底，依次向上叠   ← 观察点（现象来源）
  → chartReportDonut(daily)                  [app.js:2762]
    → chs = Object.keys(d.series)            [app.js:2765]
  → chartReportHourly(hourly)                [app.js:2801]
    → chs = Object.keys(d.series)            [app.js:2811]
```

- **上游调用者**：`loadReportAll`（range/metric 切换）与 `rerenderCharts`（app.js:2867-2870，主题/语言切换时用缓存重渲）
- **下游依赖**：后端四表 UNION（usage_records / zcode_usage / claudecode_usage / codex_usage）
- **影响范围**：若按方案 A 重新落地，仅改 `app.js` 三个函数的 dataset/键序构造，共 3 处；后端、渠道明细表、导出等不受影响；`chartReportDonut` 的 `onClick` 索引映射与 `chs`/`data` 同源同序，排序后天然一致

## 第四步：边缘情况检查

| 维度 | 场景 | 现状/重做后行为 | 是否有问题 | 建议 |
|------|------|----------------|------------|------|
| 指标口径 | metric 切 tokens/cost/requests | 方案 A 按当前 `d.series` 求和排序，自动跟随指标 | 否 | — |
| cost 档渠道缺失 | metric=cost 时 codex 系列被省略 | series 键集合变化，排序天然适应 | 否 | — |
| 排序稳定性 | 两渠道 range 总量相等 | 顺序不定（视觉长度相同，无观感差异） | 否 | 如需跨 range 完全稳定可加渠道名次级键（可选） |
| 切 range 顺序变化 | 各档位渠道总量不同 | 同一图内所有柱子分段顺序一致；跨档位顺序可能变 | 否（昨日方案 A 已接受该取舍） | — |
| 空态 | 某图无非零数据 | 空守卫在 `new Chart` 前 return，排序逻辑放守卫之后不受影响 | 否 | — |
| 图例顺序 | 排序后图例随 dataset 顺序变化 | 图例即按总量降序呈现（昨日方案 A 的预期效果之一） | 否 | — |
| 回归验证 | UI 契约/pytest | `scripts/check_codex_ui.cjs`、`tests/` 相关用例需复跑 | 否 | 重做后执行 |

## 总结与建议

**根因**：昨日已确认的"方案 A（按 range 内渠道总量降序、大渠道垫底）"修复未进入版本库，在 9-09 当天分层视图手术式回退与多会话并发编辑 `app.js` 的过程中丢失；当前三图按后端数据首现顺序堆叠，与用量无关。

**建议**：按 [20260909-stack-chart-order.md](20260909-stack-chart-order.md) 方案 A 在当前行号重新落地——`app.js:2744`（chartReportStack）、`app.js:2765`（chartReportDonut）、`app.js:2811`（chartReportHourly），并同步更新该实施文档状态（"已实施"→"重做"）。**修改前需用户确认**（遵守项目规则：先文档确认，后改代码）；本次修复应随确认后的提交尽快进入 commit，避免再次丢失。
