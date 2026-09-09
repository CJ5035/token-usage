# 用量统计页面按数据源分层折叠优化方案（方案 A）

**文档编号**: 20260907-usage-stats-layered-view  
**创建日期**: 2026-09-07  
**最近修订**: 2026-09-08（合并评审改进：占比条导航、默认展开第一名、手风琴单开、空源收纳区、估算值常驻徽标、记录页跳转带过滤参数）  
**方案类型**: 方案 A - 按数据源分层折叠  
**影响范围**: 前端 UI 重构（用量统计页 page-stats）  
**交互原型**: [20260908-stats-display-mockup.html](20260908-stats-display-mockup.html)

**⚠️ 改造目标明确**：
- 改造对象：**page-stats（用量统计页）重构 + page-records 小改（来源筛选预设入口）**
- 数据来源：远程数据（`usage_records` JOIN `accounts` 判定渠道）+ 本地数据（`zcode_usage`、`claudecode_usage`、`codex_usage` 表；DSH 无表，文件型仅今日窗口）
- 核心改动：按数据源（OpenCode、BAI、CommandCode、ZCode、Claude Code、Codex、DSH）分层折叠展示
- 汇总数据**复用现有 `db.report_channels()` 聚合**（与首页渠道明细同口径），不新建平行聚合逻辑

---

## 一、需求背景

### 1.1 当前问题

**现状说明**：
- page-stats 包含全局汇总、Token 构成、模型用量、用量趋势图表
- 底部独立展示本地数据（ZCode/DSH/Claude Code/Codex）
- 所有数据源的数据混在一起，无法快速区分各数据源占比

**存在问题**：

1. **信息扁平化**：全局汇总混合了所有数据源，无法回答"OpenCode 占多少？ZCode 占多少？"
2. **数据源割裂**：远程数据在顶部，本地数据在底部，缺乏统一对比视图
3. **多账号混乱**：OpenCode/CommandCode 可能有多个账号，但无法区分
4. **本地数据冗余**：即使某些本地数据源为空也占据空间

### 1.2 数据结构

渠道判定以代码为准（`db.py` `_CHANNEL_ORDER`）：远程渠道由 `usage_records LEFT JOIN accounts ON account_id` 的 `accounts.source` 得出；本地渠道各有镜像表；**DSH 无数据库表**。

| 渠道 channel | 类型 | 数据来源 | 费用口径 | 下钻维度 |
|---|---|---|---|---|
| `opencode` | 远程 | `usage_records` JOIN `accounts.source` | 实际费用 | 账号 → Key → 模型 |
| `bai` | 远程 | 同上（BAI 是独立渠道，非 OpenCode 子集） | 实际费用 | 账号 → Key → 模型 |
| `commandcode` | 远程 | 同上 | 实际费用 | 账号 → Key → 模型 |
| `zcode` | 本地 | `zcode_usage` 表 | 估算（estimated） | Provider → 模型 |
| `claudecode` | 本地 | `claudecode_usage` 表 | 估算（estimated） | Channel → 模型 |
| `codex` | 本地 | `codex_usage` 表 | **不可用**（cost=NULL, cost_available=false）；请求数按事件模式聚合（request_count_exact） | Provider → 模型 |
| `dsh` | 本地 | **无表**，`~/.dsh/sessions` 文件（`dsh_api`），**仅"今日"窗口**，requests/cost 均不可用 | 不可用 | 仅今日汇总，无下钻 |

**关键约束**：
- `usage_records` 表**没有 source 列**，远程渠道必须 JOIN `accounts` 取 `source` 字段分组
- DSH 仅在 `range=today` 时可进主列表（标注"仅今日"、无费用/请求数）；其余时间范围进收纳区
- Codex 费用不可用：不参与费用占比条，面板内显示"费用不可用"，排序按 Token

### 1.3 优化目标

- 按数据源分层折叠，一眼看出各数据源占比
- 远程数据展示账号 + Key 维度，本地数据展示 Provider/Channel 维度
- 统一远程和本地数据的展示方式
- 按需加载，减少初始渲染压力

---

## 二、方案设计

### 2.1 整体架构

