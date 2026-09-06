# EVOLUTION-9 诊断报告：tooltip 双语泄漏 + i18n title 处理缺失 + 切语言顶栏快照回写

- **候选编号**：问题 9（第三轮候选 #3）
- **版本**：v3（门禁1 第 2 轮全票后修正：R3 定性改「同值回写零可见损伤」（PM 席自我纠正）、applyCurrency 方向改设置页跳过、行号区间修正、验收口径补充；对照表见 `doc/evolution-votes-9.md`）
- **预估等级**：P2（**4/10**，v1 5/10 下修——可达性误判修正后损伤面缩水）
- **诊断方式**：静态源码盘点 + DOM 快照实测 + 门禁1 三席独立复核修正（两席驳回暴露 v1 可达性误判）
- **问题仍存在验证**：✅ 当前 HEAD 源码核对 + 走查 DOM 快照实测（accessible name 泄漏）

## 1. 问题陈述

界面语言与 tooltip/顶栏快照文案脱节：中文界面悬停顶栏/侧栏显示英文 tooltip（12 处，反之亦然）；「估算」badge 的 tooltip 因 i18n 属性无处理逻辑而永远为空且徽标文本「估」硬编码中文；切语言后首页渠道表体/windows-bar/配额条/图表标签保持旧语言（靠切页重载兜底才最终一致）；applyLang 对隐藏首页容器与顶栏做同值回写的冗余重渲（无可见数据损伤，属代码卫生范畴）。

## 2. 运行时机制（v1 漏判、门禁1 修正——评估损伤的前提）

- **切语言运行时唯一入口在设置页**：`app.js:2095`（语言 pill → applyLang）；另一调用 :2541 为启动 init（彼时 state.data 为 null，renderAll 分支不触发）。因此 **applyLang 执行时 state.page 恒为 "settings"，首页 hidden，homeVisible 恒为 false**。
- **switchPage 回页必重载**：`app.js:484-490`——home/stats 调 `loadDashboard()`，records 调 `loadSessions()+loadRecords()`（:489），overview 调 `loadOverview()`，全量重渲。语言最终一致性由该机制保证（v1 的"切语言后大半内容旧语言、需刷新页面"不成立）。
- **顶栏文案唯一更新点是 renderAll**（:1497-1507：tb-sync/tb-login/tb-user-count/tb-updated）——applyLang 当下不刷新顶栏语言，直到下次导航/同步。

## 3. 根因分析

### R1【静态确认 + DOM 实测】12 处 tooltip 硬编码双语泄漏

- **中文硬编码**（英文 UI 下中文泄漏）：index.html:20 `tb-theme title="切换主题"`、:21 `tb-refresh title="刷新"`、:25 `tb-user-count title="已登录用户数"`（后者为潜在死值：app.js:1507 每次 renderAll 以 t("userCountTip") 覆盖且 :1505 hidden 同步门控——硬编码清单 12 处、用户可见泄漏 11 处）
- **英文硬编码**（中文 UI 下英文泄漏，DOM 快照实证）：index.html:29 `Minimize`、:30 `Close`、:37 `Home`、:40 `Stats`、:43 `Records`、:47 `Accounts Overview`、:50 `Settings`、:53 `About`
- **JS 内硬编码**（同族，体验官席补充）：app.js:2270（renderQuotaBar）`title="同步失败"`（配额卡同步失败 ⚠ 标记）
- 对照：app.js:1502/1507 已有 JS 动态补 title 先例——缺统一机制而非能力。
- 高频/低频分层（体验官席）：顶栏+侧栏每页可见高频；同步失败 ⚠ 低频。

### R2【静态确认】data-i18n-title 无处理逻辑 + 估算 badge 双重缺陷

- index.html `data-i18n-title` 两处：:24 `tb-login`（有 app.js:1502 手动补偿，侥幸可用）、:72 `report-est`（**无任何补偿**，`title=""` 永远为空）。app.js 全文无 `data-i18n-title` 遍历处理。
- **徽标文本硬编码**（体验官席）：:72 `#report-est` 文本「估」硬编码中文（英文 UI 不切换），I18N 键 `estimateBadge`（"估算/Est."）已存在但 app.js:2233 只控 hidden 未写文本。
- 估算解释入口并非完全缺失（PM 席修正）：windows-bar 标注行、渠道明细表行内 badge、统计页 KPI 的动态 est-badge tooltip 均正常——本缺陷是**首页分渠道趋势卡标题旁这一处**单点无解释。

