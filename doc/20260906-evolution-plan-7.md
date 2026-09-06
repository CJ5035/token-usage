# EVOLUTION-7 实施计划：空数据显示策略统一 + 统计页口径提示

- **问题编号**：问题 7（第三轮候选 #1）
- **依据**：`doc/evolution-diagnosis-7.md` v3（门禁1 三轮通过，streak=2）
- **版本**：v3（门禁2 第 2 轮全票后吸收 5 条非阻塞建议：range 显式传参、断言锚定粒度、干净环境 hint 预期、wb-since 最长拼接实拍、hint 长文案可读性核对；对照表见 `doc/evolution-votes-7-plan.md`）
- **改动原则**：最小化——只动空态守卫、口径 hint、compare 标注/零用量文案三条线；不碰 two-col 断点（EVOLUTION-8）、tooltip/i18n 泄漏（EVOLUTION-9）、rerenderCharts 缓存机制（EVOLUTION-4 既有）

## 1. 改动文件与内容

### 1.1 `app/web/index.html`（约 +9 行）

每个图表容器内加空态占位元素（复用 `.zcode-chart-empty` 先例结构，对照 index.html:128 zcode-trend-box 写法；全部 7 个容器均为 `.chart-box`，style.css:204 已含 `position:relative`，**无需补任何 inline 定位**）：

| 图表 canvas | 容器 | 新增占位 id |
|---|---|---|
| report-stack | 分渠道消耗趋势卡 .chart-box | report-stack-empty |
| report-donut | 渠道占比卡 .chart-box | report-donut-empty |
| report-hourly | 今日趋势(all)卡 .chart-box | report-hourly-empty |
| today-chart | 今日趋势(单渠道)卡 .chart-box | today-empty |
| mr-chart | 模型用量卡 .chart-box | mr-empty |
| trend-chart | 用量趋势卡 .chart-box | trend-empty |
| ov-trend-chart | 总览 7 日费用对比卡 .chart-box | ov-trend-empty |

统计页主区 KPI 行上方加口径 hint（**复用既有 `.scope-hint` 类**，style.css:487——11px/var(--text3)/padding 与既有 hint 语言完全一致，**style.css 零改动**）：
`<div class="scope-hint" id="stats-scope-hint" hidden></div>`
位置：index.html:101 `.ph` 与 :102 `stats-total-cards` 之间——紧贴主区首个全 0 卡上方（体验官 R3 轮"与矛盾源头同视野"要求，不得放页面底部）。

### 1.2 `app/web/app.js`

**A. 七个图表函数加空守卫**（每处 3~5 行，模式对照 chartClaudecodeTrend:1119-1123 的 emptyEl 显隐）：

- 空判定统一为「无任何非零数据点」：
  - `chartReportStack(d)`：`!d || !Object.values(d.series).some(arr => arr.some(v => v > 0))`
  - `chartReportDonut(d)`：`grand === 0`（既有变量）——**在 `new Chart` 之前 return**（centerText 为实例级插件，不建实例即不绘制；占位文案由 `.zcode-chart-empty` 全卡 flex 居中呈现，与 centerText 原锚点视觉连续，体验官 R3 轮确认无碰撞风险）
  - `chartReportHourly(d)` / `chartToday(trend)`：同 stack 判定
  - `chartModel(models)`：既有 `!models.length` 分支内追加 emptyEl 显示（替换纯 return；**已知例外**：models 非空但全 0 值仍渲染空环——维持现状不扩大，测试断言单独锚定）
  - `chartTrend(trend)` / `chartOvTrend`（app.js:1636-1642）：同 stack 判定
- 空时动作：`destroy → null → emptyEl.textContent = t(key) → hidden=false`；非空时 `emptyEl.hidden = true`（先例模式）。
- 占位文案两语义（同一 i18n key 族）+ 档位联动（架构师 R1 轮）：**range 由调用点显式传参，图函数不读全局 state.range**（架构师 R2 轮：await 乱序窗口内 state.range 可能已被切换，读全局会出现数据档位与文案档位错位）——`chartReportHourly(d, emptyKey)` / 调用点：
  - `loadReportAll:2193` 传局部 `range` 快照：`range === "today" ? t("noUsageToday") : t("noDataInRange")`；
  - `rerenderCharts:2410` 传 `reportHourlyCache.range`（该路径键校验已保证 cache.range === state.range）。
  - `chartToday`（单渠道，标题固定「今日趋势 24 小时」）：固定 `t("noUsageToday")`
  - stack/donut/mr/trend/ovTrend：统一 `t("noDataInRange")`（**不做档位联动**——today 档下与 hourly 的文案差异属口径正确的并存，避免图函数感知全局档位的复杂度，见实施备注 3）
