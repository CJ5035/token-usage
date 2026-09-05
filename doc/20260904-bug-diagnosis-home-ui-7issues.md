# Bug 诊断报告：首页用量面板 7 项 UI/性能问题

- **日期**：2026-09-04
- **状态**：已确认（7 项问题全部在代码中定位到根因，待用户确认后修复）
- **严重级别**：P2 一般（含 1 项性能问题 P2、6 项 UI 问题 P3）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）

---

## 问题描述

用户在 GoGauge 首页（用量统计总览）反馈 7 个问题：

1. **图1**：commandcode 渠道下「滚动用量 / 每周用量 / 每月用量」三张配额卡竖排显示，应横向排列。
2. **图2**：全部渠道页签下「各渠道配额」摘要条显示方式太丑（纯文本行，形如 `opencode ▓▓▓░ 0% · 1账号 · 0min`）。
3. **图3**：用量统计总览的图表（分渠道消耗趋势 / 渠道占比环形图）配色太暗、不好看。
4. **图4**：顶部切换渠道页签时，页面有秒级卡顿。
5. **图5**：「GLM Coding Plan · ZCode」额度卡出现在 bai 渠道页签下，应只显示在 zcode 渠道页签，且应计入「各渠道配额」。
6. **图6**：本地渠道（claudecode 等）页签显示「本地渠道，无配额概念」文字占位，希望直接不显示配额区。
7. **图7**：commandcode 渠道的「账期汇总」卡片错位（账号名长 UUID 换行挤压、成功率卡独占一行错位）。

## 环境信息

