# 实施文档：分渠道消耗趋势堆叠柱状图"头重脚轻"——按用量降序堆叠

- **日期**：2026-09-09（2026-09-10 更新为重做版）
- **状态**：修复已丢失，待重做（方案 A 仍有效；9-09 的修复未进 commit，在当日分层视图回退/多会话编辑中丢失，经 2026-09-10 诊断确认代码不存在）
- **关联诊断**：doc/bug-diagnosis-stats-bar-chart-order-20260909.md、doc/bug-diagnosis-stack-chart-order-20260910.md

## 问题

首页"分渠道消耗趋势"（堆叠柱状图）中，各渠道分段的堆叠顺序是**固定渠道顺序**（zcode → claudecode → codex…，来自后端 `report_daily` 的 series 键顺序），与用量大小无关。Chart.js 堆叠时 dataset[0] 垫底，后面的往上叠。当垫底渠道当天用量小、上层渠道用量大时（如 2026-09-09：zcode 10.2M 垫底、claudecode 25.1M 压顶），图表视觉上头重脚轻。

"今日趋势 24h"（`chartReportHourly`）与"渠道占比"环形图（`chartReportDonut`）使用同一固定顺序，存在同样观感问题。

## 方案（推荐 A）

### 方案 A：按所选范围内渠道总量降序堆叠（大渠道垫底）

- 对每张图，构造 datasets 前按**整个 range 的渠道总量**降序排序：
  ```js
  const chs = Object.keys(d.series).sort((a, b) =>
    d.series[b].reduce((s, v) => s + (v || 0), 0) - d.series[a].reduce((s, v) => s + (v || 0), 0));
  ```
- 特性：
  - 同一张图内所有柱子的分段顺序一致（总量在 range 内固定，不会逐日跳动），跨天可比性保持；
  - 用量最大的渠道恒在底部，视觉重心在下；
  - 图例顺序随 dataset 顺序同步变化（图例即按降序列出，信息呈现更合理）；
  - 切换 range（今天/近7天/…）时各渠道总量不同，顺序可能变化——同屏内仍一致，可接受。
- 修改点（仅前端 app.js，共 3 处，后端不动；行号为 2026-09-10 当前工作区实测，9-09 原行号 2282/2314/2353 已因回退整体偏移失效）：
  1. `chartReportStack`（app.js:2730，datasets 构造在 2744）：`Object.keys(d.series)` → 上述降序 `chs`（需在 `new Chart` 前提出一行 `const chs = ...`）；
  2. `chartReportDonut`（app.js:2762，`const chs = Object.keys(d.series)` 在 2765）：`chs` 加 `.sort(...)` 降序（onClick 索引映射与 chs/data 同源同序，排序后天然一致）；
  3. `chartReportHourly`（app.js:2801，`const chs = Object.keys(d.series)` 在 2811）：同样降序（与趋势图保持一致）。

### 方案 B：每根柱子内部按当天用量排序

每天都是"大渠道垫底"，但同一渠道在不同柱子里的位置会逐日跳动，跨天对比困难。不推荐。

### 方案 C：维持现状

固定渠道顺序，接受头重脚轻观感。

## 验证

1. 用本地数据库副本启动服务，浏览器实测：分渠道消耗趋势、今日趋势、渠道占比三图的分段/图例顺序按总量降序，柱内大段垫底；
2. 截图人工复核；
3. `node --check app/web/app.js` 通过；
4. 跑现有测试：`scripts/check_codex_ui.cjs`（UI 契约）与 `tests/` 下相关 pytest，确认无回归。

## 影响范围

- 仅 `app/web/app.js` 三个图表渲染函数，纯展示层；后端接口、数据、导出等不受影响。

## 2026-09-10 重做记录

- 9-09 实施的排序修复未进 commit，且从未持久化：HEAD 与当前工作区三处均无 `.sort`，`git log --all -S "sort((a, b)"` 无相关命中——在当日分层视图手术式回退与多会话并发编辑 `app.js` 的过程中丢失。取证详见 doc/bug-diagnosis-stack-chart-order-20260910.md。
- 方案内容不变（方案 A），上文修改点行号已更新为当前工作区实测值。
- **提交要求**：本次重做经用户确认执行后，须随当次 commit 固化进版本库，避免再次丢失。
