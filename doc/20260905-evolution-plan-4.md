# 实施计划 EVOLUTION-4：切主题后图表/渠道色/模型图标残留旧配色【v3】

- **日期**：2026-09-05（v2：门禁2 第 1 轮意见吸收；v3：第 2 轮 3/3 通过后实施级精确化）
- **依据**：`doc/evolution-diagnosis-4.md`（门禁1 两轮 3/3 通过）+ 评委建议
- **等级**：P1（7/10）
- **改动范围**：`app/web/app.js`（主体，预计 +80/-30 行）+ `app/web/style.css`（两条 transition 规则，共两文件）

## 改动清单

### 1. rerenderCharts() 重构（app.js:2339-2348）

去掉 `if (!state.data) return` 守卫，改为**按模块级缓存判断、无缓存即 no-op**（保护 applyDarkMode:450 与 applyCurrency:460 两个调用方语义）：

```js
function rerenderCharts() {
  // 首页 all: 三图（缓存键控见 §2；cHourly 仅 today/yesterday 有缓存）
  if (!document.getElementById("page-home").hidden && !$("report-all").hidden) {
    if (reportDailyCache) { chartReportStack(reportDailyCache.data, true); chartReportDonut(reportDailyCache.data, true); }
    if (reportHourlyCache) chartReportHourly(reportHourlyCache, true);
  }
  // 首页单渠道: 24h 图（用单渠道 trend 缓存；state.data 陷阱=陈旧 stats 数据误重渲，
  // chartToday 自带空值守卫不会抛错——注释据实修正）
  if (!document.getElementById("page-home").hidden && !$("report-single").hidden && chTrendCache) {
    chartToday(chTrendCache.data, true);
  }
  // 总览页 7 日趋势（v1 清单缺口）
  if (!document.getElementById("page-overview").hidden && ovAccountsCache) chartOvTrend(ovAccountsCache, true);
  // 统计页（chartTrend/chartZcodeTrend/chartClaudecodeTrend 原样保留；chartModel
  // 移入 refreshIcons 统一处理，避免本函数与 refreshIcons 双重销毁重建 cModel）
  if (!document.getElementById("page-stats").hidden && state.data) {
    chartTrend(state.data.trend, true);
    if (zcodeSummaryLast) chartZcodeTrend(zcodeSummaryLast.daily7, true);
    if (claudecodeSummaryLast) chartClaudecodeTrend(claudecodeSummaryLast.daily7, true);
  }
  refreshIcons();   // 图标变体原地换 src + chartModel 重渲（§4，唯一入口）
}
```

**重渲统一关闭 Chart.js 入场动画**：图表创建函数加第二参数 `noAnim`，重建时传 `animation: false`（避免切主题时集体重播生长/扫入动画，与 body .2s transition 动效节奏一致）。hidden 容器零尺寸陷阱（app.js:1416 注释自证）由"仅当前可见子视图重渲"天然规避。

### 2. 模块级缓存（数据源，切主题零网络请求）

| 缓存 | 键控 | 写入点 |
|---|---|---|
| `reportDailyCache` | `{range, metric, data}`（**metric/range 双键**，防切指标后旧数据重渲） | loadReportAll `chartReportDonut(daily)` 之后（await 在 app.js:2134、渲染 2135-2136） |
| `reportHourlyCache` | `{range, data}`；**7d/30d/all 档显式置 null 并跳过重渲** | hourly 分支（app.js:2138-2141） |
| `chTrendCache` | `{channel, range, data}`——**键控写死切换时的 `state.range`，勿写接口 date 参数**（trend 接口 date= yesterday/today 二值，而 state.range 可为 7d/30d/all；若按 date 键控，7d/30d 档读侧校验恒不匹配 → 24h 图残留旧主题轴色） | 单渠道分支 seq 守卫块内（app.js:547 `if (seq !== chSeq) return;` 之后） |
| `ovAccountsCache` | 总览页**原始 `data.accounts`**（chartOvTrend 仅读 daily7，写死此一种避免歧义） | loadOverview ovSeq 守卫块内（app.js:1506 之后） |

**写入与读取防陈旧双保险**：① `loadReportAll` **入口（await 之前）先置空 `reportDailyCache`/`reportHourlyCache`**（该函数现无 seq 守卫，收窄 today→7d 切换在途期间旧档重渲的瞬态窗口）；② **重渲前读侧校验**：使用缓存前比对缓存键与当前 `state.range/state.reportMetric/state.channel`，不匹配即 no-op——快速连点指标（app.js:2105 无守卫入口）响应乱序时保证三图必用当前指标数据。单渠道/总览写入点落在既有 chSeq/ovSeq 守卫块内（最新胜出）。