### R3【静态确认 + 门禁1 修正降级】切语言的重渲缺口与顶栏快照回写

- applyLang（当前 :355-370）动态重渲：`renderAll(state.data)` + `renderSettings()` + `loadRecords()` + zcode/dsh/cc 三块 + EVOLUTION-7 占位重设。**不在清单**：renderWindows/renderQuotaBar/renderChannelTable 表体/renderQuotaSingle/三图 label/总览页 loadOverview——保持旧语言，由 switchPage 回页重载兜底最终一致（用户在设置页切完语言停留时，这些区块语言无关紧要；感知残留有限）。
- **同值回写、零可见数据损伤（PM 席第 2 轮自我纠正）**：renderAll 全库仅两个调用点（applyLang :356 与 loadDashboard :583），state.data 唯一赋值点即 renderAll 首行 :1482，顶栏四元素唯一写点全在 renderAll 内（:1498-1510）——任意时刻顶栏 DOM ≡ f(state.data)，故 applyLang 的 renderAll(state.data) 是**同值回写**：tb-updated 值恒等无变化，tb-sync 的 fmtRelative 相对时间自然前进属正确刷新。**零用户可见损伤，纯冗余重渲/代码卫生**。
- **隐藏容器写穿（无用重渲）**：renderAll 内 renderUsageBlocks/renderCcSummary/renderOverview（:1484-1486）无页面门控，把旧快照写入隐藏的首页容器；导航回首页的取数窗口期短暂可见旧口径，请求失败则持续——亚秒瞬态或罕见持续。
- **唯二真实瞬态**：①切语言恰逢同步进行中时，progress 横幅（renderAll :1511-1512 用旧 progress）被静态遍历重置，≤2.5s pollUntilIdle（:1532）自愈；②renderSettingsSyncProgress 运行中文案同理自愈。
- 现状该调用的真实价值：顶栏文案即时换语言——修复方向 2 需保留该价值（提取函数方案）。

### R4【静态确认 + 架构师同源发现】applyCurrency 同模式未门控

app.js:467-475（return 后 8 条语句 :468-475）：`if (!state.data) return` 后无条件 `renderOverview(state.data.totals)`（:469）等重渲——与 R3 同模式（切货币时旧快照写穿隐藏容器）。与 R3 的修复（上下文门控/提取函数）应同批处理，避免"修了 applyLang 漏了 applyCurrency"半修状态。

## 3. 用户体验影响（修正后）

- **双语可信度**（主损伤）：12 处 tooltip 双语泄漏，顶栏/侧栏高频悬停点每页可见；估算徽标「估」英文 UI 不切换。
- **估算 badge 单点 tooltip 缺失**：首页分渠道趋势卡标题旁 badge 悬停无解释（费用口径的局部解释入口缺失，与 EVOLUTION-7 hint 姊妹）。
- **冗余重渲（代码卫生）**：隐藏容器写穿与同值回写无用户可见损伤，但属应消除的误导性代码路径（后续演进者可能据其误判行为）。
- 操作无受阻、数据无错（显示层面）——P2 下限 4/10。

## 4. 修复收益

- tooltip/徽标全量随语言切换，双语一致性闭环。
- 估算 badge tooltip + 文本切换生效。
- 顶栏即时换语言且**不回写旧时间戳**（提取的顶栏刷新段仅重设 t() 文案部分，时间戳 DOM 不动）。
- 消除隐藏容器写穿与 applyCurrency 同模式。

## 5. 修复方向草案（供阶段3计划参考，非承诺；**计划阶段一律以符号名+grep 锚定定位，不以区间端点为准**——两轮间 HEAD 曾新增 4 行致区间漂移实证）

