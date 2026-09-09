# Bug 诊断报告：用量统计页面与用量统计总览渠道颜色不一致排查

- **日期**：2026-09-09
- **状态**：已确认
- **严重级别**：P2 一般（UI 配色一致性缺陷）
- **报告人**：Codex Agent（Bug Diagnosis Skill）
- **涉及项目**：`opencode-go-gauge` (`F:\GitHubs\opencode-go-gauge`)

---

## 问题描述

用户提供两张界面截图反映：
1. 图片 1（用量统计页面）：包含数据源占比条形图、各渠道列表明细及展开柱状图。
2. 图片 2（用量统计总览页面）：包含各渠道配额卡片、分渠道消耗趋势堆叠柱状图、渠道占比环形图及今日趋势图。

现象：用量统计页面的渠道标识色与用量统计总览页面的渠道颜色存在明显不一致。

---

## 现状对比（两页实际呈现颜色）

| 渠道 (Channel / Source) | 「用量统计总览」颜色（图 2） | 「用量统计」页面颜色（图 1） | 冲突状态 |
| :--- | :--- | :--- | :--- |
| **zcode** | **蓝紫色** (`--ch-zcode`: `#6366f1` / `#818cf8`) | **绿色** (`SOURCE_COLOR`: `#34b37e`) | ❌ **严重错位** |
| **commandcode** | **翡翠绿** (`--ch-commandcode`: `#10b981` / `#34d399`) | **紫色** (`SOURCE_COLOR`: `#9a6ff0`) | ❌ **严重错位** |
| **bai** | **琥珀黄/金黄** (`--ch-bai`: `#f59e0b` / `#facc15`) | **天蓝/青色** (`SOURCE_COLOR`: `#4fc3f7`) | ❌ **严重错位** |
| **claudecode** | **品牌陶土橙** (`--ch-claudecode`: `#c2410c` / `#d97757`) | **亮橙色** (`SOURCE_COLOR`: `#e8a33d`) | ⚠️ 色调偏差 |
| **codex** | **梅子紫** (`--ch-codex`: `#c026d3` / `#d946ef`) | **灰蓝色** (`SOURCE_COLOR`: `#6b7488`) | ❌ **严重错位** |

---

## 可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | 前端存在两套独立的颜色常量定义，未统一使用 CSS 变量 | **高 (99%)** | `app.js:293` 硬编码 `SOURCE_COLOR`，而首页总览在 `app.js:2094` 使用 `CH_COLOR`（对应 `style.css` 的 `--ch-*`）。总览页颜色经历过多次调优演化，但用量统计页始终停留在独立的旧静态配色表 |
| 2 | Canvas / SVG 渲染引擎无法直接解析 CSS `var(--ch-*)` | **中 (40%)** | 统计页中的某些子图表若直接读取 `var(...)` 字符串可能在 Canvas 上无法绘制（但统计页目前用的是 HTML/CSS DOM 渲染，已具备使用 CSS 变量能力） |
| 3 | 历史功能迭代遗留独立分支逻辑 | **低 (10%)** | 分层视图作为独立模块上线时，临时定义了 `SOURCE_COLOR`，未接入主设计系统 |

---

## 根因定位与代码证据

### 1. 用量统计总览（首页）的配色方案
- **位置**：`F:\GitHubs\opencode-go-gauge\app\web\style.css` 第 31-37 行及 62-68 行
- **映射对象**：`app/web/app.js` 第 2094-2095 行
```javascript
// app/web/app.js:2094
const CH_COLOR = {
  opencode: "var(--ch-opencode)",
  bai: "var(--ch-bai)",
  commandcode: "var(--ch-commandcode)",
  zcode: "var(--ch-zcode)",
  claudecode: "var(--ch-claudecode)",
  dsh: "var(--ch-dsh)",
  codex: "var(--ch-codex)"
};
```
在 `style.css` 中：
```css
/* 浅色主题 */
--ch-opencode: #4f8ef7;
--ch-bai: #f59e0b;            /* 金黄/琥珀 */
--ch-commandcode: #10b981;    /* 翡翠绿 */
--ch-zcode: #6366f1;          /* 靛蓝/蓝紫 */
--ch-claudecode: #c2410c;     /* Claude 品牌橙 */
--ch-dsh: #64748b;
--ch-codex: #c026d3;          /* 梅子紫 */

/* 深色主题 */
--ch-opencode: #6ba3ff;
--ch-bai: #facc15;
--ch-commandcode: #34d399;
--ch-zcode: #818cf8;
--ch-claudecode: #d97757;
--ch-dsh: #94a3b8;
--ch-codex: #d946ef;
```

