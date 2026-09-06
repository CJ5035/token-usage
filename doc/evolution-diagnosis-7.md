# EVOLUTION-7 诊断报告：空数据显示策略混乱 + 统计页口径矛盾

- **候选编号**：问题 7（第三轮候选 #1）
- **版本**：v3（门禁1 第 2 轮全票后吸收 9 条非阻塞建议；对照表见 `doc/evolution-votes-7.md`）
- **预估等级**：P2（6.5/10）——诊断后**维持**
- **诊断方式**：截图走查（.probe/ui-shots-v3/ 03/04/05/07/08/10）+ 静态源码复核（codegraph + sed 逐函数）+ 运行中服务实测（curl /api/report/windows 与 /api/dashboard 对照）
- **问题仍存在验证**：✅ 2026-09-06 走查截图即最新状态（分钟级）

## 1. 问题陈述

同一界面并存四种互不一致的"无数据"表现，且统计页主区（OpenCode 口径）与同屏下方本地渠道区（ZCode/ClaudeCode/DSH）数据矛盾无任何解释；零数据场景下出现语义荒谬的涨跌标识（「今天 0 ↑100% vs 昨日同时段」）。

## 2. 根因分析

### R1【静态证据确认】首页 all 页签三图无空数据守卫 → 空轴/孤 0 伪影

`app.js:2296-2319 chartReportStack`、`:2321-2349 chartReportDonut`、`:2353-2372 chartReportHourly` 三个函数**无条件 `new Chart(...)`**：
- series 为空时 stack/hourly 渲染出带 Y 轴刻度的空网格（截图 03/04 实证伪影刻度 `1 1 1 1 1 0 0 0 0 0`——Chart.js 对空数据仍计算默认轴界）；
- donut 无扇区时，centerText 插件（`:2327-2336`）仍执行 `ctx.fillText(fmtTokens(grand=0))` → 卡片中央孤零零一个大"0"（截图 03 实证）。

### R2【静态证据确认】留白式空守卫（守卫动作是"留白"而非占位/藏卡）

- `app.js:1230 chartModel`：`if (!models || !models.length) { cModel = null; $("mr-list").innerHTML = ""; return; }`——环形图销毁、排行列表清空，但**卡片框架保留** → 整卡只剩标题+维度 pill+大片空白（截图 07 实证）。
- `app.js:1266 chartTrend`：`if (!trend || !trend.length) { cTrend = null; return; }` 同样留白（截图 07/10 实证）。
- `app.js:1636-1642 chartOvTrend`（账号总览「7 日费用对比」卡）：`if (!dated.length) return;`——destroy 后直接返回，卡片保留标题+整片空白，与本组损伤完全同型（候选清单 #7 已列；总览页需开启「账户总览面板」开关，本轮走查未实截，静态证据充分）。
- 800px 窄窗下统计页 two-col 不折叠（EVOLUTION-8 范围），空白卡被拉得更高更显眼。

对照组（策略不一致的证据）：`loadReportAll:2190/2196` hourly 卡在 7d/30d 档时**藏整卡**（`closest(".card").hidden = true`）；`renderChannelTable:2375-2377` 空时显示「暂无数据」文案行；`chartToday:1174` 空时 destroy 不建图但**留标题+空白区**。同一页面四种策略并存。

### R3【静态证据确认 + 实测】统计页主区与本地渠道区口径矛盾无解释

- 统计页主区（4 总卡 `renderStatsTotal:1199` + 6 明细 `renderDetail6:1211` + 模型用量 + 用量趋势）数据源为 `/api/dashboard` 的 `totals/models/trend`——**仅统计 usage_records 主区（OpenCode 及其转接渠道）口径**（架构师复核：server.py:1241-1248 → db.totals/model_stats/daily_stats 全部 FROM usage_records）。
- 实测（dev 库，opencode 未登录）：`/api/dashboard` → `totals` 全 0、`models: 0`；同一次请求窗口下 `/api/report/windows` → `today.tokens = 11,306,482`（server 层并入 dsh）、统计页 ZCode 区 ¥671.16/1.19B、DSH 区 415 会话/1.55B、CC 区 36.8M。
- 结果：主区「总费用 ¥0.0000 / 总请求 0 / Token 构成全 0 / 模型用量空白 / 用量趋势空白」与同屏下方三个数据丰富的区块**同屏矛盾**（截图 07/08 实证）。`index.html:121` 的 `zcodeCostHint` 只解释估算计价，不解释主区为何不含本地渠道。
- **跨档位口径差（PM 席补充）**：`server.py:1075-1077` 只把 DSH 并入 `today` 窗口，`7d/30d` 窗口不含 DSH（dsh 数据源仅有今日粒度）——长期 DSH 用户的「今天 11.31M」与「近7天 1.19B」之间 DSH 贡献完全不可见，是同族口径差的另一表现。
- 影响面：所有以 ZCode/DSH/ClaudeCode 为主力渠道的用户（本 dev 库即真实形态），其统计页主区**永远**全 0 空白。

