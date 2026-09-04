# CommandCode Go 套餐用量接入实施文档

- 日期：2026-09-03（v3，已经真实登录会话抓包核对全部接口）
- 状态：待确认（本文档确认后才开始编码）
- 关联：GoGauge v2.x，新增 commandcode.ai 数据源

## 1. 背景

GoGauge 目前支持两类数据源：opencode（token 认证）与 bai（WebView 登录取 cookie）。
用户希望同样监控 commandcode.ai（Command Code，$1/月 Go 套餐）的用量。

最终结论：**会话 cookie 一条路径覆盖全部功能**（与 opencode go / bai 的"登录即用"一致，
不需要 API key）。已用真实登录会话（浏览器直接访问 API）逐端点抓包核对，见 §2。

## 2. 真实抓包结果（2026-09-03，已登录会话，全部 200）

### 2.1 端点与用途

| 端点 | 内容 | 用途 |
|---|---|---|
| `GET /internal/usage?limit=&cursor=` | 请求级明细，cursor 分页 | 使用记录页 |
| `GET /internal/usage/summary` | 账期汇总（默认 `billing-period` 口径） | 首页汇总卡片 |
| `GET /internal/usage/charts` | **5 分钟桶 × 模型**聚合（含缓存 token 拆分） | 定时入库积累 → 趋势/模型排行/Token 构成 |
| `GET /internal/billing/credits` | 余额 + `windowLimits`（fiveHour/weekly） | 配额窗口 |
| `GET /internal/billing/subscriptions?withPending=true` | planId/status/账期起止 | 套餐与月度窗口 |

参数实测：`days`、`since` 参数在 usage 与 charts 上**均被服务端忽略**——
明细窗口固定最近 **24 小时**（响应 `window:{days:1,entries:100}`，cursor 内 `since`=24h 前），
charts 默认约 **1 小时**的 5 分钟桶。历史数据只能靠本地定时同步积累。

### 2.2 明细记录（/internal/usage，真实样例字段）

```json
{
  "id": "ba88574c-142d-4834-b679-85b70e32f168",
  "createdAt": "2026-09-03T09:19:10.807Z",
  "tokensIn": "13145",            // 注意：字符串
  "tokensOut": "3681",            // 字符串
  "durationTotal": "31470",       // 字符串，毫秒
  "status": "completed",
  "message": null,
  "meta": {
    "totalCost": 0.0020507,       // 数值，USD
    "inputCost": 0.0013145,
    "outputCost": 0.0007362,
    "cacheCost": 0,
    "model": "meta/muse-spark-1.3-contributor",
    "traceId": "2805c0f9576f9f6907142d49a4f5e369"
  },
  "type": "api",
  "mode": "agent"
}
```

响应外层：`{"usages":[...], "nextCursor":"<base64>", "limit":3, "periodBasis":"plan-window", "window":{"days":1,"entries":100}}`。
nextCursor 解码后为 `{"createdAt","id","since","seen"}`，翻页时原样回传即可。

与 opencode 记录的差异：token/时长是**字符串**需转 int；cost 是浮点 USD（opencode 是 1e-8 整数）；
**没有** keyID/sessionID/总 token/缓存读写字段（`meta.traceId` 可作会话关联的近似键；
provider 明细里没有，统一记 "commandcode"）。

### 2.3 配额（/internal/billing/credits，真实样例）

```json
{
  "credits": { "belowThreshold": false, "creditThreshold": 0,
    "monthlyCredits": 9.619862652, "purchasedCredits": 0,
    "premiumMonthlyCredits": 0, "opensourceMonthlyCredits": 9.619862652 },
  "windowLimits": { "limited": true, "exceeded": null,
    "fiveHour": { "used": 0.278591918, "cap": 3, "exceeded": false, "resetAt": 1788443537003 },
    "weekly":   { "used": 0.278591918, "cap": 6, "exceeded": false, "resetAt": 1789030337003 } }
}
```

计量单位为美元额度（Go 套餐池 $10：剩余 9.62 + 已花 0.38 = 10.0）；`resetAt` 为 epoch 毫秒；
**无 monthly 窗口**——月度 = 套餐池（planId→额度，individual-go=$10）与剩余值在本地计算，
账期重置时间取 subscriptions 的 `currentPeriodEnd`（实测 2026-08-25 → 2026-09-25，`planId:"individual-go"`, `status:"active"`）。

### 2.4 汇总与图表

`/internal/usage/summary`（默认即账期口径）：

```json
{ "totalCount": 205, "totalCost": 0.380137348, "averageCost": 0.0018543285268292683,
  "successRate": 100, "completedCount": 205, "failedCount": 0,
  "totalTokensIn": 17012331, "totalTokensOut": 125320, "totalTokens": 17137651,
  "totalCredits": 0.380137348, "totalFreeCredits": 0,
  "totalMonthlyCredits": 0.380137348, "totalPurchasedCredits": 0,
  "periodBasis": "billing-period" }
```