1. **统一 title/徽标机制（R1/R2）**：新增 `syncI18nTitles()`——遍历 `[data-i18n-title]` 设 `el.title = t(el.dataset.i18nTitle)`；index.html 11 处硬编码 title 改 `data-i18n-title`（I18N 补约 11 键，语义相近现键优先复用）；app.js:2270 改 `title="${t("syncFailTip")}"`（新键）；`#report-est` 文本改由 `t("estimateBadge")` 驱动（applyLang/显隐处设置）；初始化与 applyLang 各调用 syncI18nTitles。app.js:1502/1507 手动补偿保留（幂等双写同值）。
2. **顶栏即时换语言且消除冗余重渲（R3）**：从 renderAll 提取顶栏刷新段为独立函数 `syncTopBar(data)`——**直接以 state.data 重格式化**（同值回写不变式保证「值不变、前缀换语言」，无需 DOM 读回，PM 席第 2 轮简化）；progress 横幅与 renderSettingsSyncProgress 段**不纳入**提取函数（applyLang 时同步进行中为 ≤2.5s 自愈瞬态，留档验收矩阵）；applyLang 的 `renderAll(state.data)` 调用替换为 `syncTopBar(state.data)`——renderUsageBlocks/renderCcSummary/renderOverview 写穿三行随调用消除自然退场。
3. **applyCurrency 同批处理（R4，v3 修正）**：货币 pill 唯一运行时入口 app.js:2094 也在设置页（「仅统计页可见时执行」是死分支，PM 席指出）——改为**设置页上下文直接跳过 :467-475 重渲块**（保留 pill active + localStorage），货币最终一致由 switchPage 回页重载保证；顶栏无货币文案，无需提取函数兜底。
4. **备选方案留档（PM/体验官席曾提议）**：`loadDashboard(true)` 一揽子 quiet 重拉（数据+语言双新鲜、顶栏不回跳）——代价是 settings 上下文重拉会以 state.range 口径改写 state.data（回统计页时 switchPage 重拉正确档位，无实际损害），且引入网络请求；与方案 2 二选一，计划阶段定（倾向方案 2：零请求、改动面更小）。

## 6. 验证方向（实测矩阵，PM 席）

- **切语言后停留设置页**：顶栏 tooltip/文案即时切换、tb-updated 值不变（前缀换语言）、估算徽标文本切换；**同步失败 ⚡ tooltip 由静态断言（12 处键接线）覆盖**（运行时需失败态，实测成本高）。
- **切语言后切回各页**（回页重载兜底）：首页 all/单渠道各页签、统计、记录、总览——语言与口径一致。
- 中英双向 × 亮暗主题抽查 tooltip。
- 静态断言：12 处 title 键接线 + syncI18nTitles 存在 + renderAll 不再被 applyLang 调用（防退化锚）。

## 7. 范围裁定

- 表格空态三套写法、.wb-v 数字抖动、overflow-y:overlay 废弃 4 处——不纳入（备选池，独立低优先级项）。
- 总览页 loadOverview 不在 applyLang 重渲清单——回页重载覆盖（体验官席确认），不单独修。

## 8. 证据索引（行号按当前 HEAD）

| 证据 | 位置 |
|---|---|
| 中文硬编码 tooltip 3 处 | index.html:20/21/25 |
| 英文硬编码 tooltip 8 处 | index.html:29/30/37/40/43/47/50/53 |
| JS 内硬编码 tooltip 1 处 | app.js:2270 |
| data-i18n-title 两处（:72 无补偿） | index.html:24/:72 |
| 估算徽标文本「估」硬编码 | index.html:72 + app.js:2233（仅控显隐） |
| 手动补偿先例 | app.js:1502/1507 |
| 切语言入口在设置页 | app.js:2095（init :2541） |
| switchPage 回页重载 | app.js:484-492 |
| applyLang 重渲缺口 | app.js:355-370 |
| renderAll 顶栏文案唯一更新点 | app.js:1498-1510（tb-updated 写点 :1510） |
| state.data 唯一赋值点 | app.js:1482 |
| applyCurrency 同模式（return 后 4 条语句 :468-471） | app.js:467-475 |