### R4【静态证据确认】compare.pct 与 KPI 数字口径分裂

- `db.py:2394-2400`：`pct` 在 **db 层**用不含 dsh 的 `windows["today"]` 与 `same_y` 计算；db 层不碰 dsh_api 是刻意边界（`report_windows` docstring："dsh 今日由 server 层并入 (T6), db 层不碰 dsh_api"）。
- `server.py:1075-1077`：server 层把 dsh 今日 tokens/cost/requests 并入 `payload["today"]`——**但不重算 `compare`**。
- 结果：KPI 大数字是"含 dsh"口径，涨跌百分比是"不含 dsh"口径，两者可能方向相反或幅度矛盾。实测当前时点：today=11.31M（含 dsh 11.3M）、pct=-84.9%（db 口径）——若 dsh 今日占比继续增大，百分比将严重失真于用户看到的数字。
- 口径协调约束（架构师席补充）：server 重算 pct 时必须尊重 db 层 `insufficient` 样本守卫语义（db.py:2395：same_y.requests<5 或凌晨<1点 → 不显示百分比）；`spike`（db.py:2400）比较双方均为 db 口径、内部自洽，若 pct 改口径需一并明确 spike 的口径选择，避免制造新的口径混用。

### R5【推测，待复现】「今天 0 + ↑100%」实例的精确数值路径

走查截图 03/05（DSH 就绪前）实拍「今天 0 / ¥0.0000 / ↑100% vs 昨日同时段」。三席独立复核一致确认：
- `db.py:2397` 两条静态路径均无法产生「↑100%」：same_y=0 时 pct=None 不显示；today=0 且 same_y>0 时 pct=-100 显示「↓100%」。
- `fmtTokens`（app.js:256-262）不会将非零渲染为 "0"；前端唯一渲染点 `renderWindows`（app.js:2269-2270）`pct>=0→↑` 无其他来源。
- 结合 R4 的口径分裂结构，指向某种"显示数字与百分比取自不同中间态"的时序（如 zcode 今日微小数据量在两次快照间变化），但未能离线锁定精确路径。**推测性问题，等级已按上限 P2 对待，不升级**。
- 无论精确路径如何，R4 的结构性缺陷已足够支撑修复：口径统一后此类荒谬组合即消除；并以可测断言兜底（见验收场景）。

## 3. 用户体验影响

- **数据可信度受损**（最重）：主区全 0 vs 下方 ¥671/1.19B 同屏矛盾，用户第一反应是"数据丢了/软件坏了"，每次打开统计页都会重复质疑。
- **废轴图观感**：今天零用量时段（清晨、新用户、休假日）首页三图呈现空网格+伪影刻度+孤"0"，像渲染故障。
- **荒谬涨跌**：0 用量配「↑100%」直接动摇对全部数字的信任。
- 操作无受阻（数据在下方区块可见、可完成查看任务）——故 P2 而非 P1。

## 4. 修复收益

- 统一空态策略后：空卡有明确占位文案或整卡隐藏，废轴/孤 0 消失，页面"像有意的"而非"坏了"。
- 主区口径说明（条件显隐）：矛盾自解释，统计页对多渠道用户立即变得可理解，且不增加 opencode 主力用户的噪音。
- compare 口径标注/统一：涨跌数字与所见数字一致。
- today 零用量时涨跌位显示「今日暂无用量」类文案替代百分比。

## 5. 修复方向草案（供阶段3计划参考，非承诺）

**产品判据（PM 席建议固化，验收标准的一部分）**：语境下卡片本不适用（档位/条件不满足）→ 藏整卡；卡片适用但无数据 → 卡内占位文案。统计页 two-col 不藏卡的技术理由（破坏布局）与产品理由（核心内容区宜占位引导）一致。

1. **前端空态守卫补齐**（R1/R2）：
   - stack/donut/hourly 加空守卫——复用既有占位先例：`chartZcodeTrend`（app.js:906-915）与 `chartClaudecodeTrend`（app.js:1119-1123）的 emptyEl 显隐模式（`.zcode-chart-empty`，style.css:472），该模式已经 rerenderCharts（app.js:2402-2427）/refreshIcons noAnim 链路验证无回归，与 EVOLUTION-4 缓存键控/seq 守卫天然兼容；
   - 统计页 chartModel/chartTrend 空时卡内占位文案（two-col 布局中藏卡破坏结构，不藏卡）；
   - 总览页 chartOvTrend 空时同样卡内占位（体验官阻塞项）；
   - donut centerText 空数据跳过绘制；空态占位文案的视觉位置计划阶段明确为**卡心居中**（替代 centerText 原位置），避免"中央空无一物+占位挤角落"或双文案并存的中间态，并给 donut 空态一张实拍验收图（体验官席）；
   - 首页 chartToday 空时同样占位（消除"留标题+空白"策略）；
   - 占位文案区分两种语义并从同一 i18n key 族取词：「今日暂无用量」（清晨零用量）vs「该范围暂无数据」（切到无数据档位），不制造第五种文案风格。
