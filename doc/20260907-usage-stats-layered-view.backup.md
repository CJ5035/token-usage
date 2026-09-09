# 用量统计页面按数据源分层折叠优化方案

**文档编号**: 20260907-usage-stats-layered-view  
**创建日期**: 2026-09-07  
**方案类型**: 方案 A - 按数据源分层折叠  
**影响范围**: 前端 UI 重构（用量统计页 page-stats）

**⚠️ 改造目标明确**：
- 改造对象：**page-stats（用量统计页）**
- 数据来源：远程数据（`usage_records` 表）+ 本地数据（`zcode_usage`、`claudecode_usage`、`dsh_*`、`codex_*` 表）
- 核心改动：按数据源（OpenCode、CommandCode、ZCode、Claude Code、DSH、Codex）分层折叠展示

---

## 一、需求背景

### 1.1 当前问题

**现状说明**：
- 当前"用量统计"页面（page-stats）包含：
  - 全局汇总卡片（总请求、总 Token、总费用等）
  - Token 构成
  - 模型用量图表
  - 用量趋势图表
  - 本地数据区块（ZCode、DSH、Claude Code、Codex）独立展示

**存在问题**：

1. **信息扁平化**
   - 全局汇总混合了所有数据源（OpenCode + CommandCode + ZCode + DSH + Claude Code + Codex）
   - 无法快速回答："OpenCode 占总费用的多少？ZCode 占多少？"
   - 用户需要手动计算各数据源的占比

2. **数据源割裂**
   - 远程数据（OpenCode/CommandCode）在顶部显示汇总图表
   - 本地数据（ZCode/DSH/Claude Code/Codex）在底部独立区块显示
   - 两者没有统一的对比视图

3. **多账号场景混乱**
   - OpenCode/CommandCode 可能有多个账号，但汇总数据混在一起
   - 无法快速筛选"只看账号 A 的数据"
   - 账号间的用量对比困难

4. **本地数据展示冗余**
   - ZCode/DSH/Claude Code/Codex 各自独立展示，即使某些数据源为空也占据空间
   - 用户需要滚动很长才能看到所有数据

### 1.2 数据结构澄清

**数据源与字段对应**：

| 数据源 | 表 | account_id | key_id | provider_id/channel |
|-------|-----|-----------|--------|-------------------|
| OpenCode | `usage_records` | ✅ | ✅ | ❌ |
| CommandCode | `usage_records` | ✅ | ✅ | ❌ |
| ZCode | `zcode_usage` | ❌ | ❌ | ✅ (provider_id) |
| Claude Code | `claudecode_usage` | ❌ | ❌ | ✅ (channel) |
| DSH | `dsh_*` | ❌ | ❌ | ✅ (channel) |
| Codex | `codex_*` | ❌ | ❌ | ✅ (provider_id) |

**关键特征**：
- **远程数据**（OpenCode/CommandCode）：有账号维度、有 Key 维度
- **本地数据**（ZCode/DSH/Claude Code/Codex）：无账号维度、无 Key 维度，但有 provider/channel 维度

### 1.3 优化目标

- **数据源层级清晰**：按数据源（OpenCode/CommandCode/ZCode/...）分组，折叠/展开控制
- **快速占比对比**：一眼看出各数据源的费用占比和用量占比
- **统一视图**：远程数据和本地数据统一展示，不再割裂
- **多维度细分**：
  - 远程数据（OpenCode/CommandCode）：展示账号分布、Top Keys
  - 本地数据（ZCode/DSH/...）：展示 Provider/Channel 分布
- **渐进式改造**：保留现有全局图表（Token 构成、用量趋势），作为全局视图

---

## 二、方案设计

### 2.1 整体架构

采用**按数据源分层折叠式**布局，重组 page-stats 页面：

```
第一层：全局汇总（跨所有数据源）
    ├─ 时间范围选择器（今天/近7天/近30天/全部）
    ├─ 汇总卡片（总请求、总 Token、总费用、平均命中率）
    └─ 全局图表（可选保留）
        ├─ Token 构成
        └─ 用量趋势

第二层：数据源折叠面板（按费用降序）
    ├─ 远程数据源
    │   ├─ OpenCode（BAI）
    │   │   ├─ 数据源汇总（请求数、Token、费用、占比）
    │   │   ├─ 账号分布（账号 A 60% | 账号 B 40%）
    │   │   ├─ Top Keys（前 3-5 个 Key）
    │   │   └─ 模型用量图表（该数据源独立）
    │   │
    │   └─ CommandCode
    │       └─ 同上结构
    │
    └─ 本地数据源
        ├─ ZCode
        │   ├─ 数据源汇总
        │   ├─ Provider 分布（GLM Coding Plan 80% | GLM Start 20%）
        │   └─ 模型用量图表
        │
        ├─ Claude Code
        ├─ DSH
        └─ Codex

第三层：明细查看（可选，点击"查看详情"后跳转）
    └─ 跳转到 page-records 或弹出明细表格
```

**关键改动**：
- 按**数据源**（OpenCode、CommandCode、ZCode...）分组，不是按产品或 Key
- 每个数据源可折叠/展开，默认折叠
- 远程数据源展示账号 + Key 维度，本地数据源展示 Provider/Channel 维度
- 保留全局汇总和图表，作为"全部数据源"的概览

### 2.2 视觉设计

#### 2.2.1 全局汇总区（顶部，始终可见）

```
┌───────────────────────────────────────────────────────┐
│  用量统计                                             │
│  [今天] [近7天] [近30天] [全部]  ← 时间范围选择      │
├───────────────────────────────────────────────────────┤
│  📊 全局汇总（所有数据源）                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐│
│  │总请求数  │ │总 TOKEN  │ │总费用    │ │平均命中率││
│  │ 1,234    │ │ 456.7K   │ │ $12.34   │ │  42.3%   ││
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘│
├───────────────────────────────────────────────────────┤
│  📊 Token 构成（可选，点击折叠/展开）                │
│  ┌─────────────────────────────────────────────────┐ │
│  │ [输入] [输出] [推理] [缓存读] 占比环形图         │ │
│  └─────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────┘
```

