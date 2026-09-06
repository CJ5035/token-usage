# EVOLUTION-7 门禁2 投票记录（计划评审）

## 第 1 轮（2026-09-06）

### 架构师：通过

核实记录：7 容器均 .chart-box（style.css:204 position:relative）；7 图函数全部调用点核实（stack/donut/hourly×2、chartToday×3、chartModel×3、chartTrend×2、chartOvTrend×2），函数内守卫全覆盖无遗漏；safeResize 对 null 安全；EVOLUTION-4/5 交互无冲突；server compare 赋值安全（db.py:2423 恒含 compare 键）；renderWindows 新优先级可同时消除 R5 两种荒谬形态且回滚可行。

建议：
1. 占位文案与档位联动：report-hourly 在 yesterday 档标题动态切「昨日」（app.js:2191-2192）但空占位固定「今日暂无用量」→ 矛盾；建议 yesterday 档用中性 key；stack/donut 在 today/yesterday 档可就近复用 noUsageToday（可选）。
2. `.cmp-dsh-note` 无样式定义条目，需明确（或继承 .wb-s 或补 color: var(--text3)）。
3. hint 调用点遗漏 summary 失败路径（app.js:818 / :1045 catch 置 null 不触发 updateStatsScopeHint），可补调用或声明接受瞬态。
4. 计划 C"否则 hidden=true"与风险表"null 不触发隐藏"有实现歧义，建议明确纯函数语义。
5. 基线数字需复核：实测 pytest --collect-only 416 项，计划写 413 passed；实施前重跑全量确认基线。

### 产品经理：通过

核实记录：计划引用代码位置与源码一致；四条修复线齐备；改动范围（3 源文件 +1 测试，约 +40 行）与 P2 匹配；诊断 5 组验收场景在计划第 4 节全有对应。

建议：
1. §1.1"容器需确认 position:relative"可关闭：.chart-box 已含，写入实施备注防画蛇添足。
2. cost 档下 tokens>0 但成本全 0 时显示「该范围暂无数据」语义略宽——罕见边界，记录已知取舍或现场区分文案。
3. cmp-dsh-note 与「↑84.9% vs 昨日同时段」拼接在 1/4 宽格可能折行（800px 更甚）——建议挪入既有 wb-since 标注行或缩短文案；验收 3/5 顺带核对。
4. statsScopeHint 文案「（今日窗口已并入 DSH）」可能被误读为统计页今天档已含 DSH——加页面前限定语。
5. chartModel models 非空全 0 时仍渲染空环——与"统一无非零判定"表述有出入，测试断言 1 勿按统一口径写死。

### 用户体验官：驳回

阻塞：
1. **cmp-dsh-note 塞 today 格副行制造破版+染警示色**：.wb-s 副行在 1/4 宽格内，1280px 折行、800px 折 2-3 行致 today 格膨胀底边不齐（与 EVOLUTION-8 同族破版）；spike 为真时整段继承 .wb-s.spike 琥珀加粗，口径说明被染成涨跌警示色。期望：口径标注沿用组件既有设计语言——通栏标注行 .wb-since（app.js:2275-2279 notes 机制、style.css:486 grid-column:1/-1，est-badge 先例）：渲染百分比且 includes_dsh_today===true 时 `notes.push(t("cmpExcludesDsh"))`，删除 .cmp-dsh-note span；§1.4 断言 3 改锚 notes 行。
2. **改动清单缺 style.css**：.stats-scope-hint 新类无落地条目，按 §1 派发将以浏览器默认样式渲染。期望：新增 CSS 类必须有对应改动条目（若上条采纳 cmp-dsh-note 取消，本条聚焦 hint 类）。

建议：
1. .stats-scope-hint（12px）与既有 .scope-hint（style.css:487，11px）命名近字号异——直接复用 .scope-hint 或对齐 11px。
2. §1.2-D 已知边界"切语言占位保持旧语言"会造成 hint 已翻译/占位未翻译混排——applyLang 顺带对已显示 emptyEl 重设 t(key)（复用 setChartEmpty 约 3 行），不留给 EVOLUTION-9。
3. §4 验收补：800px 窗宽 hint 与占位实拍核对；hint 与右下 zcodeCostHint 同屏语义不混读核对。

### 判定

streak = 0（存在驳回票）。修订计划 v2 后进入第 2 轮。

## 修订对照表（第 1 轮意见 → 落实情况，v2）

| 上轮意见 | 落实情况 |
|---|---|
| 体验官-阻塞1：cmp 标注挪 wb-since | ✅ §1.2-B 改为 notes.push 进 wb-since 通栏行，删除 .cmp-dsh-note；断言 3 改锚 notes 行 |
| 体验官-阻塞2：style.css 条目 | ✅ 核实 .scope-hint（style.css:487）为独立类无排他选择器，hint 直接复用该类——**style.css 零改动**并显式写入 §1 与 §2 说明 |
| 体验官-建议1：hint 复用 .scope-hint | ✅ 同上（1.1 元素改 class="scope-hint"） |
| 体验官-建议2：applyLang 重设占位文案 | ✅ §1.2 新增 applyLang 对已显示 emptyEl 重设（复用 setChartEmpty，约 3 行） |
| 体验官-建议3：800px 实拍+语义不混读 | ✅ §4 验收场景 2/3 补核对点 |
| 架构师-建议1：hourly 档位联动 | ✅ §1.2-A：hourly 空文案 key 按 range 联动（today→noUsageToday / 其余→noDataInRange）；stack/donut 统一中性文案不做联动（复杂度取舍，写入实施备注） |
| 架构师-建议2：cmp-dsh-note 样式 | ✅ 随阻塞1 取消该类 |
| 架构师-建议3：summary 失败路径调用 | ✅ §1.2-C 调用点补两处 catch |
| 架构师-建议4：纯函数语义 | ✅ §3 实施备注明确（null 不计"有数据"，条件不成立即隐藏，多点调用自愈） |
| 架构师-建议5：基线复核 | ✅ §4 测试节改为"实施前先重跑全量记录基线" |
| PM-建议1：position:relative 关闭项 | ✅ §3 实施备注明确无需补 inline 定位 |
| PM-建议2：cost 档已知取舍 | ✅ §3 记录已知边界（统一中性文案，不按指标档分叉） |
| PM-建议3：cmp 折行 | ✅ 随阻塞1 挪 wb-since 通栏行（1/1 宽，无折行问题）；验收仍保留窄窗核对 |
| PM-建议4：hint 文案限定语 | ✅ §1.2-D statsScopeHint 文案改精确限定（"首页「今天」合计已并入今日 DSH 用量"） |
| PM-建议5：chartModel 断言例外 | ✅ §1.4 断言 1 对 chartModel 单独锚定（不按统一口径写死） |