### 3. DOM 内联快照色改 CSS 变量引用（三处，app.js:2180/2191/2317）

2180/2191/2317 三处模板行内**全部** `chColor()` 内联用法（2180 qb-dot 的 `background:` + 同行 qb-name 的 `color:`、2191 同、2317 渠道名 td 的 `color:`）统一改为 `${CH_COLOR[ch] || "#4f8ef7"}`（fallback 兜底未知渠道，避免 `color:undefined` 静默失效；边界说明：新增渠道须同步 CH_COLOR 与亮暗两套 CSS 变量，否则内联 var() 静默透明而 chColor 回退 #4f8ef7，两者行为不同）。配套给 `.qb-dot`/`.qb-name`（style.css:489-490）与渠道名 td 补 `transition: background .2s, color .2s`，使内联 var() 色的跳变与 body 全局 .2s 主题过渡节奏对齐（6 渠道中 4 个亮暗色值不同）。**`chColor()` 本体不动**——它被 Chart.js 数据集直接消费（app.js:2244/2279/2297），canvas 无法解析 `var()`；图表内渠道色维持"快照+重渲"路径，**两条上色路径不可混用**。

### 4. 图标主题变体切换：原地换 img src（v2 重写，零数据源依赖）

**方案**：`modelIcon()` 生成的 img 自带 `alt=模型名`（app.js:1401）——切主题时对四张表体 tbody 内的 img 按当前主题重算 themed 名后**直接改 `src`**，不重建任何 DOM：

```js
function themedName(m, dark) {   // 封装 app.js:1389-1400 全部逻辑（名称解析 lower/split/map/hy 前缀/
  ...                            //   deepseek 兜底 + 暗色变体选择），modelIcon 与 refreshIcons 共用；
}                                //   勿只抽 1396-1400——muse→meta、hy2/hy3→hy、未知→deepseek 三条映射丢失会 404 破图

function refreshIcons() {   // 唯一入口（applyDarkMode:449 处原调用删除，仅 rerenderCharts 末尾调用一次）
  if (!document.getElementById("page-stats").hidden && state.data) chartModel(state.data.models, true);  // noAnim
  const dark = document.documentElement.dataset.theme === "dark";
  for (const id of ["zcode-model-body", "dsh-model-body", "claudecode-model-body", "records-body"]) {
    document.getElementById(id)?.querySelectorAll("img[alt]").forEach(img => {
      const next = `icons/${themedName(img.alt, dark)}.svg`;   // img.alt 属性经 escapeHtml 写入、DOM 读回原文
      if (img.getAttribute("src") !== next) img.setAttribute("src", next);
    });
  }
}
```

- `chartModel` 从 rerenderCharts 统计分支移出、归入 refreshIcons（消除同帧双重销毁重建，且传 noAnim）；`mr-list`（app.js:1244）随 chartModel 重建覆盖，其变体切换纳入"统计页不回归"走查；

- **records 表体零数据源问题就此消除**（v1 方案"重建 tbody"因 loadRecords 响应写入 DOM 后即丢弃、无模块缓存而不可执行——重拉会违反零网络承诺且异步延迟且重建筛选下拉）；原地换 src 下滚动位置/分页/筛选态天然保持，无需 recordsLast 缓存与 scrollTop 恢复；
- 变体选择逻辑（kimi/gpt/grok/mimo 规则，app.js:1396-1400）抽纯函数 `themedName(name, dark)` 供 modelIcon 与 refreshIcons 共用；
- `chartModel` 调用加 page-stats 可见性门（对齐现行 refreshIcons 行为，避免 hidden 容器无效重建）；
- **重渲收敛**：applyDarkMode 中的 refreshIcons() 调用删除，refreshIcons 仅由 rerenderCharts 末尾调用（消除双调用重复重建）。

## 不做（防止过度设计/回归）

- 不改 `chColor()` 返回值（Chart.js 消费）
- 不动 `applyCurrency` 现有守卫语义（app.js:458-460）
- 不在切主题时重拉任何接口（loadReportAll 重拉会把问题5 的 3.2s 空窗引入主题切换路径）
- all↔单渠道切换的语言同步（UI-11）不在本问题范围；
- `applyCurrency`（app.js:459）同族遗留（切货币后首页图金额/轴刻度残留旧币种格式）**登记进候选池**不并入本次（本计划重构后其修复成本约一行，与问题5 同区域排期时顺带评估）。