#### 2.2.2 数据源折叠面板（中部，可展开/收起）

```
┌───────────────────────────────────────────────────────┐
│ 🔽 OpenCode（BAI）              45.2%  |  $5.58       │  ← 点击折叠/展开
│  ├─────────────────────────────────────────────────┤  │
│  │ 📊 汇总: 234 请求 · 123.4K Token · 命中率 42%   │  │
│  │                                                  │  │
│  │ 👥 账号分布:                                     │  │
│  │   • 账号 A (user_a@company.com)  60% | $3.35   │  │
│  │   • 账号 B (user_b@company.com)  40% | $2.23   │  │
│  │                                                  │  │
│  │ 🔑 Top Keys:                                     │  │
│  │   • key-prod-001 (生产环境)      35% | $1.95   │  │
│  │   • key-dev-002 (开发环境)       25% | $1.40   │  │
│  │   • 其他 (5 个 Key)              40% | $2.23   │  │
│  │                                                  │  │
│  │ 📈 模型用量（该数据源）                         │  │
│  │ [opus-5: 60% | sonnet-5: 30% | haiku: 10%]     │  │
│  │                                                  │  │
│  │ [查看详细记录 →]                                │  │  ← 跳转到 page-records
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│ 🔽 CommandCode                      32.1%  |  $3.96   │
│  ├─────────────────────────────────────────────────┤  │
│  │ 📊 汇总: 156 请求 · 89.2K Token · 成功率 98.7%  │  │
│  │ 👥 账号: 账号 C (user_c@company.com)  100%      │  │
│  │ [查看详细记录 →]                                │  │
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│ 🔽 ZCode（本地）                    15.3%  |  $1.89   │
│  ├─────────────────────────────────────────────────┤  │
│  │ 📊 汇总: 67 请求 · 45.6K Token · 命中率 51%     │  │
│  │                                                  │  │
│  │ 🔌 Provider 分布:                                │  │
│  │   • GLM Coding Plan               80% | $1.51   │  │
│  │   • GLM Start                     20% | $0.38   │  │
│  │                                                  │  │
│  │ 📈 模型用量（该数据源）                         │  │
│  │ [glm-4: 70% | glm-3-turbo: 30%]                │  │
│  │                                                  │  │
│  │ 💡 费用为估算值（订阅套餐不按此扣费）           │  │
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│ 🔽 Claude Code（本地）               7.4%  |  $0.91   │
│ 🔽 DSH（本地）                       0%    |  $0.00   │
│ 🔽 Codex（本地）                     0%    |  $0.00   │
└───────────────────────────────────────────────────────┘
```

**说明**：
- 数据源按费用降序排列（费用高的在上）
- 默认状态：所有数据源折叠，仅显示标题行（数据源名称 + 占比 + 费用）
- 点击标题行：展开/收起该数据源
- 展开后显示：汇总数据、维度分布（账号/Provider）、Top Keys（仅远程）、模型用量
- 费用为 $0 的数据源可自动隐藏（可选）

### 2.3 交互逻辑

#### 2.3.1 状态管理

```javascript
state.statsView = {
  range: "d7",                    // 时间范围：today / d7 / d30 / all
  expandedSources: [],            // 已展开的数据源：["opencode", "zcode"]
  globalChartsCollapsed: false,   // 全局图表是否折叠
};
```

#### 2.3.2 展开/收起行为

- **默认状态**：所有数据源折叠
- **点击数据源标题**：展开该数据源，加载详细数据（账号分布、Top Keys、模型图表）
- **再次点击**：收起该数据源
- **多开支持**：允许同时展开多个数据源

#### 2.3.3 数据加载策略

- **初始加载**：只加载全局汇总 + 各数据源的标题行数据（请求数、Token、费用、占比）
- **按需加载**：点击展开某个数据源时，才加载该数据源的详细数据（账号分布、Top Keys、模型图表）
- **性能优化**：展开后的数据缓存 30 秒，再次展开时直接使用缓存

#### 2.3.4 时间范围联动

- **全局时间选择器**（今天/近7天/近30天/全部）影响：
  - 全局汇总卡片
  - 所有数据源的汇总数据
  - 所有已展开数据源的详细数据（账号分布、模型图表等）

### 2.2 视觉设计

#### 2.2.1 全局汇总区（顶部，始终可见）

```
┌───────────────────────────────────────────────────────┐
│  使用记录                                             │
│  ┌─────────────────────────────────────────────────┐ │
│  │ [今天] [近7天] [近30天] [全部]  账号: [全部▼]  │ │  ← 时间范围 + 账号筛选
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐│
│  │总请求数  │ │总 TOKEN  │ │总费用    │ │平均命中率││
│  │ 1,234    │ │ 456.7K   │ │ $12.34   │ │  42.3%   ││
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘│
└───────────────────────────────────────────────────────┘
```

#### 2.2.2 Key 折叠面板（按费用降序）

