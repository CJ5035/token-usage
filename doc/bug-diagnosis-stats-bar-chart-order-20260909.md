# Bug 诊断报告：用量统计汇总"模型用量"柱状图疑似未按用量排序

- **日期**：2026-09-09
- **状态**：已确认（当前工作区版本未复现乱序；定位到两个真实风险点，见下）
- **严重级别**：P3 轻微（显示层观感问题，无数据错误）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）

---

## 问题描述

用户反馈：用量统计页"汇总"的柱状图好像没有按用量排序，"有的时候"柱状图中间的柱子比底部的柱子更高（更长）。

## 环境信息

- 分支/版本：`main`，工作区有大量未提交修改（`app/web/app.js` 今日 01:51 仍在被外部修改，文件从约 2900 行变为 2479 行）
- 相关模块：
  - 后端聚合：`app/db.py:2921` `report_models()`（四表 UNION + `ORDER BY tokens DESC`）
  - 后端路由：`app/server.py:1385` `_stats_models_payload()` / `app/server.py:1993`
  - 前端渲染：`app/web/app.js:1218` `chartStatsModels()`（Chart.js 横向条形图，`indexAxis: "y"`）
- 复现步骤：统计页 → 展开"全局图表"面板 → 观察"模型用量"柱状图（本次诊断未能复现乱序）

## 实测验证结果（本机真实数据库副本，19 万条记录）

| 验证项 | 方法 | 结果 |
|--------|------|------|
| 后端数据顺序 | 直接调用 `db.report_models()` 及 API（today/yesterday/7d/30d/all 全部 5 个 range） | 全部**严格降序** ✓ |
| 前端渲染顺序 | 浏览器内读取 `chart.getDatasetMeta(0).data[i].y` 像素坐标 | labels[0]（最大值）y=18 在**最顶部**，labels[9]（最小值）y=155 在最底部 ✓ |
| 视觉确认 | 截图"模型用量"面板 | 从上到下递减，排行榜样式正确 ✓ |
| 切 range 端到端 | 浏览器内依次点击 近30天/近7天/全部/今天 | 前三者重建后仍严格降序；"今天"无数据正确显示空态 ✓ |
| Chart.js 渲染方向 | 源码 + 实测双重确认 | 横向条形图 labels[0] 渲染在**顶部**（非底部） |

## 可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | **运行实例加载的是旧版/中间版前端代码** | 高 | 这张柱状图是**未提交的新代码**（`git show HEAD:app/web/app.js` 中不存在 `chartStatsModels`，只有旧版环形图 `chartModel`）；`app.js` 今日凌晨仍在被反复修改。若用户观察乱序的实例是修改前启动的 WebView/浏览器（或命中缓存的旧 app.js），其行为对应的是中间版本，无法保证排序 |
| 2 | **视觉预期差异：降序图"中间比底部高"是必然现象** | 高 | 实测图表为正确降序（第一名在最顶部）。降序排列下第 5 名的柱子**天然比**第 10 名（底部）长。若用户预期"从上往下递增"（或未意识到最长柱在顶部），会把正常降序误判为"没排序" |
| 3 | **前端无防御性排序 + 重渲竞态**（真实缺陷，非当前乱序直接证据） | 中 | `chartStatsModels`（app.js:1218）直接 `models.slice(0, 10)` 渲染，正确性完全依赖后端 `ORDER BY`；`renderStatsCharts`（app.js:1190）同步置位 `chartsRendered` 且无请求序号守卫，快速连续切换 range 时慢响应可能把图表覆盖为旧 range 数据（最终一次渲染后自愈，但中间态图表与页面 KPI 口径不一致） |
| 4 | SQLite 相等 tokens 时排序不稳定 | 低 | `ORDER BY tokens DESC` 无 secondary key，相等值顺序不定；但相等值柱长相等，不会造成"中间高于底部" |

## 验证动作

### 针对原因 1：旧版/中间版前端

- **验证方式**：在看到乱序的实例中强制刷新
- **具体操作**：浏览器访问时按 `Ctrl+Shift+R`（WebView 实例则完全退出应用重新打开）；刷新后在统计页控制台执行：
  ```js
  const c = Chart.getChart(document.getElementById("mr-chart"));
  console.table(c.data.labels.map((l, i) => ({ model: l, tokens: c.data.datasets[0].data[i] })));
  ```
