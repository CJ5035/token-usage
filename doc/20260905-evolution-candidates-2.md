# 候选问题清单（2026-09-05 · 第二轮：页面显示优化）

- **项目类型**：全栈（Python 桌面后端 pywebview + 本地 HTTP + vanilla JS 前端）
- **已读进化日志**：是（排除第一轮已修复 3 项；排除 `doc/20260904-bug-diagnosis-home-ui-7issues.md` 7 项——工作区已落地修复，本轮截图复核确认生效：三卡横排、qb-card 卡片化、GLM 卡归属、本地渠道占位隐藏）
- **主题**：页面显示优化（用户指定：排版错乱排查 + 更好的显示方式 + 截图分析）
- **扫描方式**：双路探针——① 静态扫描（style.css 511 行 / app.js 2393 行 / index.html 307 行逐项核对）；② 程序截图分析（独立启动 HTTP 服务 + 浏览器实测 12 组截图，覆盖首页全部/单渠道页签 × 亮/暗主题 × 1280/900 窗宽 × 统计/记录/总览/关于页）。截图存于 `.probe/ui-shots/`（21 张）。
- **截图环境备注**：data/ 开发库账号无 token（第一轮登出测试残留），故以"未登录 + 6.5MB 本地用量数据（zcode 1.5B tokens / ¥1160+）"状态为主进行截图；fullPage 截图存在 fixed 顶栏平铺伪影（IAB 工具特性，非应用 bug，已实测排除）。

## 前 3 名候选

> **修正记录（阶段1 复核，两次反转）**：初版候选 1「all 页签图表与明细不渲染」先被"重截图正常"判为截图伪影撤销；**经用户质疑后做计时实验证实是真实性能问题**——渲染函数本身极快（表格 1ms/柱图 8ms/环形图 2ms），但 `/api/report/windows` 冷算 3.2s（第2次 92ms=页缓存热）、并发时 `/api/report/daily` 被单连接串行排队堵到 3.3s（单独 curl 仅 34-60ms），03 截图（点击后 2s）正落在 ~3.4s 渲染窗口内。**教训：截图异常必须以"DOM 真相 + 分环节计时"双重验证后才能定案；"重截图正常"不构成性能问题排除证据。**

| # | 问题 | 维度 | 文件:行号 | 现象 | 预估等级 | 损伤指数 | 影响面×修复收益 |
|---|---|---|---|---|---|---|---|
| 4 | 切主题后图表/渠道色/模型图标残留旧主题配色（重渲覆盖缺口） | UI 一致性 | `app.js:443-451`（applyDarkMode）、`app.js:2339-2348`（rerenderCharts 只覆盖 chartToday，缺 cStack/cDonut/cHourly/cOvTrendChart）、`app.js:2317/2180`（innerHTML 内联 chColor 快照色）、`app.js:1396-1405`（refreshIcons 仅统计页）；style.css:31-36/56-61（亮暗两套渠道色板） | **关键机制：state.data 仅在非首页路径（renderAll）赋值，而 loadReportAll/单渠道分支不写它——用户停在首页（任何页签）切主题时 rerenderCharts 因 `if (!state.data) return` 整体跳过，图表 100% 残留旧配色**；总览页 7 日趋势图与表格渠道色/模型图标在任何页签下都不随主题更新 | **P1** | 7/10 | 中×高 |
| 5 | 首页 all 页签加载/切档位存在 0~3.4s 无反馈空窗（慢端点 + 单连接串行放大 + 无 loading 态） | UI（反馈缺失）/性能 | `app/server.py:1063-1084`（_report_windows_response 无应用层缓存，直调 db.report_windows 全表扫）、`app/db.py`（report_windows/report_daily 无 idx_usage_day 表达式索引——grep 证实 20260904 方案 4① 未实施）、`app/web/app.js:2119-2150`（loadReportAll 的 Promise.all 4-5 端点并发，单分支无 swapping 类，对照单渠道分支 :547 有） | 实测：浏览器内并发计时 windows 3297ms / daily 3334ms（各自单独请求 92ms/34-60ms）；SQLite 单连接使并发请求串行排队，一个慢端点把整条渲染链堵住；空窗内旧内容残留或空白，无任何加载指示。冷启动首屏/切档位/页缓存失效时必现 | **P2** | 6/10 | 高×高 |
| 6 | 暗色主题系统性遗漏（badge.ok 刺眼 + 小字号对比不足 + 涨跌色硬编码） | UI 一致性 | style.css:336（badge.ok 无 dark 覆盖，对照 badge.no:55 有）；style.css:45（--text3 暗色 3.2:1 < 4.5:1，卡片标题/表头/hint 发灰——zoom 截图实证「会话用量」标题几乎不可读）；style.css:478-479/496（#16a34a/#dc2626 绕过 token） | 暗色模式下：设置页「当前」徽标亮薄荷绿底刺眼；大量 11-12px 提示文字（wb-l/kpi-l/表头/hint）对比不足；涨跌/尖峰色硬编码主题失联。~~select 无暗色~~（初扫误报，zoom 核实 .select token 正常生效，撤销） | **P2** | 5.5/10 | 中×高 |