```
┌───────────────────────────────────────────────────────┐
│ 🔽 key-prod-001 (生产环境)          45.2%  |  $5.58  │  ← 折叠控制
│  ├─────────────────────────────────────────────────┤  │
│  │ 📊 140 请求 · 74.1K Token · 命中率 42%          │  │
│  │ 📧 归属: 账号 A (user_a@company.com)            │  │
│  │ 🔑 Key ID: sk-proj-abc...xyz (完整 ID)          │  │  ← Tooltip 显示
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│ 🔽 key-dev-002 (开发环境)            32.1%  |  $3.96  │
│  ├─────────────────────────────────────────────────┤  │
│  │ 📊 94 请求 · 49.3K Token · 命中率 38%           │  │
│  │ 📧 归属: 账号 A (user_a@company.com)            │  │
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│ 🔽 key-test-003 (测试环境)            15.3%  |  $1.89  │
│  ├─────────────────────────────────────────────────┤  │
│  │ 📊 67 请求 · 45.6K Token · 命中率 51%           │  │
│  │ 📧 归属: 账号 B (user_b@company.com)            │  │
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│ 🔽 未归属 Key                         7.4%   |  $0.91  │  ← key_id 为空
│  ├─────────────────────────────────────────────────┤  │
│  │ 💡 无 Key 信息的历史记录                         │  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘
```

#### 2.2.3 明细表格（点击 Key 后展开）

```
┌───────────────────────────────────────────────────────┐
│ 🔑 key-prod-001 (生产环境) 的使用记录                 │
│ ← 返回 Key 列表              模型: [全部▼]  [刷新]   │
├───────────────────────────────────────────────────────┤
│ 时间      模型      输入    输出   推理  缓存读  费用  │
│ ──────────────────────────────────────────────────── │
│ 14:23:45  opus-5  12.3K   4.5K   2.1K  8.2K   $0.12 │
│ 14:20:12  sonnet  8.9K    3.2K   0     5.1K   $0.05 │
│ 13:45:33  opus-5  15.6K   5.8K   3.2K  10.3K  $0.18 │
│ ...                                                   │
├───────────────────────────────────────────────────────┤
│ 共 140 条  [<上一页]  第 1/14 页  [下一页>]           │
└───────────────────────────────────────────────────────┘
```

### 2.3 交互逻辑

#### 2.3.1 状态管理

```javascript
state.recordsView = {
  range: "today",              // 时间范围：today / d7 / d30 / all
  accountFilter: null,         // 账号筛选：null=全部 / 账号ID
  expandedKeys: [],           // 已展开的 Key ID 列表：["key-001", "key-002"]
  selectedKey: null,          // 当前选中的 Key：{ keyId: "key-001", keyName: "生产环境" }
  detailPage: 1,              // 明细表格当前页
  detailModel: null,          // 明细表格模型筛选
};
```

#### 2.3.2 展开/收起行为

- **默认状态**：所有 Key 折叠，仅显示 Key 汇总行（按费用降序）
- **点击 Key 标题**：展开该 Key，显示汇总信息（请求数、Token、命中率、归属账号）
- **再次点击**：收起该 Key
- **多开支持**：允许同时展开多个 Key（expandedKeys 数组）

#### 2.3.3 明细查看行为

- **点击"查看明细"按钮**（展开后的 Key 卡片内）：进入该 Key 的明细视图
- **面包屑导航**：`使用记录 > key-prod-001 (生产环境)`，点击可返回上级
- **URL 状态同步**：`#records?key=key-001&page=2`，支持刷新保持状态

#### 2.3.4 筛选联动

- **账号筛选器**：选择"账号 A"后
  - 全局汇总卡片只统计账号 A 的数据
  - Key 列表只显示归属账号 A 的 Key
  - 未归属 Key 的记录仍然显示（无法判断归属）
  
- **时间范围选择器**：切换后
  - 全局汇总、Key 汇总、明细表格全部联动更新

---

## 三、数据接口设计

### 3.1 新增 API 端点

#### 3.1.1 Key 汇总接口

```
GET /api/usage/keys?range=today&account_id=123
```

**Query 参数**：
- `range`: 时间范围（today / d7 / d30 / all）
- `account_id`: 账号筛选（可选，不传则返回所有账号的 Key）

**返回结构**：
```json
{
  "range": "today",
  "account_filter": 123,
  "totals": {
    "request_count": 1234,
    "total_tokens": 456700,
    "total_cost_usd": 12.34,
    "avg_hit_rate": 42.3
  },
  "keys": [
    {
      "key_id": "key-prod-001",
      "key_name": "生产环境",
      "account_id": 123,
      "account_name": "user_a@company.com",
      "request_count": 140,
      "total_input_tokens": 50000,
      "total_output_tokens": 20000,
      "total_reasoning_tokens": 4100,
      "total_cache_read_tokens": 8200,
      "total_tokens": 74100,
      "total_cost_usd": 5.58,
      "percentage": 45.2,
      "hit_rate": 42.3,
      "first_used_at": "2026-09-07T06:23:45Z",
      "last_used_at": "2026-09-07T14:23:45Z"
    },
    {
      "key_id": "",
      "key_name": "未归属",
      "account_id": null,
      "account_name": null,
      "request_count": 67,
      "total_tokens": 45600,
      "total_cost_usd": 0.91,
      "percentage": 7.4,
      "hit_rate": null
    }
  ]
}
```

#### 3.1.2 Key 明细接口（增强现有 `/api/usage/records`）

增强现有接口，支持按 Key 筛选：

```
GET /api/usage/records?key_id=key-prod-001&page=1&page_size=10&model=opus-5
```

**新增参数**：
- `key_id`: Key ID 筛选（可选，支持空字符串查询未归属记录）
- 保留现有的 `account_id`、`model` 参数

**返回结构**（保持现有格式）：
```json
{
  "records": [...],
  "total": 140,
  "models": ["opus-5", "sonnet-5", ...]
}
```

### 3.2 数据源映射

#### 3.2.1 远程数据（OpenCode/CommandCode）

**数据来源**：
- `usage_records` 表：按 `key_id` 分组聚合
- `accounts` 表：关联账号信息
- `settings.payload.key_names`：映射 Key 显示名