2. **口径提示**（R3）：统计页主区加口径 hint，**条件显隐**（PM 席：主区全 0 且下方本地渠道区有数据时才显示，避免对 opencode 主力用户构成噪音）；**hint 位置紧贴主区首个全 0 卡片上方或 Token 构成卡内**（体验官席：同屏矛盾的解释必须与矛盾源头同视野，截图 07 首屏即见 4 张 0 卡，不得放页面底部）；文案设计需统筹跨档位口径差（7d/30d 不含 DSH）；DSH 就绪前后「今天」0→11.31M 瞬态的用户可见提示一并评估（体验官席）。
3. **compare 口径**（R4）：**优先评估「dsh 今日>0 时 pct 附注『涨跌百分比未含今日 DSH』」方向**（PM 席：直接用并入后 today 重算会使分子含 DSH、分母 same_y 不含 DSH，单边放大失真；same_y 与 same_7 同为三源 merge、数据源构成相同，差异仅在时间窗与各渠道实际贡献随时间变化，故文案归因必须限定为"未含今日 DSH"，不得笼统归结全部口径差——架构师 R3 轮修正）；若重算须尊重 insufficient 样本守卫并明确 spike 口径选择（架构师席）。具体方案计划阶段定。
4. **零用量涨跌文案**（R5 伴生）：today.tokens=0 时 compare 位显示「今日暂无用量」；需定义与 `renderWindows` insufficient_sample 文案（app.js:2269）的优先级（insufficient=true 且 today=0 时显示哪个，计划阶段定）。

## 6. 验收场景（PM 席建议显式化）

1. **新用户零数据全页**：首页三图/今日趋势占位、统计页主区+hint、总览页趋势占位——无废轴、无孤 0、无空白卡；含 donut 空态实拍验收图。
2. **纯本地渠道用户**（dev 库形态）：主区全 0 时 hint 出现且解释口径、位置紧贴矛盾源头；下方 ZCode/DSH/CC 区正常。
3. **清晨零用量时段**：today=0 且昨日同时段有数据 →「今日暂无用量」；**可测断言：`today.tokens=0` 时任何代码路径不得渲染百分比箭头**（体验官席：不仅依赖 R4 间接消除）；实拍时顺带抓取 /api/report/windows 原始响应快照，锁定 R5 精确数值路径作为断言测试输入（PM 席）。
4. **DSH 就绪前后瞬态**：今天 0→11.31M 切换时占位/图表的销毁与重建路径正确（与 EVOLUTION-4 缓存键控、seq 守卫交互无回归）。
5. **有数据用户回归**（PM 席，条件显隐逆命题）：opencode 主力用户有数据时空态守卫零触发、口径 hint 隐藏、涨跌正常显示——修复不改变有数据用户的任何预期行为。

## 7. 范围边界

- **records 页口径矛盾**（「会话用量 共 0 会话数」vs DSH 区 415 会话，截图 13）**不并入本问题**：records 空态文案已存在，矛盾源于另一数据链路（sessions 端点口径），修复应独立评估，避免本问题范围膨胀——留备选池跟踪（候选清单已有记录），若口径 hint 方案成熟可顺带评估。
- two-col 断点失效、pill 竖排、明细表溢出属 EVOLUTION-8，本问题不碰。
- tooltip/i18n 泄漏属 EVOLUTION-9，本问题不碰。

## 8. 证据索引

| 证据 | 位置 |
|---|---|
| 空轴伪影+孤 0+暂无数据四态并存 | 截图 03/04（.probe/ui-shots-v3/） |
| 统计页主区全 0 vs ZCode/DSH/CC 区矛盾 | 截图 07/08 |
| 800px 空白卡拉高 | 截图 10 |
| 「今天 0 ↑100%」 | 截图 03/05 |
| 三图无条件建图 | app.js:2296/2321/2353 |
| 留白式守卫（统计页两图+总览趋势） | app.js:1230/1266/1636-1642 |
| chartToday 留白策略 | app.js:1174 |
| hourly 藏卡策略（对照） | app.js:2190/2196 |
| pct db 层计算 | db.py:2394-2400 |
| dsh 并入不重算 compare | server.py:1075-1077 |
| dsh 仅并入 today（7d/30d 口径差） | server.py:1074-1078（`payload["today"]` 重写为唯一并入点；1079 起为 `channel == "dsh"` 单渠道分支，该分支反而以 dsh_win 覆盖 7d/30d，仅单渠道请求生效） |
| 占位先例（emptyEl 显隐） | app.js:906-915 / 1119-1123、style.css:472 |
| totals 全 0 实测 | curl /api/dashboard（2026-09-06 03:1x） |
