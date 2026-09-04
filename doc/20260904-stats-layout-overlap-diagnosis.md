# Bug 诊断报告：Stats 页面图表与表格排版错乱（重叠）

- **日期**：2026-09-04
- **状态**：已确认（静态代码分析，证据链闭合）
- **严重级别**：P1 严重（Stats 页核心内容不可读）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）

---

## 问题描述

Stats 页面出现排版错乱（见截图）：

1. 「模型用量」甜甜圈图（mr-chart）脱离卡片，覆盖在「ZCode 本地用量」渠道表格左半部分上；
2. 「用量趋势」三折线图（trend-chart，总费用/总请求(虚线)/总Token）脱离卡片，覆盖在渠道表格中部；
3. 模型明细表随之下移/错位。

截图中两个"漂浮"的图表正是上方 `.two-col` 区域（模型用量 + 用量趋势）里的两个 canvas。

## 环境信息

- 分支/版本：main @ 94860ef（v2.1.0）+ 未提交的多数据源改动（ZCode/DSH/Claude Code 本地用量区块，`app/web/*` 均为工作区改动）
- 相关模块：`app/web/index.html`（page-stats 结构）、`app/web/style.css`（布局）、`app/web/app.js`（图表渲染）
- 复现条件：本地存在 ZCode 数据（`~/.zcode/cli/db/db.sqlite`），使 `#zcode-stats` 卡片由 hidden 变为显示

---

## 可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | `#page-stats` 固定高 flex 列布局中，`.two-col` 的 `flex:1; min-height:0` 被新增的高卡片（zcode/dsh/claudecode-stats）压塌至接近 0 高，卡片内容溢出 | 高 | 未提交改动在 two-col 之后新增 3 个高卡片；`.zcode-stats` 特意加了 `flex-shrink:0`（style.css:435 注释"防被 two-col 的 flex:1 压缩"），说明开发者已意识到压缩问题，但只保护了新卡片，没意识到 two-col 自己会被压塌 |
| 2 | 甜甜圈图/趋势图均为 `responsive:false` + 创建时一次性 `resize()`，在卡片 unhide 压塌容器**之前**量好了大尺寸，之后 Chart.js 不再跟随容器变化 | 高 | app.js:1094、app.js:1125 均 `responsive:false`；window resize 处理器（app.js:1963）只在窗口缩放时触发，不监听布局变化 |
| 3 | `.card` 无 `overflow:hidden`，溢出的 canvas 直接绘制在后续兄弟卡片上 | 中（放大症状，非根因） | style.css:181 仅背景/边框/圆角，无 overflow 裁剪 |
| 4 | zcode-trend 自身尺寸错误 | 低（已排除） | chartZcodeTrend 在 `trendBox.hidden = false`（app.js:725）之后才创建，且容器有 min-height:220px，测量正常；且截图中漂浮图是 3 条数据集（费用/请求/Token），与 trend-chart 一致，zcode-trend 只有 2 条 |

## 根因结论（原因 1+2 共同作用）

**布局压塌链**：

```
#page-stats  height:100% + display:flex column + overflow-y:auto   [style.css:98,103,249]
  子项: ph → kpi-row → detail6 → .two-col(flex:1; min-height:0) → #zcode-stats(flex-shrink:0) → #dsh-stats → #claudecode-stats
```

1. 原设计里 Stats 页只有 4 个子项，`.two-col` 用 `flex:1` 填满视口剩余空间（style.css:248 注释"消除底部空白"），内容永不超高；
2. 本次未提交改动在其后追加 3 个高卡片（zcode-stats 含 5 KPI + 2 表格 + 趋势图，约 700px+），总高远超容器；
3. flex 列溢出时压缩 `flex-shrink>0` 的项：ph/kpi-row/detail6 有自动最小内容高度压不动，`.zcode-stats` 被 `flex-shrink:0` 保护，**只有 `.two-col`（`flex:1` 自带 shrink:1 + 显式 `min-height:0`）吸收全部亏空，被压到接近 0 高**；
4. 甜甜圈图和趋势图在 `loadDashboard()` 阶段创建并 `resize()`（app.js:1101、1147），此时 zcode/dsh/claudecode 卡片仍是 hidden（loadZcodeSummary 等异步返回后才 unhide，app.js:455-457 → 721-725），量到的是未压塌的大尺寸；
5. 卡片 unhide → two-col 被压塌 → 但 `responsive:false` 的 Chart.js 不重测 → canvas 保持旧的大像素尺寸，chart-box 又有 `min-height:180px`（style.css:253）/内联 200/240px → **整块图表溢出 0 高的卡片盒，绘制在下方的 zcode-stats 表格上**（.card 无 overflow:hidden，不裁剪）。

截图逐帧吻合：甜甜圈在左列（grid 1fr）、趋势图在右列（grid 1.6fr）、虚线绿线=总请求、紫色=总Token、蓝色=总费用，与 chartTrend 的 3 个数据集（app.js:1119-1121）完全一致。

---

## 验证动作

### 针对原因 1：two-col 被压塌

