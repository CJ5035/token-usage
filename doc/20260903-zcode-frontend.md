# ZCode 前端展示层实施文档（Task 4）

- 日期：2026-09-03
- 状态：**已实施**（规格来源：`.superpowers/sdd/20260903-zcode-integration/task-4-brief.md`，
  该 brief 即经确认的契约；Task 1-3 后端已交付并通过审查）
- 范围：仅 `app/web/` 三件套（index.html / app.js / style.css），**不改任何 Python 文件**

## 1. 交付内容

### 1.1 首页「GLM Coding Plan · ZCode」额度卡（index.html + app.js）

- 插入点：`#usage-blocks` 之后新增 `<div id="zcode-quota" hidden>`（含标题行
  `#zcode-quota-head`（标题 + `#zcode-level` 徽章）+ 卡片行 `#zcode-quota-cards`）。
- 数据获取：`loadDashboard()` 成功后并发拉取 `/api/zcode/quota`（独立 try/catch，不阻塞
  dashboard；`switchPage("home")` 经 loadDashboard 同样触发，不重复发请求）。
- `renderZcodeQuota(data)` 四分支：
  1. `data == null` → 三张 `.ub skeleton` 骨架；
  2. `!success` 且 error 含「未找到 ZCode Coding Plan 凭证」→ `.ub ub-hint` 天蓝引导框
     （文案 `zcodeQuotaGuide`）；
  3. `!success` 其他错误 → `.ub ub-error`（`zcodeQuotaFail` + error，经 escapeHtml）；
  4. 成功 → 标题行 + level 徽章（pro→Pro / max→Max / 其他首字母大写，空则隐藏徽章）+
     三张窗口卡（复用 `.ub` 进度条；MCP Monthly 显示 `已用 used_count/total_count 次`，
     total_count 为 0 仅显示 used_count；`reset_in_sec` 为 0 显示 "—"）。
- 隐藏规则：fetch 抛异常（404/网络错误）→ 容器保持 hidden，对无 ZCode 用户零打扰。
- `QUOTA_LABEL` 新增 `"MCP Monthly"` → `t("mcpMonthly")`。

### 1.2 统计页「ZCode 本地用量」区块（index.html + app.js）

- 插入点：`page-stats` 的 `.two-col` 之后新增 `<div class="card zcode-stats" id="zcode-stats" hidden>`：
  区块头（标题 + `zcodeCostHint` 估算口径）+ 引导文案 `#zcode-missing` + KPI 行（`#zcode-kpis`，
  kpi5 五列：请求数/总 Token/估算费用/平均输出速度/平均首字延迟，null → "—"）+
  渠道汇总表（8 列）+ 模型明细表（9 列）+ 7 日趋势图（`#zcode-trend-chart`，固定 daily7
  窗口，Token + 估算费用两条线，照现有 Chart.js 折线模式）。
- `loadZcodeSummary()`：拉 `/api/zcode/summary?range=<state.statsRange>`（与 loadDashboard
  的统计页 range 同源）；带 seq 守卫丢弃过期响应；fetch 异常 → 整块隐藏。
- 触发点：`switchPage("stats")` 与 `#stats-pills` range 切换处各追加一次调用（均为纯追加）。
- `db_found=false` → 仅显示 `zcodeStatsMissing` 引导文案，隐藏 KPI/表格/图。
- 渠道友好名 `zcodeProviderLabel`：provider_name 非空 → 原样；builtin:bigmodel/zai-coding-plan
  → "GLM Coding Plan"；含 "-start-plan" → "GLM Start"；其余 → provider_id 前 8 位 + "…"。
- 所有插值经 `escapeHtml`（provider_name/model_id 为用户自定义字符串）。

### 1.3 i18n（zh/en）

新增键：zcodeQuotaTitle / zcodeQuotaGuide / zcodeQuotaFail / mcpMonthly / zcodeStatsTitle /
zcodeStatsMissing / zcodeCostHint / zcodeChannel / zcodeModel / zcodeAvgTps / zcodeAvgTtft /
zcodeEstCost / zcodeHitRate / zcodeNoData / zcodeTimes（末项为 "次/times"，MCP 次数文案所需，
brief 词表外最小新增）。其余复用现有键（totalRequests/totalTokens/input/inclCache/output/
hitAmount/resetsIn/used 等）。

### 1.4 样式（style.css，亮/暗双主题）

新增：`.zcode-head/.zcode-title/.zcode-badge`（照 plan-badge）、`.ub.ub-hint`（天蓝信息框，
亮 #e0f2fb/#0891b2，暗 #123144/#67e8f9，照 src-badge 配色法）、`.zcode-cards`（三列网格，
引导/错误框通栏）、`.zcode-stats` 内距、`.kpi-row.kpi5` 五列（1200px 以下降 3 列）、
`.zcode-missing`（照 ov-quota-empty）、`.zcode-chart-empty`（图空态覆盖层）。

## 2. 现有函数改动点（全部为纯追加，不改既有行为）

| 位置 | 追加内容 |
|---|---|
| `loadDashboard()` try 末尾 | `loadZcodeQuota().catch(() => {})` |
| `switchPage()` | `if (page === "stats") loadZcodeSummary().catch(() => {})` |
| `#stats-pills` 点击事件 | `loadZcodeSummary()` |
| `applyLang()` 末尾 | 有缓存数据时重渲染两个 ZCode 区块（语言即时刷新，不重发请求） |
| `rerenderCharts()` stats 分支 | 主题切换时重绘 ZCode 趋势图 |
| window resize 处理器 stats 分支 | `safeResize(cZcodeTrend)` |

## 3. 验证

1. `node --check app/web/app.js`
2. `python -m pytest tests/ -q` 全量不回归
3. `python -m py_compile app/server.py app/main.py app/db.py app/zcode_api.py` +
   `git status` 确认仅 web 三件套被修改