## 排序说明

预估严重等级优先（P1 > P2）；同等级内按影响面×修复收益：
- #4 为唯一 P1："停在首页切主题"场景 100% 复现（state.data 守卫必 return），影响所有切主题用户的核心视图。
- #5 影响面「高」（冷启动首屏/每次切档位）×收益「高」（20260904 已评审方案 4①② 沿用即可）；损伤 6/10 接近 P1 线（主要流程能走通但高频无反馈等待）。
- #6 暗色用户全部受影响，四类遗漏一揽子修收益高。

## 备选池（本轮不处理，留给后续迭代）

| 来源 | 问题 | 预估等级 | 指数 |
|---|---|---|---|
| 截图新发现 | 空数据/零值状态无显示策略：统计页「模型用量/用量趋势」整卡空白、总览页「7 日费用趋势对比」空白、首页 today 档空序列 Y 轴伪影刻度 `1 1 0 0`（Chart.js 空数据真实渲染）；统计页主区 KPI 全 0（活跃账号口径）vs 下方 ZCode 区 ¥2453 同页矛盾无提示 | P2 | 5 |
| 静态 UI-05 | tooltip 中英双向泄漏（index.html 12 处 + app.js:2158） | P2 | 5 |
| 静态 UI-06 | `#page-stats .two-col` ID 特异性压死 `@media(max-width:1000px)` 断点，窄窗不折叠（style.css:265 vs 408-410） | P2 | 5 |
| 静态 UI-08 | 溢出缺失：首页 .acct-name 无 ellipsis（style.css:500）、.ov-acc-name（style.css:310）、#set-datadir 长路径（index.html:225）、DSH 两表不在 td 省略保护内（style.css:463 选择器只盖 .zcode-stats） | P2 | 4.5 |
| 静态 UI-11 | 切语言后首页 all 页签动态区块保持旧语言（applyLang 无 loadReportAll，app.js:335-362 + 1408-1440） | P2 | 5 |
| 静态 UI-12 | data-i18n-title 全工程无处理逻辑，#report-est tooltip 永远为空（index.html:72） | P2 | 4 |
| 静态 UI-04 | 表格空态行三套写法并存（padding 12/20/24px，app.js 10 处） | P2 | 3 |
| 静态 UI-09/10/14/15/16 | .wb-v 数字宽度抖动；.ub.c-month 饰条与进度条渐变色不一致；overflow-y:overlay 废弃；.user-row.active 无 CSS 规则；PLAN_BADGE 死代码；innerHTML 行内样式散落；option 内嵌 span 非法；英文长文案两处无 wrap 兜底 | P2低 | 1-3 |

> 静态扫描确认无问题项：z-index 层级有序；meta viewport 已有；主题切换 body 过渡正常（截图 12 的"背景残留"经 2.5s 复核为过渡中间态，排除）。

## 截图证据索引（.probe/ui-shots/）

| 文件 | 场景 | 关键发现 |
|---|---|---|
| 01-settings-loggedout.png | 设置页（未登录账号列表） | EVOLUTION-2 未登录行正常；fullPage 伪影（工具） |
| 02-home-all-today.png | 首页 all·今天·切页后 1.6s | **整页空白**（候选池[推测]项） |
| 02b-home-all-today-retry.png | 同上·自愈后 | 图表空+伪影轴；donut 中心 0；明细仅 dsh；「¥0.0000」；「↑100%」 |
| 03-home-all-30d.png | 首页 all·近30天 | KPI 1.52B 有数据但三图仍空（候选 1 主证据） |
| 04-home-zcode-30d.png | 首页 zcode 页签 | （待复核：GLM 卡归属正确） |
| 05-stats-30d.png | 统计页·近7天 | 主区全 0 vs ZCode 区 ¥2453 矛盾；模型用量/用量趋势卡全空白 |
| 06-records.png / 07-records-dark.png | 记录页 亮/暗 | 暗色：卡片标题对比极低；select 亮白；空态"暂无记录"正常 |
| 08-home-zcode-dark.png | zcode 页签·暗色·900px | 数据完整正常；三卡横排；GLM 卡归属正确 |
| 09-home-zcode-900w-dark.png | 900px 窄窗 | 布局无破版 |
| 10-overview-dark.png | 总览页·切页后 | **整页空白**（同 02，[推测]项） |
| 11-about-dark.png / 11b | 关于页 | 首截空白/重截正常（[推测]项复现样本） |
| 12-overview-light.png | 切回亮色瞬间 | 背景/badge 混合色=主题过渡中间态（排除）；7 日趋势卡空白（G 项） |
| 12b-overview-light-settled.png | 过渡完成后 | 全部正常 |