- 分支/版本：main（工作区有未提交修改 app/db.py、app/server.py、app/web/*）
- 相关模块：`app/web/app.js`（前端渲染）、`app/web/style.css`（布局）、`app/server.py`（API 端点）、`app/db.py`（聚合查询）
- 复现步骤：启动 GoGauge → 首页切换渠道页签（commandcode / bai / claudecode）→ 观察配额卡布局、账期汇总、切换流畅度

---

## 可能原因分析（按问题逐项）

### 问题 1：配额三卡竖排

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | 单渠道模式下 `renderQuotaSingle()` 的包裹结构破坏了 `.usage-blocks` 的 3 列 grid | **高** | 代码已证实：`.usage-blocks` 定义 `grid-template-columns: repeat(3,1fr)`（style.css:202），但单渠道渲染时每个账号生成 `.acct-quota` 容器塞进 `#usage-blocks`，3 张 `.ub` 卡全部落在 `.acct-quota` 这 **1 个 grid item** 内部，grid 的 3 列布局对卡 outer 层生效、对 inner 卡无效，块级 div 逐个换行 → 竖排 |
| 2 | `.acct-quota` 自身没有声明任何 grid/flex 布局 | **高**（同一根因的另一面） | style.css:482-483 仅有 margin/字号样式，无列布局定义 |

**调用链**：
```
switchChannel("commandcode")                     [app.js:2020]
→ loadDashboard() 单渠道分支                      [app.js:493-519]
→ renderQuotaSingle(chAccounts)                  [app.js:634-641]
  $("usage-blocks").innerHTML =
    `<div class="acct-quota">…<div class="acct-quota-body">`  ← 1 个账号 = 1 个格子
→ renderUsageBlocks(a.quota, $(`aq-${a.id}`))    [app.js:562]
  3 张 .ub 写入 .acct-quota-body ← 非网格容器, 竖排
```

对比：全部渠道的「全部」tab 不经过此函数；多账号（≥2 个 opencode 账号）时每个 `.acct-quota` 占一个格子横向排，但**每格内部的多窗口仍然竖排**。

### 问题 2：「各渠道配额」摘要条太丑

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | `renderQuotaBar()` 用纯文本字符画渲染（`▓▓▓░`、`·` 拼接） | **高** | app.js:2057-2090。opencode 渠道用 `▓▓▓░ ${pct}%` 字符进度条（app.js:2073），样式只有 `qb-row` 一条 12px 虚线分隔（style.css:477-479），无卡片、无真实进度条、无图标 |

这是**设计缺失**而非 bug：数据都齐（各账号 quota 已拉到），只是渲染成了一行文本。

### 问题 3：图表配色太暗

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | 渠道色板变量取色偏暗/饱和度失衡 | **高** | style.css:31-36：`--ch-bai: #d97706`（暗琥珀）、`--ch-claudecode: #e11d48`（暗玫红）、`--ch-dsh: #64748b`（灰）。zcode `#06b6d4` 面积大时刺眼，与暗色系搭配整体显脏 |
| 2 | 图表堆叠图直接使用 `chColor(ch)` 实色填充，无渐变/圆角/透明度处理 | **中** | app.js:2137 `backgroundColor: chColor(ch)`；环形图 borderWidth:0 无描边（app.js:2172） |

### 问题 4：切换渠道秒级卡顿

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | `db.py` 聚合 SQL 对时间列套函数（`substr(datetime(created_at,'localtime'),1,10) >= date(...)`），**索引失效全表扫描** | **高** | `_report_range_sql`（db.py:2079-2087）生成的 WHERE 均为 `substr(datetime(col,...))` 形式；`idx_usage_time`（db.py:132）、`idx_zcode_time`、`idx_cc_time` 均无法使用。记录 16,444 条时每次切换全表扫多遍 |
| 2 | 单次切 tab 并发 3+ 个重查询端点串行占用**同一把 SQLite 连接** | **高** | `db.get_db()` 是全局单连接（db.py:63-75，`check_same_thread=False` 无 pool）；切换渠道触发 `/api/report/channel-overview` + `/api/report/channel-trend` + `/api/accounts/overview`（app.js:504-507）。`/api/accounts/overview` 对**每个账号**执行 `db.totals + db.today_trend + db.daily_stats`（server.py:1206-1216），3 个账号 ≈ 9 个全表聚合查询排队 |
| 3 | 服务器与 pywebview UI 同进程，Python 端 CPU 密集聚合会抢占 UI 线程 GIL | **中** | main.py:464 `server.start_server()` 同进程；ThreadingHTTPServer（server.py:1476）每请求一线程，但 CPython GIL 下 CPU 密集的 SQLite 聚合（SQLite C 层释放 GIL，但 Python 行构造/dict 组装不释放）仍与 WebView 消息泵争 CPU |
| 4 | 前端切换时**无任何缓存/过渡态**，旧内容直接清空等待响应 | **中** | `switchChannel` → `loadDashboard` 直接 `await` 三个接口，无骨架屏、无 stale-while-revalidate；图表 destroy 后重建（`cStack.destroy()`）放大感知延迟 |
| 5 | `.page` 的 `animation: fade .18s` 与大量 DOM 重建叠加 | **低** | 影响毫秒级，非主因 |

### 问题 5：GLM Coding Plan 出现在 bai 渠道页签

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | `#zcode-quota` 区块在 HTML 上位于单渠道容器 `#report-single` 内且**无渠道条件控制显隐** | **高** | index.html:78-83：`zcode-quota` 是 `report-single` 的直接子节点；前端只在 `loadZcodeQuota()`（app.js:666-677）里控制 hidden——只要 `/api/zcode/quota` 成功就在**任何单渠道 tab**（包括 bai）渲染。图5 正是 bai tab 下出现了 zcode 卡 |
| 2 | 用户预期它属于「渠道配额」聚合条，但 `renderQuotaBar()` 对未知渠道 zcode/claudecode/dsh 只显示账号数不显示额度（app.js:2085-2086 else 分支），且 ZCode 额度数据源（本地 GLM 凭证）与 `accounts/overview` 的账号列表完全解耦 | **高** | 需求性偏差：zcode 无 accounts 行，`byCh` 分组（app.js:2058-2061）永远不含 zcode |

### 问题 6：本地渠道「本地渠道，无配额概念」占位

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | `renderQuotaSingle()` R6 分支：本地渠道无账号时主动渲染 `empty-cell` 占位文本 | **高** | app.js:635-637：`if (!accounts.length) { $("usage-blocks").innerHTML = '<div class="empty-cell">本地渠道，无配额概念</div>'; return; }`。i18n 键 `localNoQuota`（app.js:118/230） |

用户要求改为**整块隐藏**，属需求调整，改法明确。

### 问题 7：CommandCode 账期汇总错位

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | `renderCcAccounts()` 把「账号名 div」与 4 张 `.card.kpi` **平铺塞进同一个 4 列 grid**（`#cc-grid`） | **高** | app.js:646-657：`<div class="acct-name">UUID</div>` + 4 个 kpi 卡共 5 个 grid item。4 列布局下：第 1 行 = 账号名+3 张卡，第 2 行 = 成功率卡 + 3 个空位 → 正是图7 的「成功率独占下一行第一格、与上方错位」；账号名是 36 位 UUID（`.acct-name` 无 ellipsis，style.css:483）撑高行。图1（全部账号只有 1 个时也走该分支，见 renderCcSummary app.js:617-631 同样平铺 4 卡无标题——结构不同但图1 里账号名+3卡+成功率卡错位与图7 一致） |
| 2 | `.acct-name` 无 `text-overflow: ellipsis` / `word-break` 控制 | **中** | 长 UUID 换行把 grid 行高撑开，视觉上加重错位 |

---

## 验证动作

### 针对问题 1（竖排）

- **验证方式**：DevTools 检查 DOM 结构（pywebview 可右键检查或临时加 `webview.start(debug=True)`）
- **位置**：`app/web/app.js:638-640`、`app/web/style.css:202`、`app/web/style.css:482-483`
- **预期**：`#usage-blocks > .acct-quota > .acct-quota-body > .ub×3`。`.usage-blocks` 的 3 列只作用于 `.acct-quota` 层；给 `.acct-quota-body`（或 `.acct-quota`）补 `display:grid; grid-template-columns: repeat(3,1fr)` 后三卡即横排，可证实根因。

### 针对问题 4（卡顿）— 最关键验证

- **验证方式**：Python 脚本对同库跑 EXPLAIN QUERY PLAN + 计时
- **位置**：`app/db.py:2079-2087`（`_report_range_sql`）、`app/server.py:1193-1232`（accounts/overview）
- **具体操作**：
  ```python
  import time
  from app import db
  db.get_db()
  sql = db._report_range_sql("30d", "r.created_at")
  sql_full = f"SELECT COUNT(*) FROM usage_records r LEFT JOIN accounts a ON a.id=r.account_id WHERE {sql} AND COALESCE(a.source,'opencode')='opencode'"
  print(db.get_db().execute("EXPLAIN QUERY PLAN " + sql_full).fetchall())
  # 预期出现 "SCAN r" 而非 "SEARCH ... USING INDEX" → 证实全表扫描
  for _ in range(3):
      t0 = time.perf_counter()
      db.get_db().execute(sql_full).fetchone()
      print(time.perf_counter() - t0)
  ```
- **预期**：计划含 `SCAN usage_records r`；单查十几毫秒~几十毫秒，而切 tab 串行 9+ 个此类查询并叠加 JSON/渲染，总时长进入秒级。
- **辅证**：任务管理器观察切 tab 时 Python 进程 CPU 尖峰。

### 针对问题 5（GLM 卡归属）

- **验证方式**：切到 opencode/commandcode 渠道 tab 观察
- **位置**：`app/web/app.js:493-519`（单渠道分支没有任何 `$("zcode-quota").hidden = ...` 调用）
- **预期**：任何渠道 tab 下 GLM 卡都显示 → 证实缺渠道条件。

### 针对问题 7（账期汇总错位）

- **验证方式**：DevTools 查看 `#cc-grid` 子元素
- **位置**：`app/web/app.js:654-656`、`app/web/style.css:224`
- **预期**：`#cc-grid` 子元素 = `[div.acct-name, card.kpi×4]` 共 5 个节点，4 列 grid 下第 5 个（成功率）换行到第二行行首，且无占位补齐 → 与截图错位一致。

---

## 调用链与依赖分析

### 切换渠道完整链路（问题 4 主链）

```
用户点击渠道 pill
→ document click delegate                     [app.js:2007-2011]
→ switchChannel(ch)                           [app.js:2020-2024]  仅改 active 样式+state
→ loadDashboard()                             [app.js:493-519]
   ├─ renderChannelTabs() → GET /api/report/channels?range=today  (每次都拉!)
   ├─ GET /api/report/channel-overview        → db.channel_totals()   [db.py:2417]  全表扫
   ├─ GET /api/report/channel-trend           → db.channel_trend()    [db.py:2465]  全表扫
   └─ GET /api/accounts/overview              [server.py:1193]
        └─ for 每个账号 (3 个):
             ├─ db.totals("today", aid)       [db.py:1413]  全表扫
             ├─ db.today_trend(aid)           [db.py:1382]  全表扫
             ├─ db.daily_stats(7, aid)        [db.py:1337]  全表扫
             └─ db.get_cc_summary(aid) (cc 才有)
   → Promise.all 等全部返回才渲染 (无骨架/无增量渲染)
→ chartToday() destroy+new Chart              [app.js:1097]
```

注意：**全部渠道 tab** 还要额外拉 `/api/report/windows` + `/api/report/daily` + `/api/report/hourly`（app.js:2032-2050），`report_daily` 是三表 UNION 全表扫（db.py:2106-2134）。

### 关键依赖节点

- **上游**：前端 `state.channel`；`/api/accounts/overview` 同时被 4 处复用（总览页、首页全部 tab 配额条、单渠道配额卡、渠道 tabs 账号数）
- **下游**：SQLite 单连接（`db._DB` 全局共享，WAL 模式）；`_quota_cache` 进程内 TTL 缓存（配额本身不慢，慢在统计聚合）
- **数据流**：`usage_records`（16,444 行）/ `zcode_usage` / `claudecode_usage` / `charts_buckets` → SQL 聚合 → JSON → innerHTML 重建

### 影响范围评估

- 修改 `_report_range_sql` 为可走索引的范围条件 → 影响 report 系全部端点 + `totals/daily_stats/today_trend/channel_totals`（收益最大，风险中：需保持 localtime 语义，可改为 `created_at >= strftime('%Y-%m-%d %H:%M:%S','now','localtime','-29 days')` 形式并接受边界近似，或建表达式索引）
- `accounts/overview` 加聚合结果短 TTL 缓存 → 影响总览页/首页/配额条，纯增益
- 前端布局改动（usage-blocks/cc-grid/quota-bar/zcode-quota 显隐）→ 仅首页 UI，隔离性好

---

## 边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 布局 | 单账号+三窗口（图1） | `.acct-quota` 独占 grid，内部竖排 | 是 | `.acct-quota-body` 改 3 列 grid |
| 布局 | 账号名 36 位 UUID（图7） | `.acct-name` 无省略，撑破行 | 是 | 加 ellipsis 或独立标题行 |
| 布局 | cc-grid 5 元素 4 列（图7） | 成功率孤行 | 是 | 账号名做通栏标题（grid-column: 1/-1）或 4 卡外再包一层 |
| 数据 | 多账号同渠道（opencode×2） | 每账号一格横排，格内仍竖排 | 是 | 同上一并修复 |
| 数据 | zcode 无 accounts 行（问题5） | `byCh` 无 zcode 键，配额条永不显示 ZCode 额度 | 是 | 配额条并入 zcode 额度数据（读 `_zcode_quota_cache`） |
| 性能 | 记录增长到 10 万+ | 每次切 tab 串行 9+ 全表聚合，卡顿线性恶化 | 是 | 索引友好 SQL + overview 短 TTL 缓存 |
| 性能 | 切 tab 期间连点 | 无请求取消，旧响应可能覆盖新状态（单渠道分支无 seq 守卫） | 是（次要） | 参照 `loadSeq` 模式加序号守卫 |
| 空值 | ZCode 凭证缺失 | 显示登录引导框（合理） | 否 | 保持 |
| i18n | 移除 `localNoQuota` 占位后 | 键仍存在但不渲染 | 否 | 顺手清理引用 |

---

## 修复建议汇总（v2，经 Review 第 1 轮修订；待确认后实施）

| # | 问题 | 建议修法 | 改动点 |
|---|------|----------|--------|
| 1 | 三卡竖排 | `.acct-quota-body` 声明 `display:grid; grid-template-columns:repeat(3,1fr); gap:12px`；单账号时账号名行保持（作为分组标题），BAI 单块场景仅占第一格可接受 | style.css + app.js（结构微调） |
| 2 | 配额摘要条丑 | 重做为横向渠道卡组：每渠道一张小卡（渠道名色点 + 真实进度条/余额 + 同步时间），替换 `▓▓▓░` 字符画；**注意** `byCh` 分组天然不含本地渠道，zcode 额度按 #5 的并入方式单独加卡 | app.js `renderQuotaBar()` + style.css `.qb-*` |
| 3 | 图表色暗 | 调亮渠道色板（bai→#f59e0b、claudecode→#fb7185；**dsh 亮色主题不直接抄暗色值 #94a3b8**，白底对比度不足，建议保留 #64748b 或换 #7c8db5 一类中明度蓝灰），堆叠柱加渐变/圆角，环形图加描边 | style.css `:root` 渠道变量 + app.js 图表配置 |
| 4 | 切换卡顿 | ① **首选表达式索引**：`CREATE INDEX idx_usage_day ON usage_records(account_id, substr(datetime(created_at,'localtime'),1,10))`（查询表达式需与索引表达式逐字一致才命中），`_report_range_sql`/`daily_stats`/`today_trend` 保持现表达式即可提速；备选方案（改为原生列比较）存在 UTC↔本地 8 小时换算风险，**today 档不可接受**，仅在表达式索引验证无效时考虑；② `/api/accounts/overview` 加 2~5s TTL 聚合缓存，**必须同步定义失效时机**：账号切换（/api/accounts/switch）、同步完成（pollUntilIdle）、登录成功（gousageOnLoginSuccess）时 clear；③ 切 tab 时旧数据保持显示、响应到达后替换（stale-while-revalidate）；④ 单渠道 Promise.all 分支加 seq 守卫（参照 loadSeq 模式，当前旧响应会以新 state.channel 过滤旧数据覆盖渲染）；⑤ 顺手项：`renderChannelTabs` 每次 loadDashboard 都拉 `/api/report/channels`，可改为仅在账号增减时刷新 | db.py + server.py + app.js |
| 5 | GLM 卡归属 | **两半缺一不可**：a) `loadDashboard` 单渠道分支入口设 `$("zcode-quota").hidden = (state.channel !== "zcode")`；b) **channel==="zcode" 时主动确保渲染**——`loadZcodeQuota()` 目前仅在统计页分支调用（app.js:530），冷启动直接点 zcode 页签时 `zcodeQuotaLast` 为 null，仅加 hidden 条件会导致 GLM 卡不显示。修法：单渠道分支内 `if (state.channel === "zcode") { zcodeQuotaLast ? renderZcodeQuota(zcodeQuotaLast) : loadZcodeQuota(); }`。「各渠道配额」并入 zcode 额度：loadReportAll 的 Promise.all 追加 `/api/zcode/quota`（后端 TTL 30s，过期走后台刷新不阻塞；**仅进程首次为同步调用、上限 15s**，缓解：main.py 启动时预热一次 `_zcode_quota_payload()`，或前端对该请求单独 `.catch` 容忍缺失不阻塞渲染） | app.js（+可选 main.py 预热） |
| 6 | 本地渠道占位 | 本地渠道无账号时 `$("usage-blocks").hidden = true` 且清空内容，不再渲染占位文本；**必须配套**：有账号分支开头恢复 `$("usage-blocks").hidden = false`（hidden 属性不随 innerHTML 更新自动复位，漏掉会导致 opencode/commandcode 页签配额卡消失的回归） | app.js `renderQuotaSingle()` |
| 7 | 账期汇总错位 | `renderCcAccounts` 账号名通栏：选择器**限定 `#cc-grid .acct-name`** 加 `grid-column:1/-1` + `white-space:nowrap; overflow:hidden; text-overflow:ellipsis`（`.acct-name` 被 renderQuotaSingle 的 `.acct-quota` 共用，全局改动会波及问题 1 场景；且 `.acct-name` 不在 grid 容器内时 grid-column 无效但 ellipsis 会误伤） | app.js + style.css |

## 总结与建议

7 项问题根因全部定位：**布局类（1/2/7）是 CSS grid 结构与文本字符画渲染的设计缺陷；性能类（4）是 SQLite 时间过滤套函数导致索引失效 + accounts/overview 每账号 3 个全表聚合在单连接上串行；归属类（5/6）是 zcode-quota 区块缺渠道显隐条件与本地渠道占位逻辑**。建议按「4 → 1/7 → 2/3 → 5/6」顺序修复（先性能后观感），全部改动集中在前端三件套与 db.py 查询层，风险可控。确认后按上表实施。

---

## Review 记录

### 第 1 轮（2026-09-04）：不通过 → 已修订

方案 7 项方向全部判定正确（根因与代码事实逐一比对相符），但存在可执行性缺口：

| 级别 | 方案 | 缺口 | 修订 |
|------|------|------|------|
| P1 | 5 | `loadZcodeQuota()` 仅统计页分支调用（app.js:530），只加 hidden 条件会让冷启动直达 zcode 页签时 GLM 卡不显示——隐藏了「错误显示」却没实现「正确显示」 | 补 channel==="zcode" 时主动渲染/拉取（方案表 5b） |
| P1 | 6 | `usage-blocks.hidden=true` 后切回有账号渠道不会自动复位，漏恢复会让 opencode/commandcode 配额卡消失 | 补有账号分支恢复 hidden=false（方案表 6） |
| P2 | 4① | 原生列比较需 UTC↔本地换算，today 档 8 小时偏移不可接受（created_at 为 API 原样 UTC 串，opencode_api.py:460） | 表达式索引升为首选路线（方案表 4①） |
| P2 | 4② | 缓存无失效时机定义，切账号后可能显示旧账号聚合 | 补三处失效触发点（方案表 4②） |
| P2 | 2/5 | `/api/zcode/quota` 进程首次为同步调用、上限 15s（QUOTA_TIMEOUT，zcode_api.py:44；QUOTA_CACHE_TTL=30s，server.py:33），并入首页 Promise.all 有首屏风险 | 补启动预热/容错缓解（方案表 5） |
| P2 | 7 | `.acct-name` 被 renderQuotaSingle 共用（app.js:639），全局加 ellipsis/grid-column 有波及 | 选择器限定 `#cc-grid .acct-name`（方案表 7） |

另核实：报告正文所称「卡片竖排根因」「账期汇总 5 元素 4 列错位」「`byCh` 不含本地渠道」「单渠道分支无 seq 守卫」均与代码一致，判定成立。

### 第 2 轮（2026-09-04）：通过（附 3 条实施备注）

逐项复核修订后方案表与代码事实：5b/6 的显隐状态机闭环成立（zcode 页签显示 GLM 卡、其余页签隐藏、有账号渠道恢复 usage-blocks）；4① 表达式索引与现有查询表达式一致、不改动 SQL 语义；7 的选择器限定不波及问题 1 场景；3 的 dsh 色值保留原值避免对比度回归。复核中另发现 3 条备注级事项（不构成方案错误，实施时顺带处理）：

1. **applyLang 绕过渠道条件**：`applyLang()` 在语言切换时无条件 `renderZcodeQuota(zcodeQuotaLast)`（app.js:350），会在非 zcode 页签把 `#zcode-quota` 重新置为可见（下次切渠道自愈）。实施时给该处加同样的 `state.channel === "zcode"` 条件。
2. **`_period_where` 同样套函数**（db.py:1282 `datetime(created_at) >= datetime('now', ?)`），影响 `db.totals`（/api/dashboard 与 accounts/overview 路径）；4① 的 substr 表达式索引不覆盖它，可补一条 `datetime(created_at)` 表达式索引，或由 4② 的 overview 缓存掩盖（切换渠道路径不直接触发 /api/dashboard，主体目标不受影响）。
3. **4② 失效时机补全**：账号删除/退出（onUserRowAction 的 delete/logout 后 loadDashboard）也应清缓存，与 switch/登录/同步完成并列。

**判定：方案正确且可执行。**

### 第 3 轮（2026-09-04）：通过

交叉验证第 2 轮备注与整体一致性：备注 1/2/3 经代码复核全部成立（app.js:350、db.py:1282、onUserRowAction 均确认）；组合检查无冲突——方案 1+7 的选择器隔离有效，方案 5a+5b+6 状态机在 all/单渠道/有账号/无账号四象限均闭环，方案 4 各子项独立可回滚，无新增缺口。**连续第 2 次通过，review 终止。**
