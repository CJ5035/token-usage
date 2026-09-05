# 门禁1 投票记录 · EVOLUTION-4（切主题图表/渠道色/图标残留）

被评审材料：`doc/evolution-diagnosis-4.md`

## 第 1 轮（2026-09-05）

### 架构师：通过

证据核实 6 处均成立（state.data 守卫机制/rerenderCharts 缺口/chColor 快照/图标变体/两套色板；守卫实际行号 app.js:2340）。

意见：
- [建议] "去掉 state.data 守卫"不可裸做：`chartToday(state.data.today_trend)` 在 null 时抛 TypeError；首页 all 页签下 report-single 容器 hidden、canvas 零尺寸（app.js:1416 注释自证）。应采用"按容器状态判断"，分支粒度到 report-all/report-single 子容器。
- [建议] 数据缓存清单不全：单渠道分支 trend（/api/report/channel-trend，app.js:554）与总览页 chartOvTrend 入参同样需模块级缓存；验证点补"首页单渠道页签切主题"与"统计页重渲行为不回归"。
- [建议] 性能回归：若走"复用 loadReportAll() 重拉"会与问题5 叠加（windows 冷算 3.2s），应优先模块级缓存，验证点增加"切主题零网络请求"。
- [建议] 最小化：`CH_COLOR`（app.js:2116-2117）本就存 `var(--ch-*)` 字符串，DOM 内联色用 `CH_COLOR[ch]` 替代 `chColor(ch)` 即可；但 Chart.js backgroundColor 传 var() 字符串 canvas 不解析，**图表内渠道色仍须走 chColor 快照+重渲路径，两条路径不可混用**。rerenderCharts 调用方两处（applyDarkMode:450、applyCurrency:460 后者自带守卫），勿破坏 applyCurrency 语义。

### 产品经理：通过

意见：
- [建议] chColor() 不只用于 DOM 内联色，还被 Chart.js 数据集直接消费（app.js:2244/2297/2254），Canvas 无法解析 var(--ch-*)，**不能把 chColor 本身改成返回变量引用**，只能对三处 DOM 模板调用点（2317/2180/2191）单独改。
- [建议] 验证点补：① 亮→暗→亮往返；② 先访问统计页再回首页切主题——state.data 为陈旧 stats 数据，现守卫会实际执行 chartToday(state.data.today_trend) 用错数据重渲首页 24h 图（比"整体跳过"更糟，修复需同时覆盖"守卫跳过"与"脏数据误重渲"两种态）；③ 7d/30d 档 hourly 卡隐藏时切主题不报错；④ 切语言后再切主题。
- [建议] P1(7/10) 属上限用法：残留会在切页签/档位时自愈，支撑 P1 的是"默认页签必现+影响面广+低成本一次收敛"；建议与问题5 同区域合并实施。
- [建议] 坚持"模块级缓存数据"取向，勿改切主题时重拉 loadReportAll()。

### 用户体验官：通过

核实：三条根因属实且**残留清单无遗漏**（全文件 grep 内联色仅 2180/2191/2317 三处，报告全覆盖）；尼尔森跨页分裂现状描述正确。

意见：
- [建议] 阶段3 必须锁定"模块级缓存+同步重渲"，禁止切主题触发网络重拉（会把即时反馈退化成 0~3.4s 卡顿）。
- [建议] 数据源陷阱：首页分支现写 `chartToday(state.data.today_trend)`——null 抛错或残留旧 stats 值（错数据比错颜色更伤信任），须改为按视图取各自模块级缓存。
- [建议] refreshIcons 清单漏统计页模型表（app.js:892 的 modelIcon 单元格），应统一重渲所有含 modelIcon 的表体。
- [建议] 表格重渲只替换 tbody 或恢复 scrollTop，避免滚动位置丢失。
- 行号微偏（守卫实为 2340；内联色实为 2180/2191），不影响结论。

## 轮次判定

第 1 轮：3/3 通过 → streak=1（目标 streak=2，进入第 2 轮复审，材料不修订）

## 第 2 轮（2026-09-05，材料未修订复审）

### 架构师：通过
独立复核与第 1 轮一致（守卫 2340/9 处 Chart 中缺 4 处/内联色恰 3 处/modelIcon 五处表体中 4 处无人管）；另排查 sparklineSvg（app.js:1596）色来自后端常量，不属残留清单。意见：
- [建议] 缓存写入点落在 seq 守卫块内（单渠道 trend 写在 app.js:547 之后；all 页 daily/hourly 写在 loadReportAll 成功路径 2134-2141），"最新胜出"。
- [建议] `CH_COLOR[ch]` 保留未知渠道兜底（`|| "#4f8ef7"`），避免 `color:undefined` 静默失效。
- [建议] cHourly 重渲前查卡片可见性（app.js:2138/2143 hidden 时 canvas 零尺寸重建失败）；rerenderCharts 各分支"无缓存即 no-op"，保护 applyCurrency 调用方语义。

### 产品经理：通过
- [建议] modelIcon 表体共 5 处：892(zcode)/1010(**dsh，报告未点名**)/1095(cc)/1244(mr-list 随 chartModel 自愈)/1367(记录表)；重渲清单按 grep 确定，勿照抄报告点名（会漏 dsh）。
- [建议] **缓存须与 state.reportMetric/range 键控**：切过指标（Token/费用/请求）后切主题，单份缓存会用旧指标数据重渲三图；7d/30d 档 hourly 缓存置空跳过。
- [建议] 验证点补双入口一致性（设置页主题 pills app.js:2013 + 顶栏按钮 app.js:397 同走 applyDarkMode）。

### 用户体验官：通过
- [建议] 图标变体覆盖面比报告更宽：zcode/dsh/cc/records 四张表体统一纳入 refreshIcons（mr-list 随 chartModel 自愈）；验证点补"统计页三张模型表图标变体即时切换"。
- [建议] 重渲路径关闭 Chart.js 入场动画（animation:false），避免切主题时集体重播生长/扫入动画，与 body .2s transition 动效节奏不一致。
- [建议] applyLang 会重渲记录表而 applyDarkMode 不做同等处理的不对称正是根因③来源；优先修复方向 2（内联色 var() 化），chColor 本体不可改（Canvas 消费）。

## 轮次判定

第 2 轮：3/3 通过 → **streak=2，门禁1 通过**（诊断报告成立，实施建议带入阶段3）
