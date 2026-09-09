# 候选问题清单（2026-09-06 · 第四轮迭代）

- 项目类型：全栈（pywebview 桌面：Python 后端 app/ + 前端 app/web/，依据 index.html + pyproject/requirements + server.py）
- 已读进化日志：是（排除已修复 EVOLUTION-1~9；排除渠道色/配额通栏 f6dda34；排除 Codex 统计新需求）
- 扫描方式：
  1. 静态复核：第三轮候补池显示项逐项复核（Explore 子代理，全部 file:line 落到当前代码）；
  2. 截图走查：serve_ui.py 独立服务 + IAB 浏览器，1280/800 宽 × 亮/暗 × 5 页（home/stats/records/settings/about）共 10 张，另做 DOM 定量（溢出检测、rAF 帧率、遮罩状态）与注入实验（长渠道名 55/115 字符）；
  3. 方法论遵循第三轮认知：截图异常必须 DOM 双重验证后才定案（本轮"截图显示欢迎页"实为 login-overlay 真实覆盖，非伪影；"截图超时"经 rAF 1fps 证实页面静止，属探针管线伪影，不计入候选）。

## 前 3 名候选

| # | 问题 | 维度 | 文件:行号 | 现象 | 预估等级 | 损伤指数 | 影响面×修复收益 |
|---|---|---|---|---|---|---|---|
| 1 | EVOLUTION-10：DSH 两表无溢出防线，长渠道/模型名撑破并裁死数字列 | UI 一致性 | `app/web/style.css:471`（防线只写 `.zcode-stats .tbl td`，漏 `.dsh-stats`）、`style.css:295`（.tbl td nowrap）、`index.html:141-142`（DSH 两表无 .tbl-scroll 包裹，全项目仅 index.html:76 用过一次） | 800px CSS 宽（出厂 DPI 下即默认窗宽）注入 115 字符渠道名实测：表格撑到 1177px、卡片仅 707px，步数/输入/输出/速度四列全部被裁且**无横向滚动可达**（doc scrollWidth 保持 800，内容溢出被裁死）。第三轮认知明确"裁死不可达比显示不全伤害更高"，且 style.css:470 注释自述该防线防的就是"用户自定义字符串"——DSH provider/model 恰是这类数据 | P2 | 6/10 | 影响面：统计页 DSH 区 × 窄窗（默认场景）× 自定义 provider 名用户；修复收益：复用既有 .tbl-scroll + td max-width 防线，一处选择器扩展 + 一处包裹，模式已被 EVOLUTION-8 验证 |
| 2 | EVOLUTION-11：错误恢复入口不对等——非首页数据区失败无自愈路径 | 操作流程/一致性 | `app.js:522-532`（dashboard 有 data-dash-retry 重试按钮，唯一例外）；`app.js:757-761`（zcode 配额失败仅 toast+容器隐藏）；`app.js:839`、`app.js:1069`（统计页 ZCode/CC summary 失败**静默** box.hidden=true，无 toast 无重试）；`app.js:647`（opencode 配额块失败仅文字提示无按钮）；`app.js:987`（DSH 失败仅 toast） | 同一后端故障下，首页有重试按钮、其余区块梯度不对等：toast 无入口 → 纯文字 → 完全静默消失。统计页两个区块失败后用户看到的是区块"凭空消失"，误以为功能不存在；无任何入口能恢复（仅等自动刷新周期） | P2 | 5.5/10 | 影响面：所有非首页数据区块 × 弱网/后端故障场景；修复收益：统一错误态（占位+重试按钮），消除"静默消失"这一最差形态 |
| 3 | EVOLUTION-12：长文本溢出保护缺口三处（.ov-acc-name / #set-datadir / 单渠道 .acct-name） | UI 一致性 | `style.css:315`（.ov-acc-name 仅 font 定义）+ `style.css:314-317`（.ov-acc-head flex 三子项无 min-width:0，且 .ov-acc-sync 的 ellipsis 被 nowrap 抵消失效）；`index.html:226`（#set-datadir 无任何 CSS 规则，Windows 反斜杠路径无折行点）；`style.css:512`（单渠道 .acct-name 无保护，低危——.acct-quota 通栏下仅折行增高） | 长无空格账户名（重命名上限 50 字符 app.js:1942 / UUID 型名）撑破总览卡片头部行；长数据目录路径不折行溢出设置页行框（#set-sync-info 同构风险更低） | P2 | 4.5/10 | 影响面：总览面板（默认关闭，需开启）+ 设置页数据目录行；修复收益：min-width:0 + ellipsis / word-break 三处小改，与 EVOLUTION-8 的 tb-left/um-meta 修复同族 |

## 备选池（本轮新发现与候补池存活项，供后续轮次）

1. 空态写法不统一：4 类机制 5 种文案——setChartEmpty 统一入口 7 处（app.js:2359）vs 手写遮罩 2 处且文案不同（app.js:934-936/1145-1147 zcodeNoData"暂无数据"）vs 表格空行 8 处 inline style vs 1 处 .empty-cell（style.css:307，app.js:2470）vs 整块隐藏无占位 4 处（app.js:716-719/759/839/1069）；附带 setChartEmpty 的 canvasId 参数从未使用（签名误导）。
2. `overflow-y: overlay` 废弃值 4 处（style.css:120/122/125/310）：新 WebView2 按 auto 处理，注释承诺的"悬浮滚动条不占宽"失效，滚动条占宽回归。
3. 死 CSS 4 类零使用：.sk-chart（style.css:175）/ .tc-grid.tc-6（251）/ .bottom-col（262）/ .tag（364）。
4. index.html 图表盒行内 style 硬编码 10 处（min-height/height），其中 :73 的 position:relative 与 .chart-box CSS 重复。
5. 3/4 列网格无 @media 收缩（.usage-blocks/.acct-quota-body/.zcode-cards/.ov-quota-grid/.cc-grid/.windows-bar/.kpi-row）：min 窗口 1000px 下各格仍有 215-300px，属防御缺口非现实破版。
6. applyLang 保留的 loadRecords 写穿（第三轮遗留）。
7. .ub-meta 窄格折行导致同行卡片高度参差（已证实**不会重叠**，轻微）。
8. BAI/CC 未登录行「登录」按 source 分流（EVOLUTION-2/3 遗留，非显示类）。

## 已排除（本轮动态/静态验证不成立，记录防重复扫描）

- records 页「共 0 会话」与 DSH 415 口径矛盾：计数与表格行出自同一响应（server.py:1434/1517），DSH 数据不进入这两个端点，页面自洽。纯 DSH 用户看到"共 0 会话+空表"是准确显示。
- .wb-v 抖动：内容恒为单行短串（fmtTokens ≤8 字符），.wb-cell repeat(4,1fr) 下永不折行。
- .ub-meta 文案重叠：flex 布局结构上不可能重叠，.ub overflow:hidden 兜底。

## 排序说明

预估严重等级优先（三项均 P2，无 P0/P1 候选——前四轮已把高危项清空）；同等级内按影响面×修复收益排序：EVOLUTION-10 触发面最实（自定义 provider 名 + 默认窄窗 + 裁死不可达）、修复模式已被上轮验证；EVOLUTION-11 影响面宽但触发依赖故障场景；EVOLUTION-12 触发条件最窄（需 50 字符重命名/自定义长路径）。