`/internal/usage/charts`（5 分钟桶 × 模型，真实样例单条）：

```json
{ "model": "meta/muse-spark-1.3-contributor", "provider": "vercel-ai-gateway",
  "timeBucket": "2026-09-03 08:50:00", "requests": 16,
  "totalCost": 0.031323546, "inputCost": 0.0278411, "outputCost": 0.0018564, "cacheCost": 0.001626046,
  "cacheSavings": 0.079676254,
  "consumedFreeCredits": 0, "consumedMonthlyCredits": 0.031323546, "consumedPurchasedCredits": 0,
  "tokensIn": 1091434, "tokensOut": 9282, "tokensTotal": 1100716,
  "cacheReadInputTokens": 813023, "cacheCreationInputTokens": 0 }
```

注意：charts 的数值是**数字**（明细里是字符串）；它含缓存读写 token，是 Token 构成/缓存命中率
的唯一数据源；settings/usage 页面本身未调用它（无参数可参考），实测 `days`/`since` 均被忽略。

### 2.5 认证与错误形态

- 认证：better-auth 会话 cookie（浏览器带 cookie 直接访问 API 实测通过；WebView 登录后从
  cookie store 提取 `.commandcode.ai` 会话 cookie 回放，与 bai 相同做法）。cookie 名与作用域在实现首日确认。
- 401（会话失效）：`{"success":false,"error":{"code":"UNAUTHORIZED","message":"You're logged out..."}}`
- 服务端故障变体：**HTTP 200** + `{"success":false,"error":"<字符串>"}`（实测 subscriptions 出现过 Hyperdrive 错误）
- 成功判定：HTTP 2xx 且 body 无 `"success":false`；`error` 可能是对象或字符串，都兼容。
- 包裹层差异：usage/credits 顶层就是数据；subscriptions/charts 包在 `{"success":true,"data":...}` 里。

## 3. 实施方案

### 3.1 新增 `app/commandcode_api.py`（参照 bai_api.py 模式）

```python
API_BASE = "https://api.commandcode.ai"

def fetch_quota(cookie: str) -> dict
    # /internal/billing/credits → fiveHour/weekly 窗口(USD used/cap/resetAt) + monthlyCredits
    # /internal/billing/subscriptions?withPending=true → planId/status/currentPeriodEnd/userId
    # 产出与现有 quota 字典同构的窗口数据；不落库（与 opencode/bai 一致，仅内存 TTL 缓存）
def fetch_summary(cookie: str) -> dict          # /internal/usage/summary（账期口径）
def fetch_usage_page(cookie: str, limit=50, cursor="") -> (list[dict], next_cursor)
    # /internal/usage；字符串字段转 int；仅能取最近 24h
def fetch_charts(cookie: str) -> list[dict]     # /internal/usage/charts 5 分钟桶
```

- 配额窗口映射：`5h Rolling`/`Weekly` 用 used/cap（USD），百分比=used/cap×100，reset_at 由 epoch ms 转换；
  `Monthly` 用 套餐池总额度（按 planId 查表，individual-go=10，未知套餐用"剩余+账期已花"兜底）与
  `currentPeriodEnd`。
- 明细映射到 `usage_records`：`usg_id=id`、`created_at=createdAt`、`model=meta.model`、
  `provider="commandcode"`、`input_tokens=tokensIn`、`output_tokens=tokensOut`、`reasoning=0`、
  缓存读写=0（明细无）、`cost_usd=meta.totalCost`、`cost_raw=round(meta.totalCost×1e8)`
  （对齐 opencode 的 1e-8 整数语义；参考 bai 的 COST_USD_SCALE 做法）、`key_id=""`、
  `session_id=meta.traceId`、`plan=planId`。字符串数值全部容错转换（bai 的 `_to_int` 已有
  "数字字符串自动转 int" 先例，直接复用该模式）。
- 同步翻页策略（照 bai 的 G3 模式）：cursor 循环 + **命中库中已有 usg_id 即停**（增量）；
  页数上限防失控（同 `BAI_MAX_PAGES` 做法，明细窗口 24h 实际页数很小）。

### 3.2 历史数据策略（与 opencode 的关键差异）

明细只有最近 24h、charts 只有约 1h → **同步范围设置对 commandcode 的含义变化**：
不再决定"能拉取多少历史"（API 固定 24h 窗口），仅决定本地 usage_records 的裁剪保留窗口
（见下方裁剪策略）；设置页控件保留，不按账户隐藏：
- 首次同步只能拿到最近 24h 明细 + 当前账期汇总；之后靠定时同步**增量积累本地历史**。
- charts 5 分钟桶每次同步入库（按 **account_id + model + provider + timeBucket** 去重合并；
  **必须带 account_id 维度**——本项目是多用户架构，多 commandcode 账户的桶数据不能混淆）
  → 用于 7 日趋势、模型排行、Token 构成（含缓存命中），随使用时间逐步完整。