```
第一层：全局汇总（所有数据源）
    ├─ 时间范围选择器（today / yesterday / 7d / 30d / all）
    ├─ 汇总卡片（总请求、总 Token、总费用、命中率）
    ├─ 数据源占比条（100% 堆叠条，Token/费用可切换，色块可点击 = 可视化 + 导航合一）
    └─ 全局图表（Token 构成、用量趋势，默认折叠）

第二层：数据源折叠面板（手风琴单开）
    ├─ OpenCode                   ← 排序第一名默认展开
    │   ├─ 汇总数据
    │   ├─ 账号分布
    │   ├─ Top Keys
    │   └─ 模型用量图表
    ├─ BAI
    ├─ CommandCode
    ├─ ZCode（"估算值"徽标）
    │   ├─ 汇总数据
    │   ├─ Provider 分布
    │   └─ 模型用量图表
    ├─ Claude Code（"估算值"徽标）
    ├─ Codex（"费用不可用"徽标，按 Token 排序）
    └─ DSH（仅 range=today 时出现，"仅今日"徽标，无费用/请求数）

第三层：无数据源收纳区
    └─ "无数据的数据源（N）"灰色虚线折叠区
        （当前范围无数据的渠道 + 非 today 范围的 DSH）
```

**关键交互决策**：
- **手风琴单开**：同时只展开一个数据源，展开新的自动收起旧的，避免多开导致页面重新变长
- **默认展开第一名**：首屏既有全局汇总又有重点数据源详情，不丢失"一眼看懂"的价值
- **占比条即导航**：点击占比条色块 = 展开对应面板并滚动到位，跨源对比靠占比条而非多开面板
- **占比条支持 Token/费用切换**（复用首页 `report-metric` 交互模式）：费用模式下 Codex/DSH 等费用不可用渠道不占色块，脚注说明"部分渠道费用不可用，未计入费用占比"
- **排序规则**：费用可用的渠道按费用降序；费用不可用渠道（Codex、DSH）按 Token 降序排在可用组之后
- **不做环形图**：首页（用量统计总览）已有"渠道占比环形图 + 渠道明细表"，统计页只做可点击占比条，避免重复

### 2.2 视觉设计

#### 首屏状态（默认：占比条 + 第一名展开，其余折叠）

```
┌───────────────────────────────────────────────────────┐
│ 用量统计    [今天] [昨天] [近7天] [近30天] [全部]     │
├───────────────────────────────────────────────────────┤
│ [总请求: 1,234] [总 Token: 456.7K] [总费用: $12.34] [命中率: 42.3%] │
├───────────────────────────────────────────────────────┤
│ 数据源占比（点击色块展开）        [Token|费用] ← 切换 │
│ [████████ OpenCode 45.2% ████|███ BAI 20.0% ██|██ CommandCode 12.1% ██|██ ZCode …] │
│ ● OpenCode $5.58 ● BAI $2.47 ● CommandCode $1.49 ● ZCode $1.89(估) ● Claude $0.91(估) │
│ ※ Codex、DSH 费用不可用，未计入费用占比              │
├───────────────────────────────────────────────────────┤
│ ▶ 📈 全局图表（Token 构成 · 用量趋势）        ← 默认折叠 │
├───────────────────────────────────────────────────────┤
│ 🔽 OpenCode                 [▓▓▓▓▓▓▓▓░░░░] 45.2%  $5.58 │  ← 排序第一名默认展开
│  ├─────────────────────────────────────────────────┤  │
│  │ 📊 558 请求 · 205.6K Token · 命中率 42%         │  │
│  │ 👥 账号分布:  账号 A ▓▓▓▓▓▓ 60% $3.35           │  │
│  │               账号 B ▓▓▓▓   40% $2.23           │  │
│  │ 🔑 Top Keys:  key-prod-001 ▓▓▓▓ 35% $1.95       │  │
│  │               key-dev-002  ▓▓▓  25% $1.40       │  │
│  │ 🤖 模型用量:  opus-5 ▓▓▓▓▓▓ 60%                 │  │
│  │ [查看详细记录 →]（跳转记录页并预设来源=OpenCode）│  │
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│ ▶ BAI                       [▓▓▓▓░░░░░░] 20.0%  $2.47 │
├───────────────────────────────────────────────────────┤
│ ▶ ZCode  [估算值]           [▓▓▓░░░░░░░] 15.3%  $1.89 │  ← 估算源常驻徽标
├───────────────────────────────────────────────────────┤
│ ▶ Codex  [费用不可用]       36.0K Token · 费用 —      │  ← 按 Token 排序
├───────────────────────────────────────────────────────┤
│ ▶ DSH  [仅今日] [费用不可用] 12.3K Token · 费用 —     │  ← 仅 range=today 出现
├┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┤
│ ▶ 无数据的数据源（N）              ← 灰色虚线收纳区   │
└───────────────────────────────────────────────────────┘
```

面板标题行内嵌迷你占比条（mini bar），折叠状态下也能扫读各源占比；徽标体系：`估算值`（zcode/claudecode）、`费用不可用`（codex/dsh）、`仅今日`（dsh）；占比条 Token/费用切换与首页 `report-metric` 交互一致。