- **与 EVOLUTION-4 兼容**：守卫在图函数内部，rerenderCharts（:2402-2427）noAnim 重渲路径自动经过同一守卫（架构师复核：与缓存键控/seq 守卫无交互冲突）；空时缓存键仍写入（数据形态不变，仅渲染层分支）。

**B. renderWindows 零用量文案 + DSH 标注**（:2265-2287，约 +6 行）：

- cmp 渲染优先级（架构师 R1 轮明确）：`insufficient_sample` → 样本不足（既有，最高）；否则 `w.today.tokens === 0` → `t("noUsageToday")`（**无百分比箭头**——可测断言锚点）；否则既有 pct 箭头。
- DSH 口径标注走**通栏标注行 notes 机制**（体验官阻塞项整改：不塞 today 格副行——.wb-s 1/4 宽格折行破版且 spike 时染警示色；`.wb-since` grid-column:1/-1 通栏、est-badge 先例）：
  `if (渲染百分比 && w.compare.includes_dsh_today === true) notes.push(t("cmpExcludesDsh"));`
  notes 行既有结构（:2275-2279）纯文本与 dataSince 同构，**无需新样式类**。

**C. 统计页口径 hint**（约 +20 行）：

- 新函数 `updateStatsScopeHint()`——**纯函数语义**（架构师 R1 轮明确）：显示条件 = **主区全 0**（`state.data && state.data.totals && totals.request_count === 0 && totals.total_cost_usd === 0 && (input+output+reasoning) === 0`）**且 本地渠道区任一有数据**（`zcodeSummaryLast`/`dshUsageLast`/`claudecodeSummaryLast` 中任一存在且其非零用量字段为真——具体字段名实施时对照 renderZcodeSummary/renderDsh/renderClaudecodeSummary 取值路径；**null（未到达/失败）不计入"有数据"，条件不成立即隐藏，靠多点调用自愈**，不引入"保持现状"额外状态）。条件满足 → `textContent = t("statsScopeHint")` + `hidden=false`；否则 `hidden=true`。幂等。
- 调用点：`renderStatsTotal` 末尾、`renderZcodeSummary`/`renderDsh`/`renderClaudecodeSummary` **成功路径末尾与失败 catch 路径**（app.js:818/:1045 置 null 后也调用——架构师 R1 轮补）、`applyLang` 动态重渲段（:351-360 附近）。
- hint 文案（精确限定，PM R1 轮）：中文「主区仅统计 OpenCode 渠道用量；ZCode / Claude Code / DSH 本地用量见下方独立区块（首页"今天"合计已并入今日 DSH 用量，涨跌百分比未含）」+ 英文对应。实施时按 i18n 现有句式微调，保持从句限定明确不误读。
- DSH 就绪瞬态提示（体验官 R2 轮评估项）：**不新增**——EVOLUTION-5 的 swapping+降级已覆盖加载反馈，hint 已解释主区全 0 主因；若 SDD 实施中发现瞬态窗口 >3s 再评估（边界写入实施备注）。

**D. i18n 与语言切换**（I18N.zh / I18N.en 各 4 键 + 3 行）：

- `noUsageToday`：今日暂无用量 / No usage today
- `noDataInRange`：该范围暂无数据 / No data in this range
- `cmpExcludesDsh`：涨跌百分比未含今日 DSH / Trend % excludes today's DSH
- `statsScopeHint`：（见 C）
- **applyLang 顺带重设占位文案**（体验官 R1 轮，防 hint 已翻译/占位未翻译混排）：动态重渲段对当前处于显示态的 emptyEl 重设 `t(key)`（复用 A 的 setChartEmpty 工具，约 3 行——记录各 emptyEl 当前语义 key 或按图函数重渲自然覆盖，实施取简）。
- 已知边界（不在本问题修）：all 页签其余动态区块切语言保持旧语言——EVOLUTION-9 同根，不扩大范围。

### 1.3 `app/server.py`（约 +2 行）

`_report_windows_response`（:1064-1093）dsh 并入分支内：