- 首页汇总卡片直接展示 summary（账期口径），与网页 Studio 一致。
- 裁剪策略：`usage_records` 沿用全局同步范围（window_days）裁剪，与其他数据源行为一致；
  **charts 桶表不裁剪**（单账户数据量极小：每天 ≤ 288 桶 × 模型数，且是历史统计的唯一来源）。

### 3.3 登录与既有代码集成点

| 文件 | 改动 |
|---|---|
| `app/auth.py` | `build_login_url("commandcode")` → `https://commandcode.ai/signin`；`LoginWatcher` 增加 `_handle_commandcode` 分支（照 bai 模式）；同步扩展 `_ACCOUNT_TYPES`、`_login_window_title`（注意 `LoginWatcher.__init__` 会把未知 account_type 强制回退 "opencode"，auth.py:206）；cookie 提取存入 accounts.token |
| `app/db.py` | `accounts.source` 列无 CHECK 约束无需改列；实际改动是 `add_account` 增加 commandcode 分支（**去重键 = userId**，登录成功后经 subscriptions 的 `data.userId` 获取，同 bai 的 userId 模式存 workspace_hint 字段）；新增 charts 桶表（**主键 (account_id, model, provider, time_bucket)**；`timeBucket` 为无时区字符串、实测为 UTC——与明细 `createdAt` 的 Z 时间对齐；另存 requests/费用四项/credits 拆分/tokensIn/Out/Total/cacheRead/cacheCreation）；新增桶表聚合查询（产出与现有 trend/models/today_trend 同构的数据）；usage_records 复用；**最终评审补充：`delete_account`/`clear_account` 需级联清理该账户的 `charts_buckets` 行与 payload 中 `cc_summary` 键**（账户 id 会被复用，不清理会导致新账户读到已删账户的"幽灵历史"，且违反 delete_account 自身"级联删除本地全部数据"的契约） |
| `app/server.py` | **配额分派点在 `_fetch_quota_with_cache`（server.py:144，dashboard 加载路径、TTL 缓存）**：按 `_account_source` 增加 commandcode 分支调 `fetch_quota`，缺失该分支会落入 opencode 分支导致首页 3 窗口报错；`sync_usage` 按 source 分派新增 `_sync_commandcode_account()`（只负责明细翻页入库 + charts 桶入库 + summary 存 sync_state）；`/api/dashboard` 与统计页聚合按 source 分支：commandcode 账户的 trend/models/Token 构成改由 charts 桶表聚合产出，summary 卡片数据一并附带返回 |
| `app/main.py` | 账户页新增 "Command Code" WebView 登录入口 |
| `app/web/*` | 配额窗口渲染 USD 单位与 Monthly 池；设置页**保留**全局同步范围控件（其对 commandcode 的 usage_records 裁剪仍然生效），在 commandcode 账户卡片注明"API 仅提供最近 24h 明细，更早历史自接入起本地积累"；统计页对 commandcode 账户消费新的桶表聚合数据；来源徽章增加 commandcode 分支（`app.js` 现仅处理 `source==="bai"`，见 renderUserMenu/renderUsersList）+ 对应 i18n 文案 |
| `tests/` | `tests/test_commandcode_api.py`：样例响应解析（字符串数值/包裹层/两种 error 形态）、窗口换算、cursor 翻页、401 处理 |

### 3.4 不做的事

- 不做 API key 路径（cookie 已全覆盖）；不做内置浏览器自动化登录；不调用 staging。
- cap 数值不硬编码的边界：5h/weekly 的 cap **读响应**（随套餐变化）；**月度池总额度不在任何响应中**，
  只能按 planId 查表（CLI `Zn` 表，individual-go=10），未知套餐用"剩余 monthlyCredits + summary.totalCost"兜底——两处口径以此为准。

## 4. 风险

1. `/internal/*` 为无官方文档承诺的内部接口，可能变化 → 字段容错 + 失败显式报错。
2. 会话 cookie 过期时长未知 → 401 时 UI 提示重新登录；单账户失败不影响其他账户。
3. 服务端偶发 200+错误 body（Hyperdrive）→ 按 §2.5 判定成功，失败重试。
4. 历史数据从接入时开始积累，接入前的明细无法回补（仅账期汇总可看）。

## 5. 验证标准

1. `python -m pytest tests/test_commandcode_api.py` 全绿；现有测试不回归。
2. 真实登录冒烟：WebView 登录 → 同步成功 → 首页 3 窗口（5h/Weekly/Monthly，USD）+ 账期汇总卡片
   + 使用记录（最近 24h，与网页 Studio 一致）；统计页随 charts 积累出现趋势/模型数据。
3. 断网/失效凭据：可读错误提示（cookie 过期提示重新登录），不影响 opencode/bai 账户同步。