### 2.3 交互逻辑

- **默认**：排序第一名的数据源自动展开，其余折叠（首屏 = 全局汇总 + 占比条 + 重点源详情）
- **手风琴单开**：点击标题行展开该数据源，同时自动收起其他数据源；再次点击当前展开项可收起
- **占比条联动**：点击占比条色块 = 展开对应数据源面板并平滑滚动到位（导航与可视化合一）
- **占比条口径切换**：Token / 费用两种口径（默认 Token，与首页 `report-metric` 一致）；费用口径下隐藏费用不可用渠道的色块
- **按需加载**：展开时才加载详细数据（账号分布、Top Keys、图表），详情缓存 30 秒
- **时间范围联动**：切换时间范围（today / yesterday / 7d / 30d / all），汇总卡、占比条、所有面板数据更新；非 today 范围时 DSH 自动移入收纳区
- **无数据源收纳**：当前范围无数据 / 未检测到的数据源不进入主列表，统一收纳到底部"无数据的数据源（N）"灰色虚线折叠区，保留"本产品还支持哪些源"的发现性
- **跳转记录页**：面板内"查看详细记录 →"调用现有切页逻辑（`data-page="records"`）并预设 `state.records.source = <channel>` 后触发加载。应用当前无 hash 路由机制，**不引入 `#records?source=` 式 URL 状态**；记录页来源筛选下拉的选项集合需包含全部渠道（含本地渠道）

---

## 三、数据接口设计

### 3.1 新增 API 端点

#### 3.1.1 数据源汇总接口

```
GET /api/stats/sources?range=7d
```

`range` 取值遵循现有白名单（`server.py` `_RANGE_WHITELIST`）：`today / yesterday / 7d / 30d / all`。

**实现方式（去重决策）**：本接口是 `db.report_channels(range_)` 的**薄封装**，不重写聚合 SQL——渠道行（tokens/input/output/cache_read/requests/cost/cost_available/estimated）直接来自现有函数，本接口只补充：占比计算、排序、DSH 今日行并入（复用 `_report_channels_response` 的并入逻辑）、`empty_sources` 组装。

**返回结构**：
```json
{
  "range": "7d",
  "totals": {
    "request_count": 1234,
    "total_tokens": 456700,
    "total_cost_usd": 12.34,
    "hit_rate": 42.3
  },
  "sources": [
    {
      "source_id": "opencode",
      "source_name": "OpenCode",
      "source_type": "remote",
      "request_count": 234,
      "request_count_exact": true,
      "total_tokens": 123400,
      "total_cost_usd": 5.58,
      "cost_available": true,
      "estimated": false,
      "pct_cost": 45.2,
      "pct_tokens": 27.0,
      "hit_rate": 42.3
    },
    {
      "source_id": "zcode",
      "source_name": "ZCode",
      "source_type": "local",
      "request_count": 67,
      "request_count_exact": true,
      "total_tokens": 45600,
      "total_cost_usd": 1.89,
      "cost_available": true,
      "estimated": true,
      "pct_cost": 15.3,
      "pct_tokens": 10.0,
      "hit_rate": 51.2
    },
    {
      "source_id": "codex",
      "source_name": "Codex",
      "source_type": "local",
      "request_count": 91,
      "request_count_exact": false,
      "total_tokens": 36000,
      "total_cost_usd": null,
      "cost_available": false,
      "estimated": false,
      "pct_cost": null,
      "pct_tokens": 7.9,
      "hit_rate": null
    }
  ],
  "empty_sources": [
    { "source_id": "dsh", "source_name": "DSH", "reason": "仅提供今日数据（range≠today）" }
  ]
}
```

**字段与口径说明**：
- `cost_available` / `estimated` / `request_count_exact`：沿用 `report_channels` 既有语义（Codex 费用 `null` 而非 0）
- `pct_cost`：仅对 `cost_available=true` 的渠道计算（分母 = 可用渠道费用总和），不可用渠道为 `null`
- `pct_tokens`：所有渠道按 Token 计算占比，作为费用不可用渠道的排序与占比条口径
- `hit_rate`：加权口径 `SUM(cache_read) / SUM(cache_read + input) × 100`；`totals.hit_rate` 同样加权，**不做简单平均**；DSH 仅 today 口径、Codex 无缓存字段时为 `null`
- `sources` 排序：`cost_available=true` 按费用降序在前，`cost_available=false` 按 Token 降序在后
- `empty_sources`：当前范围无数据的渠道，以及 `range≠today` 时的 DSH；`list_channel_summary()` 保留历史渠道的可见性