**SQL 示例**（Key 汇总）：
```sql
SELECT 
  key_id,
  account_id,
  COUNT(*) as request_count,
  SUM(input_tokens + output_tokens + reasoning_tokens + cache_read_tokens) as total_tokens,
  SUM(cost_usd) as total_cost_usd,
  AVG(CASE WHEN (cache_read_tokens + input_tokens) > 0 
      THEN cache_read_tokens * 100.0 / (cache_read_tokens + input_tokens) 
      ELSE 0 END) as hit_rate,
  MIN(created_at) as first_used_at,
  MAX(created_at) as last_used_at
FROM usage_records
WHERE account_id = ? AND created_at >= ?
GROUP BY key_id, account_id
ORDER BY total_cost_usd DESC
```

#### 3.2.2 本地数据（暂不纳入 Key 维度）

**处理方式**：
- ZCode/Claude Code/DSH/Codex 数据**不在本次改造范围内**
- 这些本地数据无 `key_id` 字段，无法按 Key 分组
- 保留现有的独立展示逻辑（统计页独立区块）

**未来扩展**（可选）：
- 在 Key 列表末尾增加"本地数据"特殊条目
- 点击展开后显示本地数据的汇总（不按 Key 分组）

---

## 四、实施步骤

### 4.1 后端实施（app/server.py + app/db.py）

**Step 1**: 数据库层新增查询函数（app/db.py）

```python
def get_keys_summary(range_key: str, account_id: Optional[int] = None) -> dict:
    """
    按 Key 分组聚合用量，支持账号筛选
    Args:
        range_key: 时间范围 (today/d7/d30/all)
        account_id: 账号筛选（None=全部账号）
    Returns:
        {"totals": {...}, "keys": [{key_id, key_name, account_id, stats...}, ...]}
    """
    conn = get_db()
    key_names = get_key_names()  # 从 settings 读取 key_id -> 显示名映射
    
    # 1. 构建 WHERE 子句
    where_clause, params = _range_where(range_key)
    if account_id is not None:
        where_clause += " AND account_id = ?"
        params.append(account_id)
    
    # 2. 按 key_id 分组聚合
    cur = conn.cursor()
    cur.execute(f"""
        SELECT 
            key_id,
            account_id,
            COUNT(*) as request_count,
            SUM(input_tokens) as total_input_tokens,
            SUM(output_tokens) as total_output_tokens,
            SUM(reasoning_tokens) as total_reasoning_tokens,
            SUM(cache_read_tokens) as total_cache_read_tokens,
            SUM(input_tokens + output_tokens + reasoning_tokens + cache_read_tokens) as total_tokens,
            SUM(cost_usd) as total_cost_usd,
            AVG(CASE WHEN (cache_read_tokens + input_tokens) > 0 
                THEN cache_read_tokens * 100.0 / (cache_read_tokens + input_tokens) 
                ELSE 0 END) as hit_rate,
            MIN(created_at) as first_used_at,
            MAX(created_at) as last_used_at
        FROM usage_records
        WHERE {where_clause}
        GROUP BY key_id, account_id
        ORDER BY total_cost_usd DESC
    """, params)
    
    keys = []
    total_cost = 0
    for row in cur.fetchall():
        key_id = row["key_id"] or ""
        key_name = key_names.get(key_id, "未归属" if not key_id else key_id)
        cost = row["total_cost_usd"] or 0
        total_cost += cost
        
        # 查询账号名称
        account_name = None
        if row["account_id"]:
            acc_cur = conn.cursor()
            acc_cur.execute("SELECT name FROM accounts WHERE id = ?", (row["account_id"],))
            acc_row = acc_cur.fetchone()
            account_name = acc_row["name"] if acc_row else None
        
        keys.append({
            "key_id": key_id,
            "key_name": key_name,
            "account_id": row["account_id"],
            "account_name": account_name,
            "request_count": row["request_count"],
            "total_input_tokens": row["total_input_tokens"],
            "total_output_tokens": row["total_output_tokens"],
            "total_reasoning_tokens": row["total_reasoning_tokens"],
            "total_cache_read_tokens": row["total_cache_read_tokens"],
            "total_tokens": row["total_tokens"],
            "total_cost_usd": cost,
            "hit_rate": row["hit_rate"],
            "first_used_at": row["first_used_at"],
            "last_used_at": row["last_used_at"],
        })
    
    # 3. 计算占比
    for key in keys:
        key["percentage"] = (key["total_cost_usd"] / total_cost * 100) if total_cost > 0 else 0
    
    # 4. 计算全局汇总
    totals = {
        "request_count": sum(k["request_count"] for k in keys),
        "total_tokens": sum(k["total_tokens"] for k in keys),
        "total_cost_usd": total_cost,
        "avg_hit_rate": sum(k["hit_rate"] or 0 for k in keys) / len(keys) if keys else 0,
    }
    
    return {"totals": totals, "keys": keys}
```

**Step 2**: HTTP 接口层（app/server.py）

```python
def _handle_usage_keys(params):
    """
    GET /api/usage/keys?range=today&account_id=123
    返回按 Key 分组的汇总数据
    """
    range_key = params.get("range", ["today"])[0]
    account_id_str = params.get("account_id", [None])[0]
    account_id = int(account_id_str) if account_id_str else None
    
    data = get_keys_summary(range_key, account_id)
    data["range"] = range_key
    data["account_filter"] = account_id
    
    return data

# 在 _handle_api 中注册路由
if path == "/api/usage/keys":
    return _handle_usage_keys(params)
```

**Step 3**: 增强现有明细接口（app/server.py）

```python
def _handle_usage_records(params):
    """
    增强现有接口，支持按 key_id 筛选
    GET /api/usage/records?key_id=key-001&page=1&page_size=10
    """
    # ... 现有逻辑 ...
    
    # 新增 key_id 筛选
    key_id = params.get("key_id", [None])[0]
    if key_id is not None:
        # 注意：key_id 可能为空字符串（查询未归属记录）
        where_parts.append("key_id = ?" if key_id else "(key_id IS NULL OR key_id = '')")
        if key_id:
            query_params.append(key_id)
    
    # ... 后续逻辑保持不变 ...
```

