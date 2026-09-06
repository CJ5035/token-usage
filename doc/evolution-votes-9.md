# EVOLUTION-9 门禁1 投票记录（诊断评审）

## 第 1 轮（2026-09-06）

### 架构师：通过

建议：
1. 诊断行号基线过时（index.html 全部行号与当前 HEAD 不符：中文 title 实为 :20/:21/:25、英文 :29/:30/:37/:40/:43/:47/:50/:53、data-i18n-title :24/:72；app.js renderAll 调用 :356、loadDashboard return :534/:574）——计划一律以当前 HEAD 行号锚定，诊断行号须修订。
2. R3 表述修正：渠道表**头**是静态 data-i18n 会正常更新；保持旧语言的是渠道表**体**（renderChannelTable :2456/:2460/:2463 渲染期 t() 文案）及 windows-bar/quota-bar/三图 label。
3. **同源未门控点**：applyCurrency（app.js:467-471）无条件 renderOverview(state.data.totals)——与 R4 完全同模式；阶段 3 应裁定顺带纳入或显式遗留。
4. R4 口径表述放宽：state.data 为"最近一次非首页 loadDashboard 的全渠道 dashboard 快照"（range 取 statsRange 或 state.range 视页面）。

### 产品经理：驳回

阻塞：
1. **R3/R4 损伤可见性误判**：切语言运行时唯一入口在设置页（app.js:2095；:2541 为 init 时 state.data=null 不触发）→ applyLang 触发时 homeVisible 恒 false，chartToday 不会执行；switchPage 回页必重载（:484-492）保证语言最终一致——"切语言后首页大半旧语言需刷新"与"数字口径突变被解读为数据错了"均不成立。真实残留：设置页内顶栏 tb-sync/tb-updated 被旧统计快照回写（时间戳回跳）+ hidden 容器无用重渲。
2. **修复方向 3 运行时不可达**：首页 all/单渠道两个分派分支在 applyLang 时不可达（state.page 恒 settings），属过度设计；最小修复为删除/替换 applyLang 的无条件 renderAll(state.data)（保留 renderSettings/loadRecords），顶栏即时换语言需另配轻量方案。

建议：
3. 估算解释入口并非"失去"（windows-bar 标注行/渠道表行内 badge/统计页 KPI 的动态 est-badge tooltip 均正常）——改为"首页分渠道趋势卡标题旁 badge 单点无解释"。
4. index.html 行号大面积错位（同架构师-1），同日候选清单行号正确。
5. 验证场景应补"设置页切语言→停留→切回各页"实测矩阵（回页重载机制正是静态盘点漏掉的）。
6. 定级：修正后损伤面更接近 4/10（R1/R2 属实+顶栏回跳轻微）。

### 用户体验官：驳回

阻塞：
1. **R4「数字口径突变」不可达**（同 PM-阻塞1：设置页入口+homeVisible 恒 false+回页重载）——从问题陈述删除；R3/R4 残留改写为次要项。
2. **§5.3「删除无条件 renderAll」按字面执行会造成顶栏语言不切换回归**：renderAll 是顶栏 tb-sync/tb-login/tb-user-count/tb-updated 文案唯一更新点（:1497-1507）——改法：从 renderAll 提取顶栏刷新段为独立函数，applyLang 改调之；仅统计页可见时调 renderAll(state.data)；删除 quiet 重拉分派。
3. **同族遗漏两处**：①#report-est 徽标文本「估」硬编码中文（estimateBadge 键已存在未用于该元素，:72+app.js:2233 仅控显隐）；②app.js:2270 renderQuotaBar `title="同步失败"` 硬编码中文（第 12 处 tooltip，在 JS 内）——同族扫描闭合：index.html 无 placeholder/aria-label，alt 仅品牌名。

建议：
4. 行号漂移（同上）。
5. 高频/低频影响补充：侧栏导航项与顶栏同为高频悬停点；估算 badge tooltip 为低频但是费用口径唯一解释入口（该卡片上）。
6. 总览页 loadOverview 渲染全程走 t() 但不在 applyLang 重渲清单——回页重载下不可见，随 R3 重述说明即可。

### 判定