#### 3.1.2 数据源详情接口

```
GET /api/stats/sources/{source_id}/detail?range=7d
```

**返回结构（远程数据源）**：
```json
{
  "source_id": "opencode",
  "accounts": [
    {
      "account_id": 123,
      "account_name": "user_a@company.com",
      "request_count": 140,
      "total_cost_usd": 3.35,
      "percentage": 60.0
    }
  ],
  "top_keys": [
    {
      "key_id": "key-prod-001",
      "key_name": "生产环境",
      "request_count": 82,
      "total_cost_usd": 1.95,
      "percentage": 35.0
    }
  ],
  "models": [
    {
      "model": "opus-5",
      "request_count": 140,
      "percentage": 60.0
    }
  ]
}
```

**返回结构（本地数据源）**：
```json
{
  "source_id": "zcode",
  "providers": [
    {
      "provider_id": "builtin:bigmodel-coding-plan",
      "provider_name": "GLM Coding Plan",
      "request_count": 54,
      "total_cost_usd": 1.51,
      "percentage": 80.0
    }
  ],
  "models": [...]
}
```

---

## 四、实施步骤

### 4.1 后端实施（app/server.py + app/db.py）

**Step 1**: 汇总接口薄封装（app/server.py，复用 `db.report_channels`，不重写聚合 SQL）

```python
def _stats_sources_payload(range_param: str) -> dict:
    """GET /api/stats/sources 数据组装：复用 db.report_channels 渠道行，
    仅补充占比、排序、DSH 今日并入与 empty_sources。"""
    range_ = range_param if range_param in _RANGE_WHITELIST else "7d"

    # 1. 渠道行复用现有聚合（与首页渠道明细同口径）
    rows = db.report_channels(range_)
    if range_ == "today":
        rows = _merge_dsh_today_row(rows)   # 抽出 _report_channels_response 的 DSH 并入逻辑复用

    # 2. 占比：费用仅对 cost_available 渠道；Token 全渠道
    cost_pool = sum(r["cost"] or 0 for r in rows if r["cost_available"])
    tok_pool = sum(r["tokens"] or 0 for r in rows)
    sources = []
    for r in rows:
        sources.append({
            "source_id": r["channel"],
            "source_name": CHANNEL_NAMES[r["channel"]],
            "source_type": "remote" if r["channel"] in ("opencode", "bai", "commandcode") else "local",
            "request_count": r["requests"],
            "request_count_exact": r["request_count_exact"],
            "total_tokens": r["tokens"],
            "total_cost_usd": r["cost"],                 # codex/dsh 为 None
            "cost_available": r["cost_available"],
            "estimated": r["estimated"],
            "pct_cost": (r["cost"] / cost_pool * 100) if r["cost_available"] and cost_pool else None,
            "pct_tokens": (r["tokens"] / tok_pool * 100) if tok_pool else 0,
            "hit_rate": _weighted_hit_rate(r),           # cache_read/(cache_read+input)，无字段为 None
        })

    # 3. 排序：费用可用按费用降序在前，不可用按 Token 降序在后
    sources.sort(key=lambda s: (not s["cost_available"],
                                -(s["total_cost_usd"] or 0),
                                -(s["total_tokens"] or 0)))

    # 4. 收纳区：主列表未出现的渠道统一进入；DSH 在非 today 范围必入（无历史表）
    present = {s["source_id"] for s in sources}
    empty_sources = []
    for c in ALL_CHANNELS:          # 含 dsh 的全渠道清单
        if c in present:
            continue
        reason = "仅提供今日数据" if c == "dsh" and range_ != "today" else "所选范围无数据"
        empty_sources.append({"source_id": c, "source_name": CHANNEL_NAMES[c], "reason": reason})

    return {"range": range_, "sources": sources, "empty_sources": empty_sources,
            "totals": _stats_totals(sources)}            # hit_rate 加权，非简单平均
```

**Step 2**: HTTP 路由注册（app/server.py `_handle_api`）

```python
if route == "/api/stats/sources" and method == "GET":
    return _json(handler, _stats_sources_payload(query.get("range", ["7d"])[0]))

if route.startswith("/api/stats/sources/") and route.endswith("/detail") and method == "GET":
    source_id = route.split("/")[4]
    range_ = query.get("range", ["7d"])[0]
    if source_id in ("opencode", "bai", "commandcode"):
        return _json(handler, _remote_source_detail(source_id, range_))   # 账号分布 + Top Keys + 模型
    if source_id in ("zcode", "claudecode", "codex"):
        return _json(handler, _local_source_detail(source_id, range_))    # Provider/Channel + 模型
    if source_id == "dsh":
        return _json(handler, _dsh_today_detail())                        # 仅今日汇总，无下钻
    return _json(handler, {"error": "unknown source"}, status=404)
```