### 4.2 前端实施（app/web/app.js + index.html）

**Step 1**: 状态管理（app.js）

```javascript
// 在 state 对象中新增（保留现有 state.records）
state.keysView = {
  range: "today",
  accountFilter: null,     // null=全部 / 账号ID
  expandedKeys: [],        // ["key-001", "key-002"]
  selectedKey: null,       // { keyId: "key-001", keyName: "生产环境" }
  detailPage: 1,
  detailModel: null,
};
```

**Step 2**: 渲染函数（app.js）

```javascript
async function loadKeysView() {
  const params = new URLSearchParams({ range: state.keysView.range });
  if (state.keysView.accountFilter) {
    params.set("account_id", state.keysView.accountFilter);
  }
  const data = await api(`/api/usage/keys?${params}`);
  renderKeysView(data);
}

function renderKeysView(data) {
  // 1. 渲染全局汇总卡片
  const totals = data.totals;
  $("keys-totals").innerHTML = `
    <div class="card kpi c-blue">
      <div class="kpi-l">${t("totalRequests")}</div>
      <div class="kpi-v">${fmtInt(totals.request_count)}</div>
    </div>
    <div class="card kpi c-violet">
      <div class="kpi-l">${t("totalTokens")}</div>
      <div class="kpi-v">${fmtTokens(totals.total_tokens)}</div>
    </div>
    <div class="card kpi c-amber">
      <div class="kpi-l">${t("totalCost")}</div>
      <div class="kpi-v">${fmtMoney(totals.total_cost_usd)}</div>
    </div>
    <div class="card kpi c-green">
      <div class="kpi-l">${t("hitRate")}</div>
      <div class="kpi-v">${totals.avg_hit_rate.toFixed(1)}%</div>
    </div>
  `;
  
  // 2. 渲染 Key 折叠面板
  const container = $("keys-container");
  container.innerHTML = data.keys.map(key => {
    const expanded = state.keysView.expandedKeys.includes(key.key_id);
    return `
      <div class="key-panel ${expanded ? 'expanded' : ''}">
        <div class="key-header" onclick="toggleKey('${escapeAttr(key.key_id)}')">
          <span class="key-icon">🔑</span>
          <span class="key-name">${escapeHtml(key.key_name)}</span>
          <span class="key-stats">${key.percentage.toFixed(1)}% | ${fmtMoney(key.total_cost_usd)}</span>
          <span class="key-toggle">${expanded ? '🔽' : '▶️'}</span>
        </div>
        <div class="key-body">
          <div class="key-summary">
            📊 ${fmtInt(key.request_count)} 请求 · ${fmtTokens(key.total_tokens)} Token · 命中率 ${(key.hit_rate || 0).toFixed(1)}%
          </div>
          ${key.account_name ? `<div class="key-account">📧 归属: ${escapeHtml(key.account_name)}</div>` : ''}
          ${key.key_id ? `<div class="key-id" title="${escapeHtml(key.key_id)}">🔑 Key ID: ${escapeHtml(key.key_id.slice(0, 20))}...</div>` : ''}
          <button class="btn btn-sm" onclick="selectKey('${escapeAttr(key.key_id)}', '${escapeAttr(key.key_name)}')">
            查看明细
          </button>
        </div>
      </div>
    `;
  }).join("");
}

function toggleKey(keyId) {
  const idx = state.keysView.expandedKeys.indexOf(keyId);
  if (idx >= 0) {
    state.keysView.expandedKeys.splice(idx, 1);  // 收起
  } else {
    state.keysView.expandedKeys.push(keyId);    // 展开
  }
  loadKeysView();  // 重新渲染
}

function selectKey(keyId, keyName) {
  state.keysView.selectedKey = { keyId, keyName };
  state.keysView.detailPage = 1;
  loadKeyRecords(keyId);
  // 隐藏 Key 列表，显示明细视图
  $("keys-list-view").hidden = true;
  $("key-detail-view").hidden = false;
}

async function loadKeyRecords(keyId) {
  const params = new URLSearchParams({
    key_id: keyId,
    page: state.keysView.detailPage,
    page_size: 10,
  });
  if (state.keysView.detailModel) {
    params.set("model", state.keysView.detailModel);
  }
  const data = await api(`/api/usage/records?${params}`);
  renderKeyRecords(data);
}

function renderKeyRecords(data) {
  const key = state.keysView.selectedKey;
  $("key-detail-title").textContent = `🔑 ${key.keyName} 的使用记录`;
  
  // 渲染表格（复用现有 loadRecords 的表格渲染逻辑）
  const body = $("key-records-body");
  if (!data.records.length) {
    body.innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text3);padding:20px">${t("noData")}</td></tr>`;
  } else {
    body.innerHTML = data.records.map(r => `
      <tr>
        <td>${fmtDateTime(r.created_at)}</td>
        <td><span class="model-cell">${modelIcon(r.model)}${escapeHtml(r.model)}</span></td>
        <td class="num">${fmtTokens(r.input_tokens)}</td>
        <td class="num">${fmtTokens(r.output_tokens)}</td>
        <td class="num">${fmtTokens(r.reasoning_tokens)}</td>
        <td class="num">${fmtTokens(r.cache_read_tokens)}</td>
        <td class="num">${fmtMoney(r.cost_usd)}</td>
      </tr>
    `).join("");
  }
  
  // 更新分页器
  const totalPages = Math.max(1, Math.ceil(data.total / 10));
  $("key-detail-pager").textContent = `${t("pageOf")} ${state.keysView.detailPage} ${t("ofPages")} ${totalPages}`;
  $("key-detail-prev").disabled = state.keysView.detailPage <= 1;
  $("key-detail-next").disabled = state.keysView.detailPage >= totalPages;
}