streak = 0（两席驳回）。核心教训：**R3/R4 损伤可达性误判**（漏掉切语言入口在设置页 + switchPage 回页重载两个机制）；修复方向原方案有顶栏回归风险。重写诊断 v2（损伤重定级 4/10、修复方向重构、行号修正、同族两处纳入、applyCurrency 裁定）后进入第 2 轮。

## 修订对照表（第 1 轮意见 → 落实情况，v2）

| 上轮意见 | 落实情况 |
|---|---|
| PM-阻塞1 + 体验官-阻塞1：R3/R4 可达性误判 | ✅ 问题陈述重写；R3/R4 合并降级为 R3（真实残留：顶栏快照回写/隐藏容器写穿/语言最终一致由回页重载保证）；新增"运行时机制"节（设置页入口 :2095 + switchPage :484-492 回页重载） |
| 体验官-阻塞2：§5.3 顶栏回归 | ✅ 修复方向重构：方案改为"从 renderAll 提取顶栏刷新段 syncTopBar 快照重写 + 删除首页容器写穿段"；quiet 重拉分派删除（备选方案留档，含 loadDashboard(true) 一揽子方案及其口径副作用说明） |
| 体验官-阻塞3：两处同族遗漏 | ✅ R1 扩至 12 处（+app.js:2270 同步失败）；R2 扩充 #report-est 徽标文本「估」硬编码（estimateBadge 键未接线） |
| 架构师-建议1 + PM-建议4 + 体验官-建议4：行号修正 | ✅ 全文行号按当前 HEAD 修正（:20/21/25、:29-53、:24/:72、app.js :356/:534/:574/:2095/:2541/:484/:2270） |
| 架构师-建议2：表头/表体 | ✅ R3 表述修正（表头 data-i18n 正常、表体/windows-bar/quota-bar/三图 label 保持旧语言） |
| 架构师-建议3：applyCurrency 同模式 | ✅ 新增 R5 纳入本问题（同一提取函数方案顺带门控），避免半修 |
| 架构师-建议4：R4 口径放宽 | ✅ 表述修正 |
| PM-建议3：估算入口多处可及 | ✅ 损伤陈述精确化（单点 badge 无解释） |
| PM-建议5：实测矩阵 | ✅ 验收方向补"设置页切语言→停留→切回各页"两视角矩阵 |
| PM-建议6 + 两席：定级 4/10 | ✅ 改为 P2 4/10 |
| 体验官-建议5：高频低频分层 | ✅ 影响节补充 |
| 体验官-建议6：总览页同族 | ✅ R3 重述中说明（回页重载覆盖，无需单独修） |

## 第 2 轮（2026-09-06）

### 架构师：通过

建议：
1. 顶栏区段锚 :1497-1507 → 实际 :1498-1510（tb-updated 写点 :1510）。
2. switchPage 表述：records 页实调 loadSessions()+loadRecords()（:489），非 loadDashboard——机制结论不变。
3. renderSettingsSyncProgress（renderAll 尾部 :1511-1512）语言相关文案：运行中同步时切语言会被静态遍历重置为空闲文案，≤2.5s pollUntilIdle（:1532）自愈——纳入提取函数或留档为可接受瞬态。
4. index.html:25（tb-user-count）静态 title 是"潜在死值"（:1507 每次覆盖+hidden 同步块）——可见泄漏实为 11 处（12 处作为硬编码清单成立）。
5. votes 对照表 R5 与正文 R4 编号对齐。

对照表核对：4/4 已落实（含 :2541 state.data=null 核实）。

### 产品经理：通过

建议（含自我纠正）：
1. **（必改，自我纠正）R3「时间戳回跳」不成立**：renderAll 全库仅 :356/:583 两个调用点，state.data 唯一赋值点即 renderAll 首行 :1482，顶栏四元素唯一写点全在 renderAll 内（:1498-1510）→ 任意时刻顶栏 DOM ≡ f(state.data)，applyLang 的 renderAll(state.data) 是**同值回写**，tb-updated 值恒等无回跳；tb-sync fmtRelative 相对时间自然前进属正确刷新。R3 定性应改「零用户可见损伤，纯冗余重渲/代码卫生（隐藏容器写穿+同值回写）」。真正旧快照回写的是 progress 横幅（:1511-1512 vs 实时轮询 :1531-1532，仅切语言恰逢同步进行中瞬态）——§5-2 删除 renderAll 调用顺带消除。
2. §5-3 applyCurrency「仅统计页可见时执行」是死分支（货币 pill 唯一入口 :2094 也在设置页）——改为「设置页上下文直接跳过 :467-475 重渲块（保留 pill active + localStorage），货币一致由回页重载保证」。
3. §5-2 简化：syncTopBar(state.data) 直接以 state.data 重格式化即"值不变、前缀换语言"，无需 DOM 读回。
4. 笔误：:1497-1507 → :1498-1510；votes R5 编号与正文 R4 对齐。