### 4.2 前端实施（app/web/app.js）

**Step 1**: 状态管理

```javascript
state.statsView = {
  range: "7d",           // today / yesterday / 7d / 30d / all（与 _RANGE_WHITELIST 一致）
  metric: "tokens",      // 占比条口径：tokens / cost（与首页 report-metric 一致）
  expandedSource: null,  // 手风琴单开：当前展开的数据源 id（null=全部收起）
  sourcesData: null,     // 缓存数据源汇总
  detailsCache: {},      // {source_id: detail_data}，30 秒 TTL
};
```

**Step 2**: 渲染函数

```javascript
async function loadSourcesSummary() {
  const data = await api(`/api/stats/sources?range=${state.statsView.range}`);
  state.statsView.sourcesData = data;
  renderSourcesSummary(data);
}

function renderSourcesSummary(data) {
  // 1. 渲染全局汇总
  $("global-totals").innerHTML = `
    <div class="kpi-row kpi4">
      <div class="card kpi c-blue"><div class="kpi-l">总请求</div><div class="kpi-v">${fmtInt(data.totals.request_count)}</div></div>
      <div class="card kpi c-violet"><div class="kpi-l">总 Token</div><div class="kpi-v">${fmtTokens(data.totals.total_tokens)}</div></div>
      <div class="card kpi c-amber"><div class="kpi-l">总费用</div><div class="kpi-v">${fmtMoney(data.totals.total_cost_usd)}</div></div>
      <div class="card kpi c-green"><div class="kpi-l">平均命中率</div><div class="kpi-v">${data.totals.avg_hit_rate.toFixed(1)}%</div></div>
    </div>
  `;

  // 2. 渲染占比条（可视化 + 导航合一；费用口径下跳过费用不可用渠道）
  const metric = state.statsView.metric;   // "tokens" | "cost"
  const barSources = data.sources.filter(s => metric === "tokens" || s.cost_available);
  $("share-bar").innerHTML = barSources.map(s => {
    const pct = metric === "tokens" ? s.pct_tokens : s.pct_cost;
    return `
    <div class="share-seg" style="flex:${pct};background:${sourceColor(s.source_id)}"
         title="${escapeHtml(s.source_name)} ${pct.toFixed(1)}%"
         onclick="expandSource('${s.source_id}', true)">${pct >= 6 ? pct.toFixed(0) + '%' : ''}</div>`;
  }).join("");
  $("share-note").hidden = metric !== "cost" || barSources.length === data.sources.length;
  // share-note 文案："部分渠道费用不可用，未计入费用占比"

  // 3. 渲染数据源面板（手风琴：仅 expandedSource 展开）
  const container = $("sources-container");
  container.innerHTML = data.sources.map(source => {
    const expanded = state.statsView.expandedSource === source.source_id;
    const icon = source.source_type === "remote" ? "☁️" : "💾";
    const badges = [
      source.estimated ? `<span class="badge" title="费用为按量价目估算，订阅套餐实际不按此扣费">估算值</span>` : "",
      source.cost_available ? "" : `<span class="badge badge-muted">费用不可用</span>`,
      source.source_id === "dsh" ? `<span class="badge badge-muted">仅今日</span>` : "",
    ].join("");
    const pct = metric === "tokens" ? source.pct_tokens : (source.pct_cost ?? source.pct_tokens);
    const stats = source.cost_available
      ? `${pct.toFixed(1)}% | ${fmtMoney(source.total_cost_usd)}`
      : `${fmtTokens(source.total_tokens)} | 费用 —`;
    return `
      <div class="source-panel ${expanded ? 'expanded' : ''}" id="src-${source.source_id}">
        <div class="source-header" onclick="expandSource('${source.source_id}')">
          <span class="source-icon">${icon}</span>
          <span class="source-name">${escapeHtml(source.source_name)}</span>${badges}
          <span class="src-mini-bar"><span style="width:${pct}%;background:${sourceColor(source.source_id)}"></span></span>
          <span class="source-stats">${stats}</span>
          <span class="source-toggle">${expanded ? '🔽' : '▶️'}</span>
        </div>
        <div class="source-body" id="source-body-${source.source_id}">
          ${expanded ? '<div class="loading">加载中...</div>' : ''}
        </div>
      </div>
    `;
  }).join("");

  // 4. 渲染无数据源收纳区
  $("empty-zone").hidden = !data.empty_sources.length;
  $("empty-zone-count").textContent = data.empty_sources.length;
  $("empty-zone-body").innerHTML = data.empty_sources.map(s =>
    `<span class="empty-src">💾 ${escapeHtml(s.source_name)} · ${escapeHtml(s.reason)}</span>`
  ).join("");

  // 5. 加载当前展开数据源的详情
  if (state.statsView.expandedSource) loadSourceDetail(state.statsView.expandedSource);
}

// 手风琴单开；fromShareBar=true 时滚动到位
function expandSource(sourceId, fromShareBar = false) {
  state.statsView.expandedSource =
    (state.statsView.expandedSource === sourceId && !fromShareBar) ? null : sourceId;
  renderSourcesSummary(state.statsView.sourcesData);
  if (state.statsView.expandedSource) {
    loadSourceDetail(sourceId);
    if (fromShareBar) $(`src-${sourceId}`).scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}

// 初始加载完成后：默认展开费用第一名
async function initSourcesView() {
  await loadSourcesSummary();
  if (state.statsView.sourcesData.sources.length && !state.statsView.expandedSource) {
    expandSource(state.statsView.sourcesData.sources[0].source_id);
  }
}

async function loadSourceDetail(sourceId) {
  if (state.statsView.detailsCache[sourceId]) {
    renderSourceDetail(sourceId, state.statsView.detailsCache[sourceId]);
    return;
  }
  
  const detail = await api(`/api/stats/sources/${sourceId}/detail?range=${state.statsView.range}`);
  state.statsView.detailsCache[sourceId] = detail;
  renderSourceDetail(sourceId, detail);
}

function renderSourceDetail(sourceId, detail) {
  const container = $(`source-body-${sourceId}`);
  
  if (detail.accounts) {
    // 远程数据源：显示账号 + Top Keys
    container.innerHTML = `
      <div class="source-summary">📊 ${fmtInt(detail.request_count)} 请求 · ${fmtTokens(detail.total_tokens)} Token</div>
      <div class="accounts-list">
        <strong>👥 账号分布:</strong>
        ${detail.accounts.map(acc => `<div>• ${escapeHtml(acc.account_name)} (${acc.percentage.toFixed(0)}%) ${fmtMoney(acc.total_cost_usd)}</div>`).join("")}
      </div>
      <div class="keys-list">
        <strong>🔑 Top Keys:</strong>
        ${detail.top_keys.map(key => `<div>• ${escapeHtml(key.key_name)} (${key.percentage.toFixed(0)}%) ${fmtMoney(key.total_cost_usd)}</div>`).join("")}
      </div>
      <div class="models-chart">[模型用量图表占位]</div>
      <a class="src-link" onclick="gotoRecords('${sourceId}')">查看详细记录 →</a>
    `;
  } else if (detail.providers) {
    // 本地数据源：显示 Provider
    container.innerHTML = `
      <div class="source-summary">📊 ${fmtInt(detail.request_count)} 请求 · ${fmtTokens(detail.total_tokens)} Token</div>
      <div class="providers-list">
        <strong>🔌 Provider 分布:</strong>
        ${detail.providers.map(p => `<div>• ${escapeHtml(p.provider_name || p.provider_id)} (${p.percentage.toFixed(0)}%) ${fmtMoney(p.total_cost_usd)}</div>`).join("")}
      </div>
      <div class="models-chart">[模型用量图表占位]</div>
      <a class="src-link" onclick="gotoRecords('${sourceId}')">查看详细记录 →</a>
    `;
  }
}

// 跳转记录页并预设来源筛选（复用现有切页逻辑，应用无 hash 路由，不引入 URL 状态）
function gotoRecords(sourceId) {
  switchPage("records");                 // 现有侧边栏切页函数（data-page 机制）
  state.records.source = sourceId;       // records 已有 source 过滤状态（默认 "all"）
  state.records.page = 1;
  syncRecordSourceSelect();              // 同步 #rec-source-filter 下拉选中态
  loadRecords();
}
```