function backToKeysList() {
  state.keysView.selectedKey = null;
  $("keys-list-view").hidden = false;
  $("key-detail-view").hidden = true;
}
```

**Step 3**: HTML 结构（index.html）

```html
<!-- 在 page-records 之后新增 -->
<section class="page" id="page-keys-view" hidden>
  <div class="ph"><h2 class="ph-title">按 Key 查看用量</h2></div>
  
  <!-- Key 列表视图 -->
  <div id="keys-list-view">
    <!-- 时间范围 + 账号筛选 -->
    <div class="filters">
      <div class="range-tabs">
        <button data-range="today" onclick="changeKeysRange('today')">今天</button>
        <button data-range="d7" onclick="changeKeysRange('d7')">近7天</button>
        <button data-range="d30" onclick="changeKeysRange('d30')">近30天</button>
        <button data-range="all" onclick="changeKeysRange('all')">全部</button>
      </div>
      <select id="keys-account-filter" class="select" onchange="changeKeysAccount(this.value)">
        <option value="">全部账号</option>
        <!-- 动态填充账号列表 -->
      </select>
    </div>
    
    <!-- 全局汇总 -->
    <div class="kpi-row kpi4" id="keys-totals"></div>
    
    <!-- Key 折叠面板 -->
    <div id="keys-container"></div>
  </div>
  
  <!-- Key 明细视图 -->
  <div id="key-detail-view" hidden>
    <div class="breadcrumb">
      <a onclick="backToKeysList()">← 返回 Key 列表</a>
    </div>
    <h3 id="key-detail-title"></h3>
    <div class="card">
      <div class="card-h">
        <select id="key-detail-model-filter" class="select" onchange="changeKeyDetailModel(this.value)">
          <option value="">全部模型</option>
        </select>
      </div>
      <table class="tbl">
        <thead>
          <tr>
            <th>时间</th>
            <th>模型</th>
            <th class="num">输入</th>
            <th class="num">输出</th>
            <th class="num">推理</th>
            <th class="num">缓存读</th>
            <th class="num">费用</th>
          </tr>
        </thead>
        <tbody id="key-records-body"></tbody>
      </table>
      <div class="pager">
        <button class="btn" id="key-detail-prev" onclick="prevKeyDetailPage()">上一页</button>
        <span class="pager-info" id="key-detail-pager"></span>
        <button class="btn" id="key-detail-next" onclick="nextKeyDetailPage()">下一页</button>
      </div>
    </div>
  </div>
</section>
```

**Step 4**: CSS 样式（style.css）

```css
/* Key 折叠面板 */
.key-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 12px;
  overflow: hidden;
}

.key-header {
  display: flex;
  align-items: center;
  padding: 16px;
  background: var(--bg2);
  cursor: pointer;
  transition: background 0.2s;
}

.key-header:hover {
  background: var(--bg3);
}

.key-icon {
  font-size: 20px;
  margin-right: 12px;
}

.key-name {
  flex: 1;
  font-weight: 600;
  color: var(--text1);
}

.key-stats {
  color: var(--text2);
  font-size: 14px;
  margin-right: 16px;
}

.key-toggle {
  font-size: 14px;
  color: var(--text3);
}

.key-body {
  display: none;
  padding: 16px;
  background: var(--bg1);
}

.key-panel.expanded .key-body {
  display: block;
}

.key-summary, .key-account, .key-id {
  margin-bottom: 8px;
  color: var(--text2);
  font-size: 14px;
}

.filters {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  align-items: center;
}
```

---

## 五、技术细节

### 5.1 状态持久化

使用 URL Hash 保存视图状态，支持刷新后恢复：

```javascript
// 写入 URL
function updateHash() {
  const params = new URLSearchParams();
  params.set("range", state.statsView.range);
  if (state.statsView.expandedChannels.length) {
    params.set("expanded", state.statsView.expandedChannels.join(","));
  }
  if (state.statsView.selectedAccount) {
    params.set("channel", state.statsView.selectedAccount.channel);
    params.set("account", state.statsView.selectedAccount.accountId);
    params.set("page", state.statsView.recordsPage);
  }
  location.hash = `#stats?${params.toString()}`;
}