- **验证方式**：DevTools 检查元素尺寸
- **位置**：`#page-stats .two-col`（style.css:250）
- **具体操作**：应用内打开 DevTools（或临时在 app.js:457 后加 `setTimeout(()=>console.log(document.querySelector("#page-stats .two-col").clientHeight), 2000)`）
- **预期结果**：若根因成立，`clientHeight` 接近 0（仅几十 px 或 0），而 `.two-col` 内部 chart-box 的 `clientHeight ≥ 180`；同时 `#mr-chart`/`#trend-chart` canvas 的 style height 明显大于其父卡片高度

### 针对原因 1 的反证实验（最快确认）

- **验证方式**：临时把 `#zcode-stats`（index.html:106）保持 `hidden`（或在 renderZcodeSummary 入口直接 return），刷新 Stats 页
- **预期结果**：不显示 ZCode 卡片时布局完全正常 → 证实是新卡片撑高 flex 列导致的压塌

### 针对原因 2：图表未跟随容器

- **验证方式**：DevTools 中执行 `document.querySelector("#page-stats").style.display="block"`
- **位置**：`app/web/style.css:249`
- **预期结果**：two-col 恢复自然高度、图表回到卡片内、重叠消失 → 证实 flex:1 压塌是根因

---

## 调用链与依赖分析

```
入口: switchPage("stats")                                    [app/web/app.js:449]
  → loadDashboard()                                          [app/web/app.js:454]
    → renderStats(data)
      → chartModel(models)   创建甜甜圈 + resize()  ← 此刻 two-col 未被压塌，量到大尺寸 [app.js:1076-1101]
      → chartTrend(trend)    创建趋势图 + resize()  ← 同上                          [app.js:1111-1147]
  → loadZcodeSummary()  (异步)                                [app/web/app.js:455, 667]
    → renderZcodeSummary(data)                                [app.js:702]
      → box.hidden = false; kpis/tables/trendBox 全部 unhide  [app.js:721-725]
        ⇒ #page-stats flex 列重新布局: .two-col 被压塌至 ~0    ← 出错点
        ⇒ 已创建的 canvas (responsive:false) 不重测，溢出绘制   [style.css:250,253; app.js:1094,1125]
  → loadDshUsage() / loadClaudecodeSummary() (异步, 同样 unhide 高卡片, 加剧压塌) [app.js:456-457]
```

### 关键依赖节点

- **上游**：`/api/zcode/summary`、`/api/dsh/usage`、`/api/claudecode/summary` 异步返回时机决定压塌发生时刻（一定晚于图表创建）
- **下游**：window resize 处理器（app.js:1963-1975）是唯一补救入口，但它只在窗口缩放时触发，且 `safeResize` 会把图表缩进仍溢出卡片的 chart-box（min-height:180px），治标不治本

---

## 边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 空值/无数据 | 本地无 ZCode/DSH/Claude 数据（db_found=false 或 fetch 失败） | 3 个卡片保持 hidden，不撑高 flex 列，布局正常 | 否（这解释了为何该 bug 只在有数据的用户环境出现） | — |
| 数据边界 | 渠道/模型名超长 | 已有 `max-width:260px + ellipsis`（style.css:440）防护 | 否 | — |
| 视口边界 | 矮屏/高 DPI 缩放 | 即使没有新卡片，旧布局在视口过矮时 two-col 同样会被压塌溢出（flex:1 + min-height:0 的固有缺陷） | 是（存量隐患，本次改动使其 100% 触发） | 修复时一并消除 |
| 时序/竞态 | 快速切换 range（today/7d/30d/all） | loadDashboard 重建图表时有 seq 防过期（zcodeSumSeq），重建的图表会量到已压塌的容器，resize 到 min-height 盒内，仍溢出 | 是（同一根因） | 随根因修复 |
| 窗口缩放 | 用户拉伸窗口 | safeResize 触发，但只适配窗口 resize 事件，不知道卡片 unhide 引起的布局变化 | 是 | 修复布局后无需额外处理 |
| 主题切换 | 暗色/亮色 | rerenderCharts 重建图表（app.js:1947+），同样量到压塌容器 | 是（同一根因） | 随根因修复 |

---

## 总结与建议

**一句话结论**：Stats 页 `flex:1; min-height:0` 的"填满剩余空间"布局技巧与本次新增的 3 个高本地用量卡片不兼容 —— `.two-col` 被压塌至 0 高，而 `responsive:false` 的两个图表（甜甜圈/趋势图）保持创建时量得的大尺寸溢出卡片，覆盖在下方表格上。

**修复方向（按推荐度排序，待确认后实施）**：

1. **【推荐】取消 Stats 页的填满式 flex 布局**：`#page-stats` 改为普通块级流（或 `.two-col` 去掉 `flex:1; min-height:0`），页面内容自然排列、超高滚动（`overflow-y:auto` 已有）。图表容器高度由 chart-box 的 min-height（180/200/220/240px）决定，与下方卡片解耦，压塌与重叠同时消除。改动仅 style.css:249-253 几行。
2. 【可选加固】在 `renderZcodeSummary`/`renderDsh`/`renderClaudecodeSummary` unhide 卡片后调用一次 `safeResize(cModel); safeResize(cTrend)`，让图表按新布局重测（若采用方案 1 此为冗余，可不做）。
3. 【不建议单独使用】给 `.card` 加 `overflow:hidden` —— 只是遮住溢出，图表会被裁掉看不见，属于掩盖症状。

> 按项目约定，本报告仅为诊断结论；代码修改待用户确认修复方案后另行创建实施文档执行。