### 4.3 CSS 样式（app/web/style.css）

```css
.source-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 12px;
  overflow: hidden;
}

.source-header {
  display: flex;
  align-items: center;
  padding: 16px;
  background: var(--bg2);
  cursor: pointer;
  transition: background 0.2s;
}

.source-header:hover {
  background: var(--bg3);
}

.source-name {
  flex: 1;
  font-weight: 600;
}

.source-stats {
  margin-right: 16px;
  color: var(--text2);
}

.source-body {
  display: none;
  padding: 16px;
  background: var(--bg1);
}

.source-panel.expanded .source-body {
  display: block;
}

/* 占比条（可视化 + 导航合一） */
.share-card {
  background: var(--bg1);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px;
  margin-bottom: 20px;
}
.share-bar { display: flex; height: 28px; border-radius: 6px; overflow: hidden; }
.share-seg {
  display: flex; align-items: center; justify-content: center;
  color: rgba(255,255,255,.92); font-size: 12px; font-weight: 600;
  cursor: pointer; min-width: 0; overflow: hidden; white-space: nowrap;
}
.share-seg:hover { filter: brightness(1.25); }

/* 面板标题行迷你占比条 */
.src-mini-bar {
  width: 120px; height: 6px; margin: 0 12px 0 auto;
  background: var(--bg3); border-radius: 3px; overflow: hidden;
}
.src-mini-bar span { display: block; height: 100%; border-radius: 3px; }

/* 估算值常驻徽标（本地数据源） */
.badge {
  font-size: 11px; padding: 1px 8px; border-radius: 10px; margin-left: 8px;
  background: rgba(232,163,61,.15); color: var(--amber);
  border: 1px solid rgba(232,163,61,.4);
}
/* 费用不可用 / 仅今日 徽标（codex、dsh） */
.badge-muted {
  background: var(--bg3); color: var(--text3); border-color: var(--border);
}

/* 无数据源收纳区（灰色虚线） */
.empty-zone .zone-head {
  display: flex; align-items: center; padding: 12px 16px;
  border: 1px dashed var(--border); border-radius: 10px;
  color: var(--text3); cursor: pointer;
}
.empty-src { display: inline-block; margin: 0 16px 8px 0; color: var(--text3); font-size: 13px; }
```