// 从 URL 恢复
function restoreFromHash() {
  const hash = location.hash;
  if (!hash.startsWith("#stats?")) return;
  const params = new URLSearchParams(hash.slice(7));
  state.statsView.range = params.get("range") || "today";
  const expanded = params.get("expanded");
  if (expanded) state.statsView.expandedChannels = expanded.split(",");
  const channel = params.get("channel");
  const account = params.get("account");
  if (channel && account) {
    state.statsView.selectedAccount = { channel, accountId: parseInt(account) };
    state.statsView.recordsPage = parseInt(params.get("page")) || 1;
  }
}
```

### 5.2 性能优化

1. **增量渲染**：折叠状态变化时仅重新渲染受影响的面板，而非整个页面
2. **数据缓存**：渠道汇总数据缓存 30 秒，避免频繁请求
3. **虚拟滚动**（可选）：如果渠道数 > 20，考虑使用虚拟滚动

### 5.3 国际化

新增 i18n 键值（app/web/app.js）：

```javascript
const I18N = {
  zh: {
    channelAll: "全部渠道",
    channelRemote: "远程渠道",
    channelLocal: "本地渠道",
    channelSummary: "汇总",
    accountDetails: "账号明细",
    backToChannels: "返回渠道列表",
    noAccountsInChannel: "该渠道暂无账号",
    localChannelHint: "本地数据，无账号区分",
    ...
  },
  en: {
    channelAll: "All Channels",
    channelRemote: "Remote Channels",
    channelLocal: "Local Channels",
    channelSummary: "Summary",
    accountDetails: "Account Details",
    backToChannels: "Back to Channels",
    noAccountsInChannel: "No accounts in this channel",
    localChannelHint: "Local data, no account breakdown",
    ...
  }
};
```

---

## 六、风险评估与应对

### 6.1 key_names 映射缺失风险

**风险**：部分 Key 可能没有在 `settings.key_names` 中设置显示名，导致显示为原始 key_id

**应对**：
- 前端显示时，优先使用 `key_names` 映射，无映射时：
  - 完整 key_id：截取前 20 字符 + "..."
  - 空 key_id：显示"未归属"
- 提供"编辑 Key 名称"功能（可选，后续优化）

### 6.2 空 key_id 记录处理

**风险**：历史记录中可能有 `key_id` 为 NULL 或空字符串的记录

**应对**：
- 将所有空 key_id 记录归为一个特殊分组"未归属"
- 在 Key 列表中单独显示，放在末尾
- SQL 查询时使用 `COALESCE(key_id, '')` 统一处理

### 6.3 多账号数据隔离

**风险**：用户可能期望账号筛选后，只看到该账号的数据（不包括未归属记录）

**应对**：
- 默认行为：账号筛选后，未归属记录仍然显示（因为无法判断归属）
- 提供"严格模式"开关（可选）：勾选后完全过滤未归属记录

### 6.4 性能风险

**风险**：Key 数量过多（如 > 100 个）时，GROUP BY 查询可能较慢

**应对**：
- 在 `usage_records` 表的 `key_id` 列创建索引（如果尚未创建）
- 前端限制最多显示 50 个 Key，超过时分页或提供搜索框
- 增加结果缓存（30 秒 TTL）

### 6.5 本地数据割裂

**风险**：本地数据（ZCode/Claude Code/DSH/Codex）没有纳入 Key 维度，用户可能困惑

**应对**：
- 文档明确说明：本次改造仅针对远程数据（OpenCode/CommandCode）
- 在 Key 列表末尾增加提示："本地数据（ZCode/Claude Code/DSH/Codex）请查看统计页"
- 提供跳转链接："查看本地数据 →"

---

## 七、测试验证计划

### 7.1 单元测试

- [ ] 后端：`get_keys_summary()` 正确按 key_id 分组
- [ ] 后端：空 key_id 记录归入"未归属"分组
- [ ] 后端：账号筛选正确过滤数据
- [ ] 后端：时间范围筛选正确应用
- [ ] 前端：`toggleKey()` 正确更新 `expandedKeys` 数组
- [ ] 前端：Key 占比计算正确（总和为 100%）

### 7.2 集成测试

- [ ] 单账号 + 多 Key 场景：Key 列表正确显示，点击展开无报错
- [ ] 多账号 + 多 Key 场景：账号筛选正确过滤 Key
- [ ] 空 key_id 记录：正确归入"未归属"，点击查看明细正常
- [ ] Key 明细表格：数据正确，分页正常，模型筛选生效
- [ ] 时间范围切换：所有汇总数据联动更新

### 7.3 UI 测试

- [ ] 折叠/展开动画流畅（无闪烁）
- [ ] Key 名称过长时正确截断（前 20 字符 + ...）
- [ ] Tooltip 显示完整 key_id
- [ ] 暗色主题：所有新增组件颜色正确
- [ ] 移动端适配：Key 面板自适应

### 7.4 性能测试

- [ ] 50 个 Key：初始渲染 < 500ms
- [ ] 展开/收起单个 Key：< 100ms
- [ ] 切换账号筛选：重新加载数据 < 1s
- [ ] 明细表格分页：< 200ms

### 7.5 边界测试

- [ ] 无任何 Key（所有记录 key_id 为空）：正确显示"未归属"分组
- [ ] 单个 Key：折叠面板正常工作
- [ ] Key 名称包含特殊字符（HTML/JS 注入）：正确转义
- [ ] 同一账号的不同 Key：正确区分显示

---

## 八、上线计划

### 8.1 开发排期

| 阶段 | 任务 | 预计工时 | 完成标准 |
|-----|------|---------|---------|
| P1 | 后端：`get_keys_summary()` 函数开发 | 3h | 正确按 key_id 分组，支持账号筛选 |
| P2 | 后端：增强 `/api/usage/records` 接口 | 1h | 支持 key_id 参数筛选 |
| P3 | 后端：创建 key_id 索引（如未创建） | 0.5h | 查询性能优化 |
| P4 | 前端：状态管理 + Key 列表渲染 | 4h | Key 折叠/展开正常，UI 符合设计稿 |
| P5 | 前端：Key 明细视图 + 分页 | 2h | 明细表格正确显示，分页功能正常 |
| P6 | 前端：账号筛选器 | 1h | 动态加载账号列表，筛选正确联动 |
| P7 | CSS 样式调整 + 暗色主题 | 2h | 两种主题下样式无异常 |
| P8 | 国际化文案补全 | 1h | 中英文文案齐全，无遗漏 |
| P9 | 导航入口（侧边栏/顶部菜单） | 0.5h | 用户可找到新页面入口 |
| P10 | 集成测试 + Bug 修复 | 3h | 通过测试用例，无阻断性 Bug |
| **总计** | | **18h** | |

### 8.2 页面入口设计

**改造对象确认**：**page-records（使用记录页）**

**实施方式**：在现有"使用记录"页面增加 Tab 切换

```
使用记录页面结构：
┌─────────────────────────────────────┐
│ 使用记录                            │
│ [按时间查看] [按 Key 查看] ← Tab   │
├─────────────────────────────────────┤
│ 按时间查看：                        │
│   - 会话用量表（现有）              │
│   - 使用明细表（现有）              │
│                                     │
│ 按 Key 查看：                       │
│   - Key 折叠面板（新增）            │
│   - Key 明细表格（新增）            │
└─────────────────────────────────────┘
```

**实施步骤**：
1. 在 `page-records` 顶部增加 Tab 切换按钮
2. 默认显示"按时间查看"（现有的会话用量 + 使用明细）
3. 点击"按 Key 查看"时，隐藏现有表格，显示新的 Key 折叠视图
4. 两个 Tab 共享时间范围选择器和账号筛选器

**优点**：
- 改造目标明确：page-records
- 不影响 page-stats（用量统计页）的本地数据展示
- 用户可自由切换两种维度查看同一数据源
- 实现成本低，风险可控

### 8.3 灰度方案（可选）

如果担心改动影响现有用户：

1. **配置开关**：`settings.enable_keys_view: boolean`（默认 false）
2. **设置页控制**：用户可在设置中启用"按 Key 查看用量（实验性功能）"
3. **渐进上线**：
   - Week 1：仅内部测试用户启用
   - Week 2：向 20% 用户灰度
   - Week 3：全量上线

### 8.4 回滚预案

如果上线后发现严重问题：

1. **配置开关降级**：`enable_keys_view: false`，隐藏入口
2. **代码回滚**：保留旧版"使用记录"页面不变，新功能可快速移除

---

## 九、后续优化方向

### 9.1 短期（1-2 周内）

- [ ] Key 编辑功能：点击 Key 名称可直接修改显示名（更新 `key_names`）
- [ ] Key 搜索框：Key 数量 > 20 时，提供实时搜索筛选
- [ ] 批量导出：选中多个 Key，批量导出 CSV
- [ ] Key 使用趋势：在 Key 卡片中增加"本周趋势"迷你图（Sparkline）

### 9.2 中期（1 个月内）

- [ ] Key 分组标签：用户可为 Key 添加标签（如"生产"、"测试"），按标签筛选
- [ ] 预算告警：为单个 Key 设置预算上限，超过时高亮提示
- [ ] Key 对比视图：选中 2-3 个 Key，并排对比用量
- [ ] Key 归档：长期未使用的 Key 自动归档（不影响历史数据）

### 9.3 长期（待规划）

- [ ] 本地数据 Key 支持：将 ZCode/Claude Code 的 channel 映射为"虚拟 Key"
- [ ] Key 权限管理：标记哪些 Key 是生产环境，显示额外警告
- [ ] 异常检测：自动识别单个 Key 的用量异常波动
- [ ] 成本归因：按 Key → 会话 → 项目的三级归因

---

## 十、附录

### 10.1 与首页功能对比

| 维度 | 首页（现有） | 本方案（新增） |
|-----|------------|--------------|
| 主要维度 | 产品（OpenCode/ZCode/...） | API Key |
| 展示方式 | Tab 切换 | 折叠面板 |
| 汇总粒度 | 按产品汇总 | 按 Key 汇总 |
| 明细查看 | 无明细表格 | 点击 Key 查看明细 |
| 筛选能力 | 无 | 支持账号筛选 |
| 核心问题 | "哪个产品用量大？" | "哪个 Key 花费多？" |

**结论**：两者互补，不冲突。首页关注产品维度，新方案关注 Key 维度。

### 10.2 数据口径说明

- **total_tokens**：input + output + reasoning + cache_read（与现有口径一致）
- **hit_rate**：cache_read / (cache_read + input) * 100%
- **cost_usd**：原始费用字段，单位美元
- **percentage**：该 Key 费用占所有 Key 费用总和的百分比

### 10.3 原型图链接（待补充）

TODO: 使用 Figma/Sketch 绘制高保真原型

### 10.4 参考资料

- 现有代码：`app/web/app.js` L1609-1650（使用记录渲染逻辑）
- 现有代码：`app/db.py` L860-900（usage_records 写入逻辑）
- 现有代码：`app/server.py` L1685-1690（key_names 映射）
- 类似产品：
  - OpenAI Dashboard：按 API Key 分组查看用量
  - Anthropic Console：工作区内按 Key 统计
  - Stripe Dashboard：按产品/客户维度切换

### 10.5 FAQ

**Q1：为什么改造 page-records（使用记录），而不是 page-stats（用量统计）？**  
A：
- **page-stats** 包含本地数据（ZCode/DSH/Claude Code/Codex），数据源异构，难以统一按 Key 分组
- **page-records** 仅包含远程数据（OpenCode/CommandCode），数据源统一（usage_records 表），有 key_id 字段
- 用户截图显示的混乱主要是"使用明细表"（page-records 的一部分），改造这里最直接

**Q2：为什么不按"产品"分组？**  
A：首页已经按产品（OpenCode/CommandCode/ZCode...）分 Tab 展示，统计页再重复会造成功能冗余。用户真正关心的是"哪个 Key 花费最多"，这是 Key 维度才能回答的问题。

**Q3：本地数据（ZCode/Claude Code/DSH/Codex）怎么办？**  
A：本地数据保持在 page-stats（用量统计页）独立展示，本次改造不涉及。未来可考虑将 channel 映射为"虚拟 Key"。

**Q4：如果用户有 100 个 Key，页面会很卡吗？**  
A：会做以下优化：
  - 默认折叠，减少初始 DOM 节点
  - 超过 50 个 Key 时分页或提供搜索框
  - 创建 key_id 索引加速查询

**Q5：与现有"使用记录"页面是什么关系？**  
A：在"使用记录"页面增加 Tab 切换：[按时间查看] [按 Key 查看]，两种维度共存，用户自由切换。

**Q6：会影响现有功能吗？**  
A：不会。新增独立的接口和 Tab 视图，现有"按时间查看"保持不变。可通过配置开关灰度上线。

**Q7：为什么不在 page-stats 统一所有数据源？**  
A：技术难度高（本地数据无 key_id），且用户截图中的混乱主要在"使用明细表"（属于 page-records）。优先解决核心痛点。

---

**文档状态**: 待审核  
**审核人**: （待填写）  
**审核日期**: （待填写）  
**批准实施**: ☐ 是  ☐ 否（原因：_____）
