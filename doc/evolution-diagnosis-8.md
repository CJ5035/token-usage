# EVOLUTION-8 诊断报告：窄窗（高 DPI 缩放）排版错乱三连

- **候选编号**：问题 8（第三轮候选 #2）
- **版本**：v3（门禁1 第 2 轮全票后吸收 6 条非阻塞建议：.ph-right 复用点留档、方案 b 勿扩大、措辞收窄、英文档同款条目、pill 边界改写、右对齐基线 1280px；对照表见 `doc/evolution-votes-8.md`）
- **预估等级**：P2（6/10）——诊断后**维持**
- **诊断方式**：走查截图（.probe/ui-shots-v3/ 10/11/12）+ CSS 规则逐条核对 + 800px 视口 DOM 定量复验（2026-09-06，修复 EVOLUTION-7 后的服务实测）
- **问题仍存在验证**：✅ 800px 视口实测（pill 高 74px 竖排 / .ph-title 高 54px 折行 / 统计页 two-col 仍 `1fr 1.6fr` / 明细表 707px 贴 708px 容器临界）

## 1. 问题陈述

主窗口 `min_size=(1000,680)`（app/main.py:26）按**物理像素**约束；Windows 出厂默认 125%/150% DPI 缩放下，CSS 视口宽仅 ~800/667px。此宽度下三处排版错乱同时触发：页签 pill 文字竖排换行、渠道明细表尾部列被裁死不可达、统计页两卡断点失效不折叠。

## 2. 根因分析（三处独立缺陷，静态证据确认）

### R1【静态确认 + DOM 定量】页签 pill 竖排 + 标题折行

- 结构（index.html:65）：`.ph`（:194 `display:flex; justify-content:space-between`）左 `.ph-title`（h2）右 `.ph-right` 内两个 `.pill-row`（:93 `display:flex; gap:4px`）——`#channel-tabs`（全部渠道/opencode/zcode/claudecode/dsh）+ `#home-pills`（今天/昨天/近7天/近30天/全部）。
- `.pill`（:92）**无 `white-space: nowrap`**：flex 容器收缩时 pill 被压缩，汉字无断行点逐字换行 → 「全部渠道」竖排 3-4 行（实测 pill 高 74px，单行应为 ~28px）。
- `.ph`/`.ph-right` 均**无 `flex-wrap`**：空间不足时标题与 pill 组互相挤压，`.ph-title` 折行（实测高 54px）。
- 触发面：约 <900px CSS 宽即开始挤压，667px（150% DPI）最严重。

### R2【静态确认 + 走查实拍】渠道明细表溢出被裁死（不可滚动）

- `.tbl td { white-space: nowrap; }`（style.css:294）+ 渠道明细表 8 列（渠道/Token/输入/输出/缓存读/请求/费用/数据自）→ 表 min-content 随数据在 ~700-750px 波动。
- 表为 `.card` 直接子元素（index.html:76），card 与各级容器（.main:116 overflow:hidden）**均无 `overflow-x:auto`** → 溢出部分被**直接裁剪且用户无法滚动看到**。裁剪链复核（架构师席确认）：`.page { overflow:hidden }`（:117）+ `#page-home` 仅覆盖 overflow-y（:120），overflow-x 保持 hidden。
- 损伤精确化（PM 席）：首页顶部 scope-hint 已有**全局**数据起点（「数据自 2026-07-30」），被裁死的是**每渠道各自**的起始日期（zcode 2026-08-19 / claudecode 2026-07-30 各不相同）——信息确有丢失但不致"完全无法得知数据起点"，支持 6/10 定级不上调。
- 实测两组证据：走查时 tableW 747 > cardW 708，`clipped:true`（「数据自 2026-0...」截断，截图 12）；本轮复验 707 ≈ 708 贴边临界——**溢出随数据宽度波动，容器无任何余量**。
- 对照：`#page-records .tbl` 有 `table-layout:fixed` + td ellipsis（:133-134）保护；report 表无任何保护。

### R3【静态确认 + DOM 定量】统计页 two-col 断点被 ID 特异性压死

- style.css:270 `#page-stats .two-col { grid-template-columns: 1fr 1.6fr; }`（特异性 0,1,1,0）
- style.css:414-416 `@media (max-width:1000px) { .two-col { grid-template-columns: 1fr; } }`（特异性 0,0,1,0——**无条件输给** :270，与源序无关）
- 实测：800px 视口下统计页 two-col 仍 `1fr 1.6fr`；首页 two-col（无 ID 前缀）正常折叠 → 同类组件行为分叉。
- 连带效应：EVOLUTION-7 修复的「模型用量/用量趋势」空态占位卡在不折叠布局下被拉得更高，空白观感放大（截图 10）。

### 范围裁定

- `.ub-meta` 文案重叠（style.css:221 space-between + :208 overflow:hidden，800px 3 列格 <200px 时）为**同族静态疑似**，但 dev 库无 BAI 账号无法实拍验证，且修复依赖 BAI 实际文案宽度——**不纳入本问题**，留备选池（附行号证据）。
- `.wb-cell`（:478-479）800px 实测未破版（截图 11 KPI 4 卡正常），不纳入。
- 其他多列网格（.zcode-cards/.usage-blocks 等）800px 实测压缩但未破（截图 09/11），不纳入。

## 3. 用户体验影响