---

## 五、风险评估与应对

### 5.1 异构数据源整合风险

**风险**：远程/本地/文件型（DSH）三类数据源字段与口径不一致，难以统一展示

**应对**：
- 汇总层**复用 `db.report_channels` 既有契约**（tokens/requests/cost/cost_available/estimated/request_count_exact），不做第二套口径
- 费用语义三态：`cost_available=true`（实际费用）/ `estimated=true`（估算，常驻徽标）/ `cost_available=false`（费用不可用，codex/dsh，显示"费用 —"）
- 本地数据无账号维度时，详情接口返回空数组，前端不渲染账号区块
- DSH 无历史表：仅 `range=today` 进主列表（"仅今日"徽标），其余范围进收纳区，详情接口返回今日汇总且无下钻

### 5.2 性能风险

**风险**：数据源过多（6+ 个）且同时展开时，渲染和数据加载压力大

**应对**：
- 手风琴单开：同时最多展开 1 个数据源，从交互上根除多开压力
- 按需加载：展开时才请求详情接口
- 缓存机制：详情数据缓存 30 秒

### 5.3 本地数据估算值混淆

**风险**：本地数据费用是估算值，用户可能误认为实际扣费

**应对**：
- 后端返回 `cost_estimated: true`，前端在数据源名称旁显示**常驻"估算值"徽标**（非仅 Tooltip）
- Tooltip 补充说明："费用为按量价目估算，订阅套餐实际不按此扣费"
- 页面底部保留统一说明文案

---

## 六、测试验证计划

### 6.1 单元测试

- [ ] 后端：`_stats_sources_payload()` 与 `db.report_channels` 口径一致（同 range 下各渠道 tokens/requests 相等）
- [ ] 后端：远程渠道经 `accounts.source` 正确拆分为 opencode / bai / commandcode
- [ ] 后端：`range=today` 时 DSH 进主列表；`range=7d/30d/all` 时 DSH 进 `empty_sources` 且 reason 为"仅提供今日数据"
- [ ] 后端：Codex 行 `cost=null`、`cost_available=false`、`pct_cost=null`，排序落在费用可用组之后
- [ ] 后端：`pct_cost` 仅对费用可用渠道计算且总和 100%；`pct_tokens` 全渠道总和 100%
- [ ] 后端：`totals.hit_rate` 为加权口径（非简单平均）
- [ ] 后端：range 非法值回退 7d，白名单外不报错
- [ ] 前端：`expandSource()` 手风琴单开（展开新源自动收起旧源，再次点击可收起）
- [ ] 前端：初始加载默认展开排序第一名
- [ ] 前端：占比条色块点击 = 展开对应面板并滚动到位；费用口径下隐藏费用不可用渠道色块并显示脚注
- [ ] 前端：`gotoRecords()` 正确切页并预设来源筛选

### 6.2 集成测试

- [ ] 单数据源场景：正确显示，展开无报错
- [ ] 多数据源场景：按费用降序排列，占比正确
- [ ] 本地数据缺失场景：不显示或显示空态提示
- [ ] 时间范围切换：所有数据联动更新

### 6.3 UI 测试

