# Bug 诊断报告：统计页 Codex 本地用量 KPI 出现两行完全相同的卡片

- **日期**：2026-09-07
- **状态**：已修复（今日行整体移除，2026-09-07 实施并回归通过）
- **严重级别**：P2 一般（数据展示重复，误导用户以为统计翻倍）
- **报告人**：Codex Agent（Bug Diagnosis Skill）

---

## 问题描述

统计页「Codex 本地用量」区块渲染出**两行完全相同的 KPI 卡片**（总请求 175 / 总 TOKEN
57.69M / 输入 57.57M / 输出 117.4k / 平均输出速度 — / 费用 —），两行无任何"累计/今日"
标识，用户无法区分，看起来像渲染重复 Bug。

## 环境信息

- 运行实例：`D:\绿色版\GoGauge\GoGauge.exe`（数据目录 `D:\绿色版\GoGauge\data\`）
- 复现步骤：统计页 → range 切到「今日」→ 观察 Codex 本地用量区块

---

## 可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | 统计页 range=今日 时，总量行与今日行数据源等价，两行必然重复 | 高（实锤） | 后端 `_codex_summary_payload` 中 `totals = db.codex_totals(range_param)`，`today = db.codex_totals("today")`；当 `range_param == "today"` 时两个调用**完全相同**（`app/server.py:1227-1228`） |
| 2 | 前端两行复用同一渲染函数与同一组标签键，无行标识 | 高（实锤，叠加因素） | `renderCodexSummary` 中两行均由同一个 `cards()` 生成、标签键完全一致（`app/web/app.js:1290-1291`）；task4 实施文档明确"今日行复用同一组既有标签键"，即有意省略了区分标识 |
| 3 | 渲染重复执行导致 innerHTML 叠加 | 低（已排除） | 两行是两个独立容器 `#codex-kpis` / `#codex-today-kpis`，各自整体赋值 innerHTML，不存在追加 |

## DB 实测（决定性证据）

只读查询运行实例数据库副本（`D:\绿色版\GoGauge\data\gousage.db`，2026-09-07）：

```
codex_usage 跨度: 2026-07-29 ~ 2026-09-07，共 827 条

按本地日聚合:
  2026-07-29   289 请求    8.34M tokens
  2026-09-05    51 请求    2.43M tokens
  2026-09-06   312 请求   87.47M tokens
  2026-09-07   175 请求   57.69M tokens   ← 本地今天

全量合计:      827 请求  ~155.9M tokens
```

截图两行 KPI 均为 175 / 57.69M / 57.57M / 117.4k —— **与"今天"单日聚合逐位吻合**，
而非全量 827 / 155.9M。证明：当前统计页 range 处于「今日」，此时总量行（totals）
与今日行（today）就是同一个查询结果，重复是必然的、确定性的。

> 注：默认 range 是 7d（`app.js:253`），7d 档下两行不会相同（7d=538 请求/~147.5M vs
> 今日=175/57.69M）；但 range 切到「今日」即 100% 复现。

## 调用链与依赖分析

```
统计页 range seg（今日/昨天/7d/30d/全部） → state.statsRange   [app.js:2262]
  → loadCodexSummary()                     [app.js:1210]
    → GET /api/codex/summary?range=today
      → _codex_summary_payload("today")    [server.py:1203]
        → totals: db.codex_totals("today") [server.py:1227]  ← 两个键等价
        → today:  db.codex_totals("today") [server.py:1228]
          → codex_totals: WHERE started_at ∈ 本地今日 [db.py:3452]
    → renderCodexSummary(d)                [app.js:1254]
      → kpis.innerHTML      = cards(data.totals)   [app.js:1290]  ← 总量行
      → todayKpis.innerHTML = cards(data.today)    [app.js:1291]  ← 今日行（标签键与上行完全相同）
```

### 关键对照：DSH 双行先例（同样的双行设计，但没有此问题）

DSH 区块（`index.html:138-139`）同样有总量行 + 今日行，但其今日行使用**今日专属标签
键**（`dshKpiTodayInput` 今日输入 / `dshKpiTodayOutput` 今日输出 / `dshKpiTodaySpeed`
今日速度，`app.js:1049-1053`），用户能一眼区分两行口径；Codex 区块两行标签键完全一致。

## 边缘情况检查

| 维度 | 场景 | 是否有问题 | 建议 |
|------|------|-----------|------|
| range=今日 | totals 与 today 等价 | 是 | 今日行应隐藏或与总量行合并（方案A） |
| range=昨天 | totals=昨日、today=今日，两行不同但昨日行无标识 | 是 | 行标识缺失问题在所有 range 下存在 |
| range 切换 | 今日隐藏今日行后，切回 7d 需恢复显示 | 需覆盖 | 隐藏逻辑须放在 renderCodexSummary 内按当次 range 判定 |
| i18n | 新增行标识/今日专属键需中英两份 | 需覆盖 | 对齐 DSH 键命名先例 |
| 刷新生命周期 | revision 轮询/语言/货币切换重渲 | 否 | 复用 codexSummaryLast 重渲路径，逻辑内聚无影响 |
| 空数据 | data.today 全 0 | 否 | 现状已统一渲染 0，不在本 Bug 范围 |

## 修复方向（三选一，待确认）

| 方案 | 改动 | 说明 |
|------|------|------|
| **A（推荐）**：range=今日 时隐藏今日行 + 两行加口径标识 | 仅前端 `app.js`（+ i18n 两键） | 最小改动；今日档不渲染重复行，其余档位两行可区分（如"累计(近7天)" vs "今日"） |
| B：按 DSH 先例给今日行换今日专属标签键 | 前端 `app.js` + i18n | 不解决 range=今日 时两行数值重复，只解决"分不清" |
| C：仿 DSH 加 总量/今日 seg 切换器，仅渲染一行 | 前端 `index.html` + `app.js` + `style.css` | 改动最大，交互与 DSH 对齐 |

> **最终决议（2026-09-07）**：执行比方案 A 更彻底的方案——今日行在所有 range 档位整体移除，后端 today 字段保留（契约不变），全量回归 541 passed。

## 总结与建议

两行 KPI 重复的直接原因是**统计页 range=今日 时后端 totals 与 today 两个键等价**，叠加
**前端两行共用同一组标签键且无行标识**。推荐方案A：`renderCodexSummary` 内当
`data.range === "today"` 时隐藏 `#codex-today-kpis`，其余档位为两行补充口径标识（今日
专属标签键对齐 DSH 先例）。等待用户确认后实施。