- Windows 125%/150% DPI 是**出厂默认缩放**，受影响用户远多于 100%；-min_size 窗口即触发，用户缩小窗口同样触发。
- pill 竖排 + 标题折行：首屏导航区破碎，操作目标难辨认（视觉错乱最显眼处）。
- 明细表尾部列（数据自）被裁死：信息丢失且无滚动出口，用户无法得知渠道数据起点。
- 统计页不折叠：800px 下两卡各 ~350px，图表与占位挤压；行为与首页不一致造成"有的页面会折叠有的不会"的混乱感。

## 4. 修复收益

- 三处均为 CSS 级小改（估计净增 <10 行）：pill nowrap + ph 换行策略、明细表横向滚动、@media 补 ID 前缀规则。
- 修复后 667-800px 宽度带**三处缺陷涉及页面/场景**的可用性恢复（不含范围裁定排除项，如 .ub-meta），与 1000px+ 行为一致。

## 5. 修复方向草案（供阶段3计划参考，非承诺）

1. **pill/标题（R1）**：
   - `.pill { white-space: nowrap; }`（pill 文字永不逐字断行）；
   - `.ph { flex-wrap: wrap; }` + **`.ph-right { margin-left: auto; }`**（v2 修正：仅加 wrap 时换行后的 .ph-right 是第二行唯一 flex 项目，space-between 等效 flex-start 会靠左——margin-left:auto 宽屏下吸收剩余空间保持右对齐、换行后单 item 行也推至右缘，宽屏视觉与现状等价）；
   - `.pill-row { flex-wrap: wrap; }` 兜底（架构师席：单条 pill-row min-content 超可用宽时组内换行，防整条水平溢出）；
   - 影响面已核实：.pill nowrap 波及顶栏 .pill.small 与设置页 5 组 pill-row，667px（583px 可用宽）下不溢出，风险可控；**`.ph-right` 类另有 3 处复用**（index.html:70 #report-all 下 seg 容器 / :101 统计页 .ph / :171 records card-h）——静态推演均无视觉回归（:70 父级 block 流 margin 解析为 0；:171 card-h space-between 下位置不变），计划阶段验收顺带覆盖或留档（架构师 R2）。
2. **明细表（R2）**：给渠道明细表加横向滚动。**倾向方案 b**：index.html 给该表包一层 `<div class="tbl-scroll">` + `.tbl-scroll { overflow-x:auto; }`（对 table 自身 display 零改动；**仅包渠道明细一处，勿扩大到 records 两表**——它们已有 fixed+ellipsis 保护，双滚动语义混淆，架构师 R2）。**方案 a（`.card > table.tbl { display:block }`）波及面警示**（架构师/体验官席）：会命中 records 页两张同为 .card 直接子的表，其行高均分契约（:127 `flex:1;height:100%` + :128 `tbody tr height:calc((100%-28px)/7)`）在 table 块化后失效，且 `.tbl width:100%`（:292）退化为 shrink-to-fit——若用方案 a 必须限定 #report 域。取舍留档要求（PM 席）：计划中记录"为何不选缩字号/减列"（答：缩字号伤 667px 可读性、减列丢失列语义，横向滚动是桌面表格惯例），备选「窄宽度隐藏次要列」仅在滚动条观感不佳时启用。
3. **two-col（R3）**：@media (max-width:1000px) 块内补 `#page-stats .two-col { grid-template-columns: 1fr; }`（同特异性源序获胜）。:410/:473 两个 @media 块经架构师复核**不需要**同款补齐（.tc-grid.tc-6/.d6-grid/.kpi-row.kpi5 均无 ID 前缀竞争规则）。
4. **验收标准（可判定化，体验官 v2/v3 修正）**：
   - ①667/800px 下**每个 pill 文字自身单行**（无竖排）；②换行仅发生在 **pill 边界（组内或组间均可）**，不发生在 pill 文字内部；③标题「用量统计总览」保持单行；④**换行后 pill 组仍右对齐**（基线实拍对照取 1280px 档，即现有截图 03 档）；
   - 明细表在 800px 可横向滚动至「数据自」完整可见；**暗色主题滚动条与卡片对比度核对**（升格为验收项）；
   - 统计页 two-col 800px 单列，与首页同宽**并排截图**作一致性回归锚；
   - **800px 英文界面档**验收，**执行同款验收条目①-⑦**（英文 pill 文案如 "All Channels" 比汉字更宽，正是换行行为最可能分叉的场景）；
   - **667×453**（150% DPI 极端矮高）截图核对页头垂直成本（换行后 ~110px 约占 1/4 视口）与首屏观感；
   - 1000px+ 布局零变化（回归锚）。

## 6. 证据索引

| 证据 | 位置 |
|---|---|
| pill 竖排/标题折行实拍 | 截图 11（800px）；DOM: pillH=74, titleH=54 |
| 明细表裁死实拍 | 截图 12；DOM: 747>708 clipped:true（走查时） |
| 明细表贴边临界 | 本轮 DOM: tableW=707, cardW=708 |
| two-col 不折叠 | 本轮 DOM: `1fr 1.6fr`@800px；截图 10 |
| .pill 无 nowrap / .ph 无 wrap | style.css:92/193-194（.ph 定义 :194） |
| .tbl td nowrap + 无滚动容器 | style.css:294 + index.html:76 表结构 |
| ID 特异性压死断点 | style.css:270 vs :414-416 |
| min_size 物理像素约束 | app/main.py:26 |
| records 页表格保护对照 | style.css:133-134 |