## 第 2 轮（2026-09-06）

### 架构师：通过

建议：
1. hourly 空 key 联动的 range 取值应显式传参：loadReportAll 调用点传局部 range 快照、rerenderCharts 路径传 reportHourlyCache.range（该校验行已保证 cache.range === state.range）——避免图函数内读全局 state.range 在 await 乱序窗口出现数据档位与文案档位错位。
2. §1.4 断言 3 锚定粒度：锚新增分支代码片段本身，勿对 renderWindows 全函数体做反向文本匹配（既有 cmp 箭头行本就含 ↑，防误报/漏报）。

补充核实：7 容器全 .chart-box；.scope-hint 复用成立；donut 守卫前置无碰撞；server 双分支键安全；applyLang 段 report 三图不经图函数重渲——§1.2-D「记录语义 key」兜底自洽。

对照表核对：5/5 已落实。

### 产品经理：通过

建议：
1. §4 场景 1 补「hint 仅在本地渠道区有数据时显示，真·全新环境（本地渠道目录也无数据）hint 不显示属正确行为」——防实施者在干净环境误判 hint 未显示为缺陷。

补充核实：spike 染色路径确认存在且整改后消除；includes_dsh_today 与零用量分支互斥闭环；renderDsh 失败路径不置 null（:962 保留旧缓存）与多点调用语义自洽。

对照表核对：5/5 已落实（含两阻塞项整改核实）。

### 用户体验官：通过

建议：
1. §4 场景 3 wb-since 实拍覆盖最长拼接形态（data_since + est-badge + cmpExcludesDsh 三段同现，800px 窗宽）。
2. statsScopeHint 长文案（中文约 50 字）800px 折 2-3 行属预期，实拍顺带确认折行后可读性（行距/与 KPI 卡间距）。

补充核实：spike 要求 today>2×avg7 → tokens=0 时恒 False，染色彻底闭环；.scope-hint 纯类选择器、index.html:66 同类同位先例；applyLang 段 chartToday 受 homeVisible 门控、report 三图不重渲——重设方案必要且可行。

对照表核对：5/5 已落实（含 2 阻塞项，另核实染色闭环）。

### 判定

streak = 1（第 2 轮 3/3 全票）。按门禁状态机需连续两轮全票，吸收 5 条非阻塞建议出 v3 后进入第 3 轮。

### v3 修订对照表

| 第 2 轮意见 | 落实 |
|---|---|
| 架构师-1：range 显式传参 | ✅ §1.2-A 改为调用点传参（loadReportAll 传局部快照、rerenderCharts 传 cache.range），图函数不读全局 |
| 架构师-2：断言锚定粒度 | ✅ §1.4 断言 3 明确锚新增分支片段 |
| PM-1：干净环境 hint 预期 | ✅ §4 场景 1 补说明 |
| 体验官-1：wb-since 最长拼接实拍 | ✅ §4 场景 3 补三段同现 800px |
| 体验官-2：hint 长文案折行可读性 | ✅ §4 场景 2 补核对 |

## 第 3 轮（2026-09-06）—— 门禁2 通过轮

### 架构师：通过

建议（派发级，非阻塞）：
1. hourly 签名规格：现签名 `chartReportHourly(d, noAnim)`（app.js:2353），v3 的 `chartReportHourly(d, emptyKey)` 写法会让实施者把第二参改为 emptyKey、丢失 EVOLUTION-4 的 noAnim → 主题重渲重播入场动画。改法：签名取 `(d, noAnim, emptyKey)`，rerenderCharts 调用点传 `(cache.data, true, t(cache.range === "today" ? "noUsageToday" : "noDataInRange"))`；emptyKey 语义统一为「传 i18n key、调用点三元求值、t() 延迟」。**已补入计划 §3 实施备注 13**。
2. （核实记录）全部锚点复核成立（loadReportAll:2163 局部快照、rerenderCharts:2410 键校验、notes 机制、catch 路径、server 双分支、index.html 位置、先例行号）。

对照表核对：2/2 已落实。

### 产品经理：通过

无新增意见。抽查确认 5 条落实无新矛盾（场景 1 两种环境设定自洽、spike 染色与 wb-since 互不接触、产品判据三线执行一致、P2 与改动量匹配）。

对照表核对：1/1 已落实。

### 用户体验官：通过

无新增意见。前两轮阻塞项整改在源码层面闭环（spike 类仅挂 today 格 .wb-s、style.css:485 不触及 wb-since；7 容器/先例/传参可行性/applyLang 必要性/server 键安全全部抽查一致）。

对照表核对：2/2 已落实。

### 判定

streak = 2（第 2、3 轮连续全票）→ **门禁2 通过**，计划 v3 定稿，派发 SDD 实施。
