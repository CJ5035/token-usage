# 门禁2 投票记录 · EVOLUTION-4（实施计划）

被评审材料：`doc/20260905-evolution-plan-4.md`（v1 → 体验官阻塞 → v2）

## 第 1 轮（2026-09-05）

### 架构师：通过（14 处锚点核实）
- [建议] §1 伪码"null 抛错"与代码不符（chartToday:1164 有空值守卫），真实陷阱仅"陈旧 stats 数据"；静态断言措辞收窄为"不存在顶层 if (!state.data) return;"（统计页分支保留 state.data 属预期）。
- [建议] §4 records 表体缺数据源（loadRecords 无模块缓存），需补 recordsLast 或纯函数，禁止重拉。
- [建议] §2 `await daily` 实为 2134（差 2 行）；hourly 需先落局部变量再写缓存；loadReportAll 入口先置空两缓存收窄瞬态。
- [建议] §4 表体重渲加页面可见性门；ovAccountsCache 写死一种数据形态。

### 产品经理：通过
- [建议] **loadReportAll 现无 seq 守卫**，"写入点全落守卫块"不成立——需读侧校验（重渲前比对缓存键与 state.*），否则连点指标响应乱序时旧指标数据重渲。
- [建议] 静态断言措辞同上；applyCurrency 同族遗留（切货币首页残留）登记候选池；records 重渲锁定现有行数据不重发接口；补"在途场景 no-op"验证点。

### 用户体验官：驳回

- [阻塞] §4 records 表体重渲无数据源，不可执行且引入新可用性问题：loadRecords 响应直接写入 DOM 后丢弃、无任何模块缓存；唯一现成路径是重拉（违反零网络承诺+异步延迟+重建筛选下拉干扰操作）。期望：记录页切主题图标变体**同步切换、零网络、分页/筛选态不动**。改法二选一：① recordsLast 模块缓存（seq 守卫后写入）+ 缓存空则 no-op；② **原地换 img src**（img 自带 alt=模型名，按主题重算 themed 改 src，四表一套逻辑、零缓存、滚动/分页/筛选天然保持）。
- [建议] refreshIcons 双调用收敛（applyDarkMode:449 与 rerenderCharts 末尾重复），明确唯一入口。
- [建议] 内联 var() 色跳变补 transition: .2s 与全局节奏对齐（4 渠道亮暗色值不同）。
- [建议] ovAccountsCache 写死一种形态。

## 第 1 轮判定

存在驳回票 → streak=0。主 agent 复核阻塞**属实**（loadRecords:1347-1386 确无缓存落点）→ 采纳体验官方案②（原地换 src，更简更稳）+ 两席建议修订至 v2 → 第 2 轮。

## 第 2 轮（2026-09-05，评审对象 v2）

### 架构师：通过（对照表 5/5 落实；chartModel 双调/noAnim 缺口为新发现）
- [建议] refreshIcons 与 rerenderCharts 统计分支对 chartModel 双重调用且未传 noAnim——从 refreshIcons 移除（统计分支已覆盖且 mr-list 随 chartModel 重渲）或统一传 noAnim；伪码 reportDailyCache → .data；dark 变量未使用。
- [建议] themedName 契约精确化：收原始模型名内部封装 1389-1400 全部逻辑（baseName 中间层勿做 split——muse→meta/hy2→hy/deepseek 兜底丢失会写坏 src）。
- [建议] 改动范围/回滚补 style.css（§3 两条 transition）。
- [建议] "零网络"验收措辞收窄（图标静态文件首次变体切换允许一次请求）。
- [建议] 内联 var() 兜底边界说明（新增渠道同步 CH_COLOR 与两套变量）。

### 产品经理：通过（对照表 5/5 落实）
- [建议] 改动范围/回滚补 style.css（同架构师）。
- [建议] applyCurrency 转可裁决项：补走查点"切货币首页图即时更新"，通过则候选池销项。
- [建议] 伪码小瑕（dark 未用；锚点以 chartReportDonut(daily) 后为准）；mr-list 变体纳入统计页走查。

### 用户体验官：通过（对照表：1 阻塞解除 + 3 建议落实）
- [建议] §3 按"用法"表述：2180/2191 行 dot background+name color 同行、2317 td color，静态断言覆盖 color 用法（防"点新字旧"）。
- [建议] chTrendCache 键控写死 state.range（勿写接口 date 参数）+ 测试点补"单渠道 7d/30d 档切主题 24h 图随动"。
- [建议] themedName 契约同架构师（三映射丢失会 404 破图）。
- [建议] chartModel 双重建与 noAnim 统一（同架构师）。

## 第 2 轮判定

3/3 通过 → streak=1。吸收建议修订至 v3（全部为实施级精确化，不动方案骨架）→ 第 3 轮。

## 第 3 轮（2026-09-05，评审对象 v3）

### 架构师：通过（对照表 5/5 落实；22 处锚点全部核实）
- [建议] reportHourlyCache.data 伪码（否则 Object.keys(undefined) 抛错中断调用链）；hourly 先落局部变量；td transition 限定选择器。

### 产品经理：通过（对照表 4/4 落实）
- [建议] 静态断言按用法分 background/color；applyCurrency 销项随完成报告登记；跨页自愈锚点走查。

### 用户体验官：通过（对照表 4/4 落实）
- [建议] 写入点加键校验根治乱序覆盖；反向断言防"点新字旧"半改；noAnim 函数清单 9 个；td 选择器明确；伪码指回 §2；applyCurrency 条目补全单渠道 renderOverview 问题；补"连点指标后切主题"验证点。

## 第 3 轮判定

3/3 通过 → **streak=2，门禁2 通过**。第 3 轮建议以"实施备注"附录进 plan-4（SDD 任务卡吸收）。

---

# 门禁2 总判定（EVOLUTION-4）

3 轮通过（1 轮 2/3 → 修订 → 2 轮 3/3 → 精确化 → 3 轮 3/3）。计划 v3 + 实施备注可交付 SDD。