### 2. 用量统计页面（分层视图）的配色方案
- **位置**：`F:\GitHubs\opencode-go-gauge\app\web\app.js` 第 293-294 行
```javascript
// app/web/app.js:293
const SOURCE_COLOR = {
  opencode: "#5b8def",
  bai: "#4fc3f7",         // ❌ 依然为天蓝色（总览已是黄色）
  commandcode: "#9a6ff0", // ❌ 依然为紫色（总览已是绿色）
  zcode: "#34b37e",       // ❌ 依然为绿色（总览已是蓝紫色）
  claudecode: "#e8a33d",  // ⚠️ 依然为通用橙色（总览为品牌陶土橙）
  codex: "#6b7488",       // ❌ 依然为灰蓝（总览已是梅子紫）
  dsh: "#8d6e63"
};
```
在分层视图渲染中直接引用 `SOURCE_COLOR`：
- `app/web/app.js:1058`：数据源占比条（`style="flex:${pct};background:${SOURCE_COLOR[s.source_id] || "#6b7488"}"`）
- `app/web/app.js:1063`：图例圆点（`style="background:${SOURCE_COLOR[s.source_id] || "#6b7488"}"`）
- `app/web/app.js:1086`：渠道小进度条（`style="width:${pct}%;background:${SOURCE_COLOR[s.source_id] || "#6b7488"}"`）
- `app/web/app.js:1151`：展开明细的横向柱状图（`const color = SOURCE_COLOR[sourceId] || "#6b7488";`）

---

## 验证动作

### 针对原因 1 的验证：
- **验证方式**：查看 `app.js` 中 `SOURCE_COLOR` 是否能直接复用 `CH_COLOR` 或 `var(--ch-${id})`
- **位置**：`F:\GitHubs\opencode-go-gauge\app\web\app.js:293`
- **验证步骤**：
  将 `SOURCE_COLOR` 改为使用 `var(--ch-...)`：
  ```javascript
  const SOURCE_COLOR = {
    opencode: "var(--ch-opencode)",
    bai: "var(--ch-bai)",
    commandcode: "var(--ch-commandcode)",
    zcode: "var(--ch-zcode)",
    claudecode: "var(--ch-claudecode)",
    dsh: "var(--ch-dsh)",
    codex: "var(--ch-codex)"
  };
  ```
- **预期结果**：
  由于统计页面的占比条、图例点、列表迷你条、展开柱状图均为 HTML DOM 的 `div.style.background` 渲染，支持 CSS 变量。替换后两页面渠道颜色将完全一致，且暗色模式下也能自动同步暗色高亮色值。

---

## 调用链与依赖分析

```
用户访问页面
 │
 ├── 点击「用量统计总览」 (Home)
 │    └── renderHome()
 │         ├── renderQuotaCards()  --> 使用 CH_COLOR (var(--ch-*))
 │         ├── renderTrendChart()  --> 使用 CH_COLOR (var(--ch-*))
 │         └── renderDonutChart()  --> 使用 CH_COLOR (var(--ch-*))
 │
 └── 点击「用量统计」 (Stats)
      └── renderStatsLayeredView()
           ├── 占比条渲染 (line 1058)   --> 错误读取 SOURCE_COLOR[source_id] (硬编码色值)
           ├── 图例圆点 (line 1063)     --> 错误读取 SOURCE_COLOR[source_id] (硬编码色值)
           ├── 渠道列表条 (line 1086)   --> 错误读取 SOURCE_COLOR[source_id] (硬编码色值)
           └── 展开明细条 (line 1151)   --> 错误读取 SOURCE_COLOR[source_id] (硬编码色值)
```

---

## 边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|---|---|---|---|---|
| **主题切换** | 浅色/深色模式切换 | `CH_COLOR` 使用 CSS 变量自适应；`SOURCE_COLOR` 为死色值不会自适应 | 是 | 统一迁移至 `var(--ch-*)`，自动享受暗色主题调光 |
| **新渠道扩充** | 新增渠道未定义颜色 | 均有兜底 `#6b7488` | 否 | 保留 `|| "var(--ch-opencode, #6b7488)"` 兜底 |
| **Canvas 兼容** | 若未来有 Canvas 绘图 | Canvas 不支持直接填入 `var(...)` | 暂无影响 | 当前均为 DOM 样式，如果涉及 Canvas，需通过 `getComputedStyle(document.documentElement).getPropertyValue('--ch-...')` 取值 |

---

## 总结与建议

**问题核心**：`opencode-go-gauge\app\web\app.js` 中维护了两套重复且未同步的渠道颜色定义。总览页使用了随设计演进的 `CH_COLOR` / `var(--ch-*)`，而用量统计页使用了写死且过期的 `SOURCE_COLOR`。

**修复方案建议**：
将 `app/web/app.js` 中的 `SOURCE_COLOR` 统一定义为引用 `var(--ch-*)`，或者直接将 `SOURCE_COLOR` 替换为 `CH_COLOR`，消除双重定义。