- **预期结果**：若刷新后 tokens 列从上到下递减，则乱序来自旧代码/缓存，当前版本已无此问题。

### 针对原因 2：视觉预期

- **验证方式**：对照柱状图与右侧 `mr-list` 排行榜（app.js:1230，同样数据按序渲染）
- **预期结果**：两者顺序一致（第一名在最上）；柱状图第一根（顶部）最长。若与此描述相符，即属正常降序呈现。

### 针对原因 3：竞态复现

- **位置**：`app/web/app.js:1190`（`renderStatsCharts`）
- **具体操作**：展开全局图表面板后，在"近7天/近30天/全部"之间快速连续点击（间隔 < 接口响应时间），观察图表数据与 KPI 卡口径是否短暂不一致。

## 调用链与依赖分析

```
入口: 统计页展开"全局图表"面板 / 切换 range pill
  → loadStatsSources()                        [app/web/app.js:1024]
    → renderStatsCharts()                     [app/web/app.js:1190]
      → GET /api/stats/models?range=...       [app/server.py:1993]
        → _stats_models_payload()             [app/server.py:1385]
          → db.report_models(range)           [app/db.py:2921]
            → 四表 UNION ALL + GROUP BY model + ORDER BY tokens DESC  ← 排序唯一保障点
      → chartStatsModels(models)              [app/web/app.js:1218]
        → models.slice(0, 10) 原样传入 Chart.js（无前端排序）      ← 观察点
```

- **上游调用者**：`renderStatsCharts` 仅在全局图表面板展开时触发（`chartsRendered` 标志防重入）
- **下游依赖**：`usage_records`、`zcode_usage`、`claudecode_usage`、`codex_usage` 四表 UNION（tokens 口径不同：claudecode 为 input+output，codex 为 total_tokens）
- **影响范围**：若给 `chartStatsModels` 加前端排序，仅影响该图与 `mr-list` 榜单；若改后端 SQL 排序，会影响所有消费 `/api/stats/models` 的视图

## 边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 数据边界 | 某 range 无数据（如"今天"） | `setChartEmpty` 空态占位 | 否 | — |
| 数据边界 | 模型数 > 10 | `slice(0, 10)` 截断 Top10 | 否 | — |
| 排序稳定性 | 两个模型 tokens 完全相等 | 顺序不定（长度相同，观感无差异） | 否 | 如需完全稳定可加 `ORDER BY tokens DESC, model` |
| 并发/竞态 | 快速连续切换 range | 无请求守卫，慢响应可能短暂覆盖图表为旧 range 数据（与页面其余部分口径不一致） | 是（轻微） | `renderStatsCharts` 加请求序号守卫（参考 `loadRecords` 的 `recSeq` 模式） |
| 防御性 | 后端未来改动破坏 ORDER BY | 前端无排序兜底，图会直接乱 | 是（潜在） | `chartStatsModels` 开头加一行降序排序 |
| 版本兼容 | 旧实例 + 新后端 / 缓存 app.js | 行为不可控（本次乱序反馈最可能来源） | 是 | 强制刷新验证；必要时给静态资源加版本参数防缓存 |

## 总结与建议

当前工作区版本经端到端实测（5 个 range 的后端数据、渲染像素坐标、截图、切 range 全链路）**排序正确**，未能复现乱序。最可能的原因是用户观察时实例加载了今日凌晨修改过程中的旧版/中间版前端（该柱状图为未提交新代码），或对降序图的正常呈现（中间柱比底部柱长）产生了误判。

建议两处低成本加固（均需确认后再实施）：
1. `chartStatsModels`（app.js:1218）渲染前加防御性排序 `models = [...models].sort((a, b) => (b.tokens || 0) - (a.tokens || 0));`，不再单纯依赖后端 ORDER BY；
2. `renderStatsCharts`（app.js:1190）加请求序号守卫，消除快速切 range 时旧响应覆盖图表的竞态。

请先在出现乱序的实例上强制刷新复核；若刷新后仍可复现，请提供当时的 range 与截图，我再按原因 4 方向深入排查。