对照表核对：6/6 已落实。

### 用户体验官：通过

建议：
1. 行号区间端点漂移汇总：:1498-1510（tb-sync→tb-updated）、:1484-1486（写穿三行）、switchPage 函数体 :479-491 重载行 :484-490、applyCurrency return 后实为 4 条语句 :468-471——计划阶段以符号名+grep 锚定，不以区间端点为准。
2. §6 补「同步失败 ⚡ tooltip 由静态断言（12 处键接线）覆盖」口径（运行时实测成本高）。

对照表核对：6/6 已落实（3 阻塞全闭环）。

### 判定

streak = 1（第 2 轮 3/3 全票）。吸收建议出 v3（文字级：R3 定性修正、applyCurrency 方向改跳过、行号区间、§6 口径）后进入第 3 轮。

### v3 修订对照表

| 第 2 轮意见 | 落实 |
|---|---|
| 架构师-1/PM-4/体验官-1：行号区间 | ✅ 全文按 :1498-1510/:1484-1486 修正，计划要求符号名锚定 |
| 架构师-2：switchPage records 表述 | ✅ §2 修正 |
| 架构师-3：renderSettingsSyncProgress 瞬态 | ✅ §5-2 留档（≤2.5s 自愈，验收矩阵补） |
| 架构师-4：tb-user-count 死值 | ✅ R1 注明（硬编码清单 12 处/可见泄漏 11 处） |
| 架构师-5/PM-4：编号对齐 | ✅ votes 已注 |
| PM-1：R3 定性修正（同值回写） | ✅ 问题陈述/影响/R3/§6 五处同步修正 |
| PM-2：applyCurrency 改跳过 | ✅ §5-3 重写 |
| PM-3：syncTopBar 直接重格式化 | ✅ §5-2 简化 |
| 体验官-2：同步失败 tooltip 静态断言覆盖 | ✅ §6 补口径 |

## 第 3 轮（2026-09-06）—— 门禁1 通过轮

### 架构师：通过
建议（档案级/计划阶段）：①§2 switchPage records 表述与 :484-490 区间残留（本轮已顺手修正正文）②tb-user-count 死值注明（本轮已补 R1）③§4 与 §5-2 时间戳处理两措辞二选一定稿（§5-2 为准）④证据索引 applyCurrency :468-475 补全（本轮已改）⑤votes R5 编号（档案注记）。
对照表核对：2/2 落实（3 处"声称落实未体现"均为建议级注记，本轮已顺手消化 2 处）。

### 产品经理：通过
建议（留档）：①votes 档案 R5 注记与 tb-user-count 注记补齐（正文级本轮已补）②§4 措辞对齐 §5-2 重格式化策略 ③applyCurrency 证据索引 :468-475（本轮已改）。
对照表核对：4/4 落实（R3 同值回写定性五处吻合、applyCurrency 跳过方案、syncTopBar 简化、笔误修正全部核实）。

### 用户体验官：通过
建议（留档/计划阶段）：①§2 两处残留（本轮已修正）②applyCurrency 区间 :468-475（本轮已改，含两轮间 HEAD 新增 4 行的漂移实证）③对照表 tb-user-count 虚标（本轮已补正文）④applyLang 自身 loadRecords/zcode/cc 写穿同族——计划阶段与 loadOverview 同口径显式裁定（回页重载覆盖）⑤§5 补符号名锚定声明（本轮已加）。
对照表核对：2/2 落实。

### 判定
streak = 2（第 2、3 轮连续全票）→ **门禁1 通过**，诊断 v3 定稿，进入阶段3。