## 回滚方案

两文件 `app/web/app.js` + `app/web/style.css`：SDD 任务快照备份至工作区，`diff` 生成增量；异常时按快照还原即可（无 schema/接口变更，回滚零副作用）。

## 测试验证点

1. **静态断言测试**（pytest，参照 test_network_deblocking 的源码断言模式）：app.js 源码含 `reportDailyCache`/`chTrendCache`、**rerenderCharts 不存在顶层 `if (!state.data) return;` 早退守卫**（统计页分支内部保留 `state.data` 判断属预期，勿断言"函数体内不含 state.data"）、三处内联色使用 `CH_COLOR[`；
2. 人工/截图走查（配合本轮截图环境）：
   - 停在首页 all/单渠道页签切主题 → 三图/24h 图轴、图例、渠道色即时切换，**零网络请求**（DevTools Network 面板确认）；
   - 亮→暗→亮往返两次，图表颜色随动、无动画重播；
   - 总览页切主题 → 7 日趋势图重渲；
   - 统计页切主题 → 行为不回归（原有重渲保留）；
   - 记录页/zcode/dsh/cc 表模型图标变体同帧切换，滚动/分页/筛选态不变（含 mr-list 统计页模型表）；
   - 先访问统计页再回首页切主题 → 首页 24h 图显示单渠道数据（非 stats 残留）；
   - 7d/30d 档切主题 → hourly 卡保持隐藏、不报错；
   - 切语言后再切主题 → 无异常；
   - 双入口（顶栏按钮 + 设置页主题 pills）行为一致；
   - **在途场景**：loadReportAll 仍在途（缓存为空）时切主题 → rerenderCharts 安全 no-op，数据到达后以当前主题渲染自愈，无残留无报错；
   - 单渠道 7d/30d 档切主题 → 24h 图随动（chTrendCache 键控 state.range 的回归锚）；
   - muse/hy2/未知模型图标切主题后不破图（themedName 全量解析契约锚）；
   - 切货币后首页图金额/轴刻度即时更新（applyCurrency 复用新重渲路径的可裁决走查，通过则候选池该项销项）；
   - 图标"零网络"口径：**零 /api 接口请求**；图标静态文件首次变体切换允许一次请求（此后 disk cache）；
   - 图标变体：切主题时四张表体图标**同帧切换、零网络请求**，记录页滚动/分页/筛选态完全不动。

## 实施备注（门禁2 第 3 轮建议，SDD 任务卡必须吸收）

1. `chartReportHourly(reportHourlyCache.data, true)`——勿照旧伪码传缓存对象（会 `Object.keys(undefined)` 抛错且中断 rerenderCharts 调用链）；
2. hourly 缓存写入：现网为行内 `await api(...)`（app.js:2141），先赋局部变量再写缓存；置 null 分支与 2142-2143 的 else 卡隐藏对齐；
3. 渠道名 td 的 transition 用限定选择器（如 `#report-table td:first-child` 或专用 class），勿用宽泛 `td`；
4. 静态断言按"用法"分：qb-dot background 与 qb-name color 分别命中 + **反向断言**（三处模板行内不再出现 `${chColor(` 内联 style 用法）；
5. **写入点同样加键校验**（`range === state.range && metric === state.reportMetric` 不匹配即丢弃，根治连点指标响应乱序覆盖；读侧校验退化为纯防御）；
6. noAnim 参数改造函数清单共 9 个：chartToday / chartReportStack / chartReportDonut / chartReportHourly / chartOvTrend / chartTrend / chartZcodeTrend / chartClaudecodeTrend / chartModel；
7. §1 伪码 all 分支补注释指回 §2 读侧校验；
8. applyCurrency 候选池条目补全：单渠道视图 app.js:461 `renderOverview(state.data.totals)` 未传 channel（对比单渠道路径 553 传单渠道 totals），切货币时单渠道 6 格会被全渠道数据覆盖——同族问题一并登记；
9. 验证点补："快速连点指标后切主题 → 三图为当前指标数据且随主题"；跨页自愈锚："首页切主题后进入统计页/记录页，模型图标变体正确"（switchPage 重拉自愈，显式钉住）；
10. applyCurrency 可裁决走查通过后，候选池销项随本问题完成报告登记。