```python
payload["compare"]["includes_dsh_today"] = bool(dsh_win["tokens"] > 0)
```

- 不重算 pct（诊断方向 3：标注优先，避免分子含 DSH 分母不含的单边放大）。
- 不动 db 层（`insufficient`/`spike` 口径自洽不变——架构师口径协调约束）。
- 非 dsh 并入路径该键不出现（前端 `=== true` 判定安全）；`channel=="dsh"` 重建分支的 `{**payload,...}` 展开保留该键（已核实）。

### 1.4 `tests/test_empty_state.py`（新增，约 150 行）

沿用项目静态断言先例（test_theme_rerender/test_dark_theme 模式）：

1. **空守卫源码断言**：6 个图函数（stack/donut/hourly/chartTrend/chartOvTrend/chartToday）按「无非零数据点」统一口径锚定；**chartModel 单独锚定**（`!models.length` 分支 + emptyEl 显示——PM R1 轮：不按统一口径写死防误报）。
2. **i18n 契约断言**：4 个新 key 在 I18N.zh 与 I18N.en 同时存在；index.html 含 7 个 empty div + stats-scope-hint（class="scope-hint"）。
3. **renderWindows 断言**：**锚定新增分支代码片段本身**（`today.tokens === 0` 分支体不含 `↑` 字符；架构师 R2 轮：勿对 renderWindows 全函数体做反向文本匹配——既有 cmp 箭头行本就含 ↑，防误报/漏报）；**cmpExcludesDsh 出现在 notes 组装处**（wb-since 通栏行，非 .wb-s 副行——体验官阻塞项的防退化锚）。
4. **server 字段断言**：参照 test_dsh_background.py 的 dsh mock 方式，断言 dsh 今日 tokens>0 时 `compare.includes_dsh_today is True`；dsh 无数据时键缺省或 False。
5. **回归锚**：断言 `:root` 既有变量与 renderStatsTotal/renderWindows 函数签名未变（防顺手重构）；断言 style.css 无新增类（复用 .scope-hint 的落实锚）。

## 2. 不改动清单（防范围膨胀）

- **style.css 零改动**（hint 复用 .scope-hint、cmp 标注走既有 wb-since 结构、占位复用 .zcode-chart-empty——三处新 UI 全部复用既有设计语言）
- rerenderCharts / 各缓存变量（EVOLUTION-4 机制）
- loadReportAll 的 swapping/seq 守卫（EVOLUTION-5 机制）
- 暗色 token（EVOLUTION-6 既有）
- two-col 断点、pill 换行、明细表溢出（EVOLUTION-8）
- title tooltip / data-i18n-title（EVOLUTION-9）
- records 页会话口径（备选池）
- db.py（零改动）

## 3. 实施备注（SDD 派发注意）

1. 空判定统一「无非零数据点」，不用 `labels.length===0` 单一条件（防御性统一判定）。
2. donut 空守卫必须在 `new Chart` 之前 return。
3. stack/donut 空文案统一中性 key、不做档位联动（复杂度取舍，架构师 R1 轮建议的"可选项"不采纳，理由：图函数感知全局档位引入新耦合；today 档下 hourly「今日暂无用量」与 stack「该范围暂无数据」并存属口径正确，无矛盾）。
4. emptyEl 引用统一封装小工具 `setChartEmpty(canvasId, emptyId, key)`（7 处复用 + applyLang 重设复用；本问题新增的唯一抽象）。
5. hint 元素**无需任何新样式**（.scope-hint 既有：11px/var(--text3)/padding 2px 0 6px）；**无需补 position:relative**（.chart-box 已含，style.css:204）——两项均为评审确认的"关闭项"，防止实施者画蛇添足。
6. renderDsh 的字段名以函数体实际取值为准（dshUsageLast 数据形态现场核对，不凭本计划记忆）。
7. i18n key 插入位置按 I18N 对象现有分组习惯。
8. 占位 div 初始态显式 `hidden`（防闪现）。
9. `applyCurrency` 重渲路径（:464-465）不影响空守卫，无需改动。
10. chartModel 的 `!models.length` 分支改造时保留 `$("mr-list").innerHTML = ""` 既有行为。
11. cost 指标档下 tokens>0 但成本全 0 显示「该范围暂无数据」为**已知取舍**（语义略宽但优于空网格，不做指标档分叉——PM R1 轮记录）。
12. DSH 瞬态提示：hint 已覆盖主因；瞬态 >3s 的再评估边界如 C 节所述。
13. **chartReportHourly 签名为 `(d, noAnim, emptyKey)`**（架构师 R3 轮）：不得把现有第二参 noAnim 改为 emptyKey（会丢 EVOLUTION-4 主题重渲免动画机制）；emptyKey 统一语义为「传 i18n key 字符串、调用点三元求值、函数内 t() 延迟求值」——loadReportAll:2193 传 `range === "today" ? "noUsageToday" : "noDataInRange"`，rerenderCharts:2410 传 `(reportHourlyCache.data, true, t(cache.range === "today" ? "noUsageToday" : "noDataInRange"))` 或按 t() 延迟约定传 key。