- [ ] 折叠/展开动画流畅
- [ ] 无数据源（$0 / 未检测到）正确进入底部收纳区，主列表不显示
- [ ] 占比条在数据源占比极小（< 6%）时色块不显示数字但可点击
- [ ] 本地数据源"估算值"徽标常驻显示，Tooltip 正常
- [ ] 暗色主题：占比条、徽标、收纳区样式正确
- [ ] 移动端适配：数据源面板、占比条自适应

### 6.4 性能测试

- [ ] 6 个数据源折叠状态：初始渲染 < 500ms
- [ ] 展开单个数据源：< 300ms
- [ ] 切换时间范围：< 1s

---

## 七、上线计划

### 7.1 开发排期

| 阶段 | 任务 | 预计工时 |
|-----|------|---------|
| P1 | 后端：`_stats_sources_payload()` 薄封装（复用 `db.report_channels`，含占比/排序/empty_sources） | 3h |
| P2 | 后端：各数据源详情接口（远程账号/Top Keys，本地 Provider，DSH 今日） | 5h |
| P3 | 前端：占比条导航（Token/费用切换）+ 数据源列表渲染（手风琴） | 5h |
| P4 | 前端：展开详情逻辑 + 按需加载缓存 | 3h |
| P5 | 前端：账号/Key/Provider 展示 + 徽标体系（估算值/费用不可用/仅今日） | 3h |
| P6 | 前端：无数据源收纳区 + 记录页来源筛选预设跳转 | 1h |
| P7 | CSS 样式 + 暗色主题 | 2h |
| P8 | 国际化文案 | 1h |
| P9 | 集成测试 + Bug 修复 | 3h |
| **总计** | | **26h** |

### 7.2 灰度方案

1. **配置开关**：`settings.enable_sources_view: boolean`（默认 false）
2. **设置页控制**：用户可启用"数据源分层视图（实验性）"
3. **渐进上线**：Week 1 内测 → Week 2 灰度 20% → Week 3 全量

### 7.3 回滚预案

如上线后发现问题：
1. 配置开关降级：`enable_sources_view: false`
2. 保留旧版 page-stats 不变，新功能可快速移除

---

## 八、FAQ

**Q1：为什么改造 page-stats 而不是 page-records？**  
A：用户截图显示的是 page-stats，且该页面包含所有数据源（远程 + 本地），是信息混乱的核心区域。

**Q2：本地数据无账号/Key 维度怎么办？**  
A：展示 Provider/Channel 维度（如 ZCode 的 GLM Coding Plan、Claude Code 的 Anthropic）。DSH 是特例：无历史表、仅今日窗口且费用/请求数不可用，仅 `range=today` 时进主列表，其余时间进收纳区。

**Q3：数据源过多会不会页面很长？**  
A：手风琴单开，同时只展开一个面板；无数据的数据源统一收纳到底部灰色虚线区，主列表始终保持紧凑。

**Q4：会影响现有功能吗？**  
A：不会。新增独立的接口和组件，通过配置开关灰度上线，可快速回滚。

**Q5：工时 26h 是否合理？**  
A：包含后端 8h、前端 12h、测试 3h、文案 1h、样式 2h。汇总层复用 `db.report_channels` 省掉了平行聚合 SQL 的开发与口径对齐成本。

**Q8：为什么不新建独立的聚合查询，而是复用 `db.report_channels`？**  
A：该函数已实现跨渠道聚合（远程经 `accounts.source` JOIN 判定渠道、本地三表分派、Codex 费用 NULL 语义、当前范围无数据不出行），与首页渠道明细同口径。新建平行逻辑等于维护两套永远需要对齐的 SQL，违反去重原则。本方案只做薄封装：占比、排序、DSH 今日并入、empty_sources。

**Q6：占比条与首页（用量统计总览）的渠道占比环形图重复吗？**  
A：信息上部分重叠，但职责不同——首页环形图是纯展示，统计页占比条是"导航 + 可视化"合一（点击色块直接展开对应数据源面板）。为彻底去重，统计页**不再做环形图**，全局图表（Token 构成、用量趋势）默认折叠收纳；"看占比"的静态视图统一留给首页。

**Q7：为什么手风琴单开，而不是文档初版的"允许多开对比"？**  
A：多开会让页面重新变长、展开时跳动，违背本方案"解决页面太长"的初衷。跨源对比的需求由占比条（一眼看清各源占比）和汇总卡承担，不需要靠多开面板实现。

---

**文档状态**: 待审核  
**审核人**: （待填写）  
**审核日期**: （待填写）  
**批准实施**: ☐ 是  ☐ 否（原因：_____）
