# 诊断报告 EVOLUTION-4：切主题后图表/渠道色/模型图标残留旧主题配色

- **日期**：2026-09-05
- **维度**：UI 一致性（主题切换一致性）
- **预估等级**：P1（损伤 7/10）
- **状态**：静态证据确认（代码机制完整闭合，非推测）

## 问题现象

暗色/亮色主题切换后，部分图表、表格内渠道色文字、模型图标**保持切换前配色**：

- 停在首页「全部渠道」页签切主题：三张图表（分渠道消耗趋势/渠道占比/今日 24h）坐标轴、图例、网格线全部残留旧主题色；
- 停在首页任意页签切主题：`rerenderCharts()` 整体跳过（见根因①）；
- 总览页「7 日费用趋势对比」图：任何场景切主题都不重渲；
- 记录页/渠道明细表内渠道名颜色、各渠道配额卡色点/渠道名：内联快照色不随主题变；
- 表格内模型图标（kimi/gpt/grok/mimo 的主题变体图片）：不随主题切换变体。

## 根因（三条缺口叠加，全部静态证据确认）

### ① `state.data` 守卫使首页场景 100% 跳过重渲

`app.js:2341-2342`：

```js
function rerenderCharts() {
  if (!state.data) return;      // ← 首页场景恒 return
```

`state.data` **只在非首页路径赋值**：`loadDashboard()` 中 `renderAll(data)` 前后（app.js:575 一带，stats/records 等页的 `/api/dashboard` 响应）。而首页两条分支——all 页签（`loadReportAll()`，app.js:2119）与单渠道分支（app.js:536-557）——**都不写 `state.data`**。

结论：用户**停留在首页（任何页签）点主题按钮** → `applyDarkMode()`（app.js:443-451）→ `rerenderCharts()` → `state.data` 为 null → **整体 return，一个图都不重渲**。这不是偶发场景，而是"在首页切主题"的必然结果。

### ② 重渲清单本身不全（即使 state.data 有值）

`rerenderCharts()` 现有清单（app.js:2343-2351）：

| 图表 | 变量 | 是否在清单 |
|---|---|---|
| 单渠道 24h 趋势（home 单渠道） | `chartToday(state.data.today_trend)` | ✅ |
| 统计页 模型用量/用量趋势 | `chartModel` / `chartTrend` | ✅ |
| 统计页 ZCode/CC 趋势 | `chartZcodeTrend` / `chartClaudecodeTrend` | ✅ |
| **首页 all：分渠道消耗趋势** | `cStack`（chartReportStack） | ❌ |
| **首页 all：渠道占比** | `cDonut`（chartReportDonut） | ❌ |
| **首页 all：今日 24h** | `chartReportHourly` | ❌ |
| **总览页：7 日费用趋势** | `cOvTrendChart`（chartOvTrend） | ❌ |

首页 all 页签（默认页签）的三张图与总览页趋势图不在重渲清单内——Chart.js 图表在创建时以 `cssVar()` 快照取色（轴刻度/网格/图例字色），创建后主题变化对其无影响。

### ③ 内联快照色与图标变体不随主题更新

- `renderChannelTable`（app.js:2317）：`<td style="color:${chColor(r.channel)}">` —— `chColor()` 在渲染时刻读取 CSS 变量的**当前值**并固化为内联样式，主题切换后 DOM 不重建则颜色失效；
- `renderQuotaBar`（app.js:2179-2190）：`qb-dot` 的 `style="background:${chColor(ch)}"`、`qb-name` 的 `style="color:..."` 同理；
- 模型图标主题变体：`modelIcon()`（app.js:1393-1401）按当前主题选择 `kimi-color`/`gpt-color` 等 img src，固化在 innerHTML 中；`refreshIcons()`（app.js:1403-1405）**只重渲统计页 chartModel 图表**，对记录页/明细表内已渲染的 img 无效。

## 用户体验影响

- 暗色用户（主题切换是高频操作之一）在首页切暗色后：白底图表的亮色轴/图例直接画在暗色卡片上，浅色刻度文字在深底上刺眼难读；反向切换同理；
- 渠道明细/配额卡的渠道色点与渠道名错配色板（亮暗两套渠道色板，style.css:31-36 / 56-61），视觉上"脏"；
- 修复收益：一次补齐后所有主题切换场景图表/表格/图标全自动一致。

## 修复方向（供阶段3 细化）

1. `rerenderCharts()` 去掉 `state.data` 守卫或改为按页面容器状态判断；补齐 cStack/cDonut/cHourly/cOvTrendChart 四图（all 页签三图的数据源 `daily`/`hourly` 需缓存于模块级变量，或复用 `loadReportAll()` 重拉）；
2. 内联快照色改为输出 CSS 变量引用（`style="color:var(--ch-zcode)"`），主题切换由 CSS 级联自动生效，无需 JS 重渲；
3. 表格内模型图标：主题切换时重渲所在表格，或 `refreshIcons()` 扩展覆盖各表（记录页/zcode/cc 表）。

## 验证点

- 停在首页 all/zcode 页签切主题 → 三图轴/图例/渠道色即时切换；
- 总览页切主题 → 7 日图重渲；
- 记录页切主题 → 表格渠道色与模型图标变体即时切换。