## 4. 测试验证点（用户体验场景对照诊断验收场景）

**实施前置**：先重跑 `python -m pytest tests/ -q` 记录当前基线（架构师 R1 轮：collect 416 项 vs 文档 413 passed 有漂移，以防把既有失败误判为本改动引入）。

| 验收场景 | 验证方式 |
|---|---|
| 1 新用户零数据全页 | 手工：清空 data/ 副本启动 → 首页三图占位「该范围暂无数据」、今日图「今日暂无用量」、统计页占位+hint、总览页占位；donut 空态实拍图核对卡心居中+图例坍缩无碰撞；**切无数据档位显示「该范围暂无数据」锚点**（PM R3 轮门禁1）；**hint 仅在本地渠道区有数据时显示——真·全新环境（~/.zcode、~/.dsh、Claude Code 本地目录均无数据）hint 不显示属正确行为**（PM R2 轮：防实施者误判为缺陷） |
| 2 纯本地渠道用户（dev 库形态） | 手工：dev 库启动 → 统计页主区全 0 时 hint 显示且紧贴 KPI 上方（首屏同视野）；下方 ZCode/DSH/CC 正常；**hint 与右下 zcodeCostHint 同屏语义不混读核对**（体验官 R1 轮）；**hint 长文案 800px 折行后可读性核对**（行距/与 KPI 卡间距，体验官 R2 轮） |
| 3 清晨零用量时段 | 源码断言（today.tokens=0 无箭头）+ 手工：注入 today.tokens=0 响应验证「今日暂无用量」；实拍抓 /api/report/windows 原始响应快照（锁定 R5 路径）；**wb-since 通栏行 DSH 标注在 1280/800px 均不折行破版，并覆盖最长拼接形态（data_since + est-badge + cmpExcludesDsh 三段同现，800px）**（体验官阻塞项整改的验收 + R2 轮补强） |
| 4 DSH 就绪瞬态 | 手工：冷启动 dev 库，观察今天 0→11.31M 切换时占位→图表重建正确、无残留；切主题重渲路径下占位稳定 |
| 5 有数据用户回归 | 手工：有数据形态 → 空守卫零触发、hint 隐藏、涨跌正常显示 |
| 6 语言切换 | 手工：切 English → hint 与已显示占位文案跟随翻译（applyLang 重设路径） |
| 编译与全量 | `node --check app.js` + `python -m pytest tests/ -q` 全量通过（基线见实施前置） |

## 5. 回滚方案

- git 单提交（信息 `product-evolution: 问题7 空态策略统一+口径提示`），异常时 `git revert <commit>` 整体回滚。
- 改动集中在 3 个源文件 + 1 个新测试文件，无迁移/无数据变更，回滚无残留。

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 空守卫误伤有数据场景（判定过宽） | 判定统一「无非零数据点」；验收场景 5 正向回归 |
| hint 条件误显示（时序：Summary 未到达时误判） | 纯函数语义：null 不计入"有数据"，条件不成立即隐藏；多点调用（含 catch 路径）幂等自愈 |
| EVOLUTION-4 重渲路径回归 | 守卫在图函数内部（先例模式，架构师两轮复核无交互冲突）；验收场景 4 |
| server 新字段破坏旧前端兼容 | 前端 `=== true` 判定，字段缺省安全；本仓库前后端同发无版本差 |
| 占位/hint 与骨架屏、swapping 冲突 | 体验官已核实：sk-box 遮罩先于 chartToday 空守卫移除（app.js:1172-1173）；renderSkeletons 的 stats 骨架被 renderStatsTotal 覆盖、hint 在容器之外；swapping 仅 opacity 过渡——均无冲突 |
