# ZCode 用量与 GLM Coding Plan 额度接入实施文档

- 日期：2026-09-03（v2，纳入用户反馈：费用估算参照 BAI / 项目维度不做 / 按渠道拆分 token
  与估算 / 获取各渠道 token 秒速）
- 状态：**待确认（本文档确认后才开始编码）**
- 关联：GoGauge v2.1.x；参考实现 `F:\GitHubs\zai-floating-monitor`（Rust/Tauri）
- 范围（用户已确认）：额度 + 本地会话用量；**费用估算参照 BAI 模式**；**按渠道（provider）
  拆分 token 消耗、估算费用与秒速**；**项目维度不做**

## 1. 背景与目标

GoGauge 目前支持 opencode / bai（/ commandcode 进行中）三类远程数据源。用户希望参照
zai-floating-monitor，接入 ZCode 客户端的两类数据：

1. **GLM Coding Plan 额度**：套餐等级 + 5 小时窗口 + 每周窗口 + MCP 月度额度的用量百分比
   与重置时间（数据来自智谱 BigModel / Z.ai 的额度接口，凭证自动取自本机 ZCode 登录态）。
2. **ZCode 本地会话用量**：ZCode 客户端在本机 `~/.zcode/cli/db/db.sqlite` 记录的全部模型
   请求用量（含 GLM Coding Plan 与用户自配的第三方渠道），**按渠道拆分**聚合出 token 消耗、
   **估算费用（参照 BAI 的本地定价表方式）**、**token 秒速**（输出速度/首字延迟）等统计。

## 2. 调研结果（zai-floating-monitor 的获取方式，均已核实）

### 2.1 GLM Coding Plan 额度（src-tauri/src/quota.rs）

链路：**读本地 ZCode 登录凭证 → 推断端点 → 请求额度接口 → 解析窗口**。

1. **凭证定位**（只读，绝不写回 ZCode 数据目录）：
   - v2 数据目录默认 `~/.zcode/v2`；支持「更改数据目录」迁移——读默认位置
     `setting.json` 顶层 `dataBaseDir` 字段（trim 后非空且为**绝对路径**才认），
     迁移后目录为 `{dataBaseDir}/.zcode/v2`（目录存在才启用，否则回退默认）。
   - 读 `{v2目录}/config.json` 顶层 `provider` map，按固定顺序选 Coding Plan 凭证：
     `builtin:bigmodel-coding-plan` → `builtin:zai-coding-plan` → 回退任意 key 含
     `"coding-plan"` 且 `options.apiKey` 非空（trim）的 provider。
     `*-start-plan`（轻量入门订阅）key 不含该子串，天然被排除。
   - 取该 provider 的 `options.apiKey`（Authorization 用）与 `options.baseURL`（缺失给空串）。
2. **端点推断**：baseURL 含 `z.ai` → `https://api.z.ai`；否则（含 bigmodel / 空）→
   `https://open.bigmodel.cn`。
3. **请求**：`GET {base}/api/monitor/usage/quota/limit`，Header `Authorization: <apiKey>`，
   15s 超时。
4. **响应**：`{success, msg, data:{level, limits[]}}`：
   - `data.level`：套餐等级（"pro" / "max" …）；
   - `limits[]` 每条：`type`、`unit`、`number`、`percentage`(0-100)、`nextResetTime`(ms，
     可缺失)、`currentValue`、`usage`、`usageDetails[]`；
   - `type=TIME_LIMIT` → **MCP 月度额度**（`currentValue`=已用次数，`usage`=总额度次数，
     注意字段名，`usageDetails` 为按工具拆分）；
   - `type=TOKENS_LIMIT` 且 `unit=3, number=5` → **5 小时窗口**；`unit=6, number=1` →
     **每周窗口**（这两类只看 `percentage` 与 `nextResetTime`）；
   - 同一账号多订阅时同窗口会出现多条：按 `nextResetTime` 升序取第一条（最活跃订阅，
     保证轮询间稳定，None 排最后）；5h 窗口刚刷新后可能无 `nextResetTime`。
5. **错误约定**：未登录/凭证缺失的文案以「未找到 ZCode Coding Plan 凭证」开头，前端以该
   前缀识别为登录引导分支。

本机已验证：`~/.zcode/v2/config.json` 存在，`builtin:bigmodel-coding-plan` 已登录
（apiKey 非空，baseURL 为国内站）。

### 2.2 ZCode 本地会话用量（src-tauri/src/db.rs + zcode_sessions.rs）

- 主数据源：`~/.zcode/cli/db/db.sqlite` 的 **`model_usage` 表**（zai-floating-monitor 的
  口径铁律：统计永远读该表本体，会话文件 rollout 只做镜像留存）。
- 打开方式：**只读**（`file:...?mode=ro` URI，显式 mode=ro 才是稳定保证；主库正被 ZCode
  写入，WAL 模式允许并发读）。
- 本机实测 schema 关键列：`id`(TEXT 主键，稳定去重键)、`session_id`、`provider_id`、
  `model_id`、`status`、`started_at`(epoch ms)、`duration_ms`、`time_to_first_token_ms`、
  `input_tokens`、`output_tokens`、`reasoning_tokens`、`cache_creation_input_tokens`、
  `cache_read_input_tokens`、`computed_total_tokens`。**无 cost 字段**（费用需本地估算）。
- **秒速可行性（本机实测）**：`duration_ms` **全渠道 100% 覆盖** → 输出速度(tok/s)全渠道
  可算；`time_to_first_token_ms` 覆盖 50%-88%（按有值样本平均，缺失行不参与）。
- 本机实测：12586 行（completed 12305 / cancelled 127 / error 161）；渠道分布 = GLM Coding
  Plan(6442) + GLM Start Plan(2099) + 7 个第三方渠道 UUID(火山 ark / tokenrhythm / b.ai /
  tokenrouter 等，3929)。即"ZCode 用量"应**全量导入**（对齐参考实现：统计不过滤 status，
  全部行计入）。
- 渠道友好名来源：`config.json` 的 provider map 中每个渠道有 `name` 字段（如「自定义中转」），
  导入时一并读取建立 provider_id → name 快照。
- 另有 `session` 表含 `directory` 列（项目归属）。**用户已确认项目维度不做**（GoGauge 现有
  opencode 统计亦无项目维度，对齐功能边界）。
- 参考实现无增量水位（每次全量聚合 SQL）；GoGauge 是导入式架构，用 `started_at` 水位 +
  主键幂等做增量。

### 2.3 BAI 的费用估算模式（本程序 app/bai_api.py，作为 zcode 估算的参照）

- **定价表**：本地文件 `C:\Users\11013\.cc-switch\model-pricing.json`（外部共享，cc-switch
  维护），结构 `{"models":[{modelId, inputCostPerMillion, outputCostPerMillion,
  cacheReadCostPerMillion, cacheCreationCostPerMillion}]}`，单价单位 USD/百万 token；
  文件缺失/损坏/结构不符 → 空表，该批成本按 0（不影响主流程）。
- **公式**（`_compute_cost_raw`）：`cost = input×in + output×out + cache_read×cr +
  (cache_write_5m + cache_write_1h)×cw`，USD → `cost_raw`（1e-8 USD 整数，`COST_USD_SCALE`）。
  cache_creation 5m/1h 共用 `cacheCreationCostPerMillion` 单价。未收录模型 → 0。
- **时机**：解析记录时算好落库 `usage_records.cost_raw`（不是查询时现算）——定价表更新不
  追溯历史行（既有口径，zcode 沿用）。
- **模型名匹配**：`_strip_provider_prefix` 剥 provider 前缀（`glm/glm-5.3-flash` →
  `glm-5.3-flash`）后按 `modelId` 精确匹配。
- **zcode 适配点（本机实测）**：zcode 的模型名**大小写不一**（`GLM-5.3` 与 `glm-5.3` 并存，
  来自不同渠道的同一模型），须在 strip 前缀后再做**大小写归一**匹配——实测 13 个在用模型
  归一后 10 个收录（GLM-5.3/Flash、glm-5.3/flash、muse-spark、qwen3.8-flash、
  deepseek-v4-flash 等），未收录 4 个（ox-alpha(-free)、qwen3.8-27b、z-ai/glm-5.3-free，
  均为免费/中转模型，按 0 合理）。
- **zcode token 字段对应**：zcode 只有一个 `cache_creation_input_tokens`（无 5m/1h 之分），
  直接乘 `cacheCreationCostPerMillion`；`reasoning_tokens` 不单独计价（与 BAI 对 glm 系
  模型同公式同口径）。

## 3. 方案选择：独立数据域（不进 accounts 体系）

ZCode 数据是**本机全局单份**（无登录流程、无多账户语义），与 opencode/bai/commandcode
的"可登录账户"模型不同。两个候选：

| | A. 伪账户（accounts 表加 source='zcode' 行） | B. 独立数据域（推荐） |
|---|---|---|
| 做法 | zcode 数据导入 `usage_records`，挂在伪账户下 | 新表 `zcode_usage` + 专属聚合查询与展示区块 |
| 复用 | 统计/趋势/模型排行 SQL 直接复用 | 需新增聚合查询（与现有同构） |
| 侵入 | 大：switch 要求 token 非空（server.py:711 分支）、overview 按 `has_token` 过滤、`logged_in` 判断、rename/delete/logout 语义全要为 zcode 开洞 | 小：完全不碰 accounts / 活跃账户 / 登录态逻辑 |
| 费用语义 | 估算费用混入 `usage_records` 费用统计，与 opencode API 返回的真实计费不可区分，污染总费用口径 | 独立区块，估算费用单列并明确标注"估算"，与真实费用不混淆 |
| 多账户污染 | zcode 行会混进"全部账户"类聚合 | 零污染：现有所有按 account_id 的查询不受影响 |

**选定 B**。额度卡片亦独立于账户配额（首页新增独立区块，不占用 `usage-blocks` 的活跃账户
配额位）。参考实现同样是把 zcode 作为独立数据源（统计面板里与 codex/claude 并列），而非
混入其他数据源。

## 4. 实施方案

### 4.1 新增 `app/zcode_api.py`（ZCode 数据源客户端）

```python
# --- 凭证与额度（移植 quota.rs 逻辑） ---
def zcode_v2_dir() -> Path              # ~/.zcode/v2 + setting.json dataBaseDir 迁移
def pick_coding_plan_credential(providers: dict) -> tuple[str, str, str] | None
    # (provider_key, api_key, base_url)；内置顺序 + "coding-plan" 回退
def base_from_provider_url(url: str) -> str   # z.ai → https://api.z.ai else open.bigmodel.cn
def fetch_quota() -> dict
    # 读凭证 → GET {base}/api/monitor/usage/quota/limit (Authorization, 15s 超时)
    # → 解析 level + 5h/weekly/MCP 三窗口；失败返回 {"success": False, "error": ...}
    # 未登录错误文案以「未找到 ZCode Coding Plan 凭证」开头（前端登录引导分支）

# --- 本地会话用量（只读） ---
ZCODE_DB = Path("~/.zcode/cli/db/db.sqlite").expanduser()   # 常量，不做环境变量覆盖
def collect_local_usage(since_ms: int) -> list[dict]
    # file: URI mode=ro 打开（百分号转义保留字符），busy_timeout 3s
    # SELECT ... FROM model_usage WHERE started_at > ? ；列缺失时容错（参考实现逐字段容错）
    # 返回行：id/started_at(ms)/session_id/provider_id/model_id/status/
    #         input_tokens/output_tokens/reasoning_tokens/
    #         cache_creation_input_tokens/cache_read_input_tokens/computed_total_tokens/
    #         duration_ms/time_to_first_token_ms

# --- 费用估算（参照 bai_api 口径 D1） ---
def read_provider_names() -> dict[str, str]
    # 读 config.json provider map → {provider_id: name}（渠道友好名快照，供导入填充）
def estimate_cost_raw(model, input, output, cache_read, cache_write,
                      models: list | None = None) -> int
    # 复用 bai_api._load_model_pricing 读定价表 + _parse_million_cost 单价解析；
    # 公式与 BAI 完全一致（input/output/cacheRead/cacheCreation 四项，1e-8 USD 整数）；
    # 差异仅匹配环节：_strip_provider_prefix 前缀剥离后增加大小写归一
    # （zcode 模型名 GLM-5.3 / glm-5.3 并存；BAI 原函数精确匹配不动，避免影响 BAI 行为）
    # models 传入预加载的定价表（批量导入只加载一次）；None 时自行加载（单条/测试用）
    # 未收录模型 / 定价表缺失 → 0
```

额度返回结构对齐前端 `quota.windows` 渲染约定（`{label, used, reset_in_sec}`），并扩展
MCP 专属字段：

```json
{ "success": true, "level": "pro", "windows": [
    { "label": "5h Rolling", "used": 42, "reset_in_sec": 3600 },
    { "label": "Weekly",     "used": 67, "reset_in_sec": 86400 },
    { "label": "MCP Monthly","used": 23, "used_count": 46, "total_count": 200,
      "reset_in_sec": 7200 }
] }
```

- `used` 一律为百分比（0-100）；MCP 额外带 `used_count`/`total_count` 次数。
- 多条同 (unit, number) 窗口按 `nextResetTime` 升序取首；`nextResetTime` 缺失时
  `reset_in_sec` 为 0，前端显示"—"。
- `usageDetails`（MCP 按工具拆分）本次不展示（YAGNI）。
- 网络访问参照 `bai_api.py` 的 urllib 用法（项目零第三方 HTTP 依赖）。

### 4.2 `app/db.py`：新表 + 聚合查询 + 水位

```sql
CREATE TABLE IF NOT EXISTS zcode_usage (
  id TEXT PRIMARY KEY,              -- model_usage.id，幂等去重键
  started_at TEXT NOT NULL,         -- epoch ms → **UTC ISO**（fromtimestamp(ms/1000, timezone.utc)，
                                     --   与 usage_records.created_at 同风格；聚合查询统一用
                                     --   'localtime' 修饰符转本地——**不可存本地时间**，
                                     --   否则双重偏移、跨日统计错位）
  session_id TEXT,
  provider_id TEXT,                 -- 渠道 ID（builtin:* 或 UUID）
  provider_name TEXT,               -- config.json 的 provider.name 快照（导入时填充，可 NULL）
  model_id TEXT,
  status TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens INTEGER NOT NULL DEFAULT 0,   -- cache_creation_input_tokens
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  total_tokens INTEGER NOT NULL DEFAULT 0,         -- computed_total_tokens
  duration_ms INTEGER,                              -- 100% 覆盖，秒速计算依据
  ttft_ms INTEGER,                                  -- time_to_first_token_ms，约 50-88% 覆盖
  cost_raw INTEGER NOT NULL DEFAULT 0,              -- 导入时按定价表估算（1e-8 USD，同 BAI 口径）
  synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_zcode_time ON zcode_usage(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_zcode_provider ON zcode_usage(provider_id);
```

- **导入**：`import_zcode_usage(rows, provider_names) -> int`——每行先过
  `estimate_cost_raw` 算估算费用，连同 `provider_name` 快照一起
  `INSERT OR IGNORE`，返回新增行数。
- **水位**：settings payload 新键 `zcode_last_started_at`（epoch ms）；每次导入后取
  `MAX(started_at)` 推进；导入条件 `started_at > 水位 - 10min`（重叠窗口防边界丢行，
  主键幂等兜底重复）。首次导入水位为 0 → 全量（本机 1.2 万行，毫秒级）。
  **注意**：`get_settings`/`save_settings` 是 `_DEFAULT_SETTINGS` 白名单键过滤
  （db.py:836/857），该键不在白名单内，**必须参照 `save_key_names` 模式用
  `_raw_payload`/`_write_payload` 直接读写**（db.py 内新增两个小函数），走
  `save_settings()` 会静默丢弃。
- **秒速口径（与参考实现 db.rs speed_agg_columns 完全一致）**：
  - **有效生成窗口** `gen`：`0 ≤ TTFT ≤ duration` 且 `TTFT×10 < duration×9` 时取
    `duration − TTFT`（剔除首字等待）；`TTFT ≥ 90%×duration` 时取 `TTFT` 本身
    （几乎无生成阶段）；TTFT 无效/缺失时取 `duration`；
  - **逐行速率**（仅可信样本）：`output_tokens ≥ 10` 且 `gen ≥ 100ms` 且
    `output×1000/gen ≤ 500 tok/s`（剔异常高速噪声）；
  - `avg_tps = AVG(逐行速率)`（**非 SUM/SUM 加权**）、`max_tps = MAX(逐行速率)`、
    `avg_ttft_ms = AVG(有效 TTFT)`（有效条件 `0 ≤ TTFT ≤ duration`）。
- **聚合**（与现有 `model_stats/daily_stats/totals` 同构）：
  - `zcode_totals(period)`：请求 / 总输入(含缓存) / 普通输入 / 推理 / 缓存命中 / 缓存写入 /
    输出 / 总 Token / **估算费用(cost_usd)** / **avg_tps / max_tps / avg_ttft_ms**
    （按上述口径）；
  - `zcode_daily(days)`：每日趋势，字段同上（无速度）；
  - **`zcode_provider_stats(period)`：按渠道（provider_id）分组**——渠道 ID / 渠道名 /
    请求数 / Token 四类消耗 / 缓存命中 / **估算费用** / **avg_tps / max_tps / avg_ttft_ms**；
    渠道名取**该渠道最新 `synced_at` 行的 `provider_name`**（渠道在 config.json 改名后
    旧快照不回写，展示取最新）；
  - `zcode_model_stats(period)`：按 (渠道, model_id) 分组——模型排行明细，字段同上。
- 不写入 `usage_records`、不建伪账户、不动 accounts/迁移逻辑（仅 settings 加一个键 +
  新表 DDL，`_init_schema` 追加）。

### 4.3 `app/server.py`：两个端点 + 同步挂载

| 端点 | 行为 |
|---|---|
| `GET /api/zcode/quota` | 模块级 `_zcode_quota_cache`（TTL 复用 `QUOTA_CACHE_TTL=30s`），过期时后台线程刷新（照 `_ensure_quota_async` 模式：失败也写缓存占位，TTL 内不重试；本次先返回缓存值，不阻塞）。 |
| `GET /api/zcode/summary?range=today\|7d\|30d\|all` | 返回 `{db_found, last_import_at, totals, daily7, providers, models}`；`providers` 为渠道分组数组（§4.2），`models` 为模型明细；`db_found=False`（`ZCODE_DB` 文件不存在或打不开）时其余字段为空，前端显示引导；`last_import_at = MAX(synced_at)`。 |

- **导入触发（三处，共用一个 `_sync_zcode_local()`）**：
  1. `sync_usage()` 内（手动与前端自动轮询共用路径）——注意该路由在未登录 opencode 时
     直接 401 返回（server.py:591），zcode 导入挂在其**登录校验之后**的执行体内；
  2. `main.py` 启动流程后台线程先跑一次增量导入（首启即有数据）；
  3. `/api/zcode/summary` 请求路径按需增量（60s 防抖，模块级时间戳）——兜底
     **未登录 opencode 的场景**（`/api/sync` 401 后 zcode 增量仍有触发点，否则启动导入
     后再无更新）；**后台线程执行，请求立即返回库内现有数据**（首次全量导入可能耗时，
     不阻塞 HTTP 响应）。
  流程：读水位 → `collect_local_usage` → `import_zcode_usage`（定价表预加载一次 +
  费用估算 + 渠道名快照）→ 推进水位；异常捕获后仅记录 `zcode_sync_error`，不影响
  opencode/bai 账户同步。
  **并发保护**：`get_db()` 是全局单连接（`check_same_thread=False`，db.py），三个触发
  点可能与 opencode 同步线程并发写同一连接导致 commit 交错——`_sync_zcode_local`
  整体以 server.py 现有 `_sync_lock`（或同粒度独立锁）串行化，自身多触发点也不重入。

### 4.4 前端 `app/web/*`

1. **首页**（`usage-blocks` 下方）：新增「GLM Coding Plan · ZCode」区块——
   - `level` 徽章（pro→Pro / max→Max / 其他原样）+ 三窗口进度条（复用 `.ub` 样式与
     `renderUsageBlocks` 的渲染分支；MCP 行显示 `used_count/total_count` 次数；
     **`QUOTA_LABEL` 映射（app.js:190）需新增 `"MCP Monthly"` 条目**，对应新增
     `mcpMonthly` i18n 键——现有映射仅含 5h Rolling/Weekly/Monthly）；
   - 错误文案含「未找到 ZCode Coding Plan 凭证」→ 显示引导文案
     （"请在 ZCode 客户端登录 Coding Plan 后自动读取"）；其他错误显示可读信息；
   - 数据来自 dashboard 载入后并发拉取 `/api/zcode/quota`（不塞进 dashboard payload，
     避免 ZCode 未安装用户首页变慢）。
2. **统计页**：新增「ZCode 本地用量」区块（范围跟随统计页现有 range 切换）：
   - **KPI 行**：请求数 / 总 Token / **估算费用** / **平均输出速度 tok/s** / **平均首字延迟**；
   - **渠道汇总表**（核心，按用户要求）：每渠道一行——渠道徽章（友好名，回退截断 UUID）/
     请求数 / 输入(含缓存) / 输出 / 缓存命中 / **估算费用** / **平均 tok/s** / **平均 TTFT**；
   - **模型明细表**：渠道 × 模型 / 请求 / Token 构成 / 估算费用 / 平均 tok/s（可折叠或
     与渠道表 tab 切换，实现时按页面空间定）；
   - **7 日趋势**：Token + 估算费用（复用现有趋势图渲染）；**趋势窗口固定近 7 天，
     不随 range 变化**（KPI/渠道表/模型表跟随 range，趋势始终展示最近一周粒度）；
   - 区块头部注明：**"费用为按量价目估算值（订阅套餐实际不按此扣费），未收录定价的
     模型按 0 计算"**。
   - `db_found=False` 时整块显示"未检测到 ZCode 本地数据"。
3. **渠道徽章友好名**：`provider_name` 快照优先（config.json 的用户自定义名，如
   「火山方舟」「自定义中转」）；NULL 时按内置映射（`builtin:bigmodel-coding-plan` →
   "GLM Coding Plan"、`builtin:*-start-plan` → "GLM Start"）；再回退截断 UUID。
4. **i18n**：zh/en 双语补全（新键约 20 个，含"估算费用 Est. cost"、"输出速度 Output
   speed"、"首字延迟 Time to first token" 等）。

### 4.5 测试 `tests/`

| 文件 | 覆盖 |
|---|---|
| `tests/test_zcode_api.py` | 凭证选择（内嵌样例 provider map：内置顺序/回退/start-plan 排除/空白 key）、baseURL→端点推断、setting.json dataBaseDir 解析（绝对/相对/空/坏 JSON）、额度响应解析（正常/多订阅同窗口/无 nextResetTime/success=false/缺 data）、HTTP 层 mock、**费用估算**（大小写归一命中 GLM-5.3→glm-5.3、前缀剥离 meta/muse-spark→muse-spark、未收录按 0、定价表缺失按 0、公式数值与 BAI 手算一致） |
| `tests/test_zcode_sync.py` | 临时 sqlite 构造 model_usage → 首次全量导入（含 cost_raw 与 provider_name 快照）→ 二次增量（只导新增）→ 幂等（重复导入 0 新增）→ 水位推进 → 聚合查询数值正确（**totals/daily/providers/models 四层的 token/费用/avg_tps/max_tps/avg_ttft**，含秒速口径用例：有效窗口=duration−TTFT、output<10 与速率>500 的噪声行剔除、TTFT 缺失/越界样本不参与平均、**started_at 转 UTC ISO 后按 localtime 聚合的跨日归组正确**）→ db 缺失时 db_found=False 不抛异常 |

现有测试不回归（新表/新键不影响既有断言）。

### 4.6 Dedupe Ticket

- **新增 `app/zcode_api.py`**
  - Intent：ZCode 数据源客户端（本地凭证读取 + 额度接口查询 + 本地 sqlite 只读采集 + 费用估算）。
  - Queries：`grep -rn "zcode\|coding.plan\|bigmodel" app/`、`grep -n "config.json\|\.zcode" app/`、
    `grep -n "model-pricing\|cost_raw" app/`。
  - Top matches：`app/opencode_api.py`、`app/bai_api.py`、`app/commandcode_api.py`。
  - Decision：**new**（模块）+ **reuse**（定价表加载 `_load_model_pricing`、单价解析
    `_parse_million_cost`、前缀剥离 `_strip_provider_prefix` 直接从 `bai_api` import，
    避免定价逻辑两份漂移；成本公式与 BAI 保持一致，仅匹配环节加大小写归一）。
- **新增 `zcode_usage` 表 + 聚合查询（db.py 内）**
  - Intent：ZCode 本地用量镜像表（含估算费用列）与渠道/模型两层聚合。
  - Queries：`grep -n "CREATE TABLE\|def model_stats\|def totals" app/db.py`。
  - Top matches：`usage_records` 表及 model_stats/daily_stats/totals。
  - Decision：**new**（表）+ **extend**（查询风格照抄现有聚合的列语义，但不改现有函数）。
    独立表是为避免污染按 account_id 组织的多账户统计（见 §3）。
- **新增 `tests/test_zcode_api.py`、`tests/test_zcode_sync.py`**
  - Decision：**new**（现有 tests 无 zcode 覆盖；fixture 模式参照 `tests/test_db_multiuser.py`）。

## 5. 不做的事

- 不做 ZCode 多账号快照/切换（accounts.rs 那套）——本机单登录态，读 config.json 即得。
- 不做 MCP `usageDetails` 按工具拆分展示、不做额度历史快照采样（quota_history）。
- **不做项目维度统计**（用户已确认；session.directory 不导入）。
- 不做"使用记录/会话"页的 zcode 逐条明细——统计页聚合（渠道/模型/趋势/KPI）已覆盖需求
  主体，明细页留待后续需要时再加。
- 不写 ZCode 数据目录（config.json/db.sqlite 全程只读）；不做环境变量路径覆盖
  （参考实现的 ZBAR_DB 是它自己的调试机制，不搬）。

## 6. 风险

1. **接口无官方文档承诺**（`/api/monitor/usage/quota/limit` 与 model_usage 表结构均为
   逆向）→ 逐字段容错 + 失败显式报错；参考实现已稳定运行多个版本，风险可控。
2. **ZCode 升级改 schema**（model_usage 列改名/删除）→ 只读采集按列存在性容错，缺列记 0
   并继续；启动导入失败不影响主程序。
3. **db.sqlite 并发读**：ZCode 写入中（WAL）只读并发安全；busy_timeout 兜底瞬时锁；
   打不开时 `db_found=False` 静默降级，下轮同步再试。
4. **凭证是明文 apiKey**：仅内存中转发 Authorization，不落 GoGauge 库、不写日志。
5. **估算费用口径**（与 BAI 同源的固有局限）：a) 订阅套餐实际不按量扣费，估算是"若按量
   计费的花费"参考值，前端已明确标注；b) 未收录定价的模型按 0（本机 4/13，均为免费/中转
   模型）→ 低估；c) 定价表更新不追溯已导入历史行（与 BAI 先例一致）；d) reasoning 不单独
   计价（与 BAI 对 glm 系同口径）。
6. **秒速口径**（与参考实现一致）：逐行速率基于**剔除首字等待**的有效生成窗口
   （`duration − TTFT`），且过滤噪声样本（output<10 / 窗口<100ms / 速率>500 tok/s 不参与），
   数值偏"纯生成阶段速度"；TTFT 无效行（约 12%-50%）不参与对应平均。
7. **首启全量导入** 1.2 万行毫秒级；若用户 ZCode 数据量极大（>百万行），水位增量后无压力
   （仅首导一次）。

## 7. 验证标准

1. `python -m pytest tests/` 全绿（新增两个测试文件 + 现有不回归）。
2. 真实环境冒烟：本机已登录 GLM Coding Plan → 首页出现「GLM Coding Plan」区块，Pro/Max
   徽章 + 5h/Weekly/MCP 三窗口数值与 ZCode 客户端显示一致；统计页 ZCode 区块出现
   12586 行量级的聚合。
3. **渠道拆分验证**：渠道汇总表出现 GLM Coding Plan / GLM Start / 各第三方渠道（火山
   ark、tokenrhythm、b.ai 等）分列的 token 消耗、估算费用、平均 tok/s、平均 TTFT；
   各渠道行数与本机 db.sqlite 实测分布一致（6442/2099/…）。
4. **估算费用验证**：抽查 GLM-5.3 单条记录，手算 `input×in + output×out + cache×单价`
   与库中 cost_raw 一致；未收录模型（ox-alpha 等）费用为 0；GLM-5.3 与 glm-5.3（不同
   渠道同一模型）都能命中定价。
5. 增量验证：ZCode 产生新请求 → 手动/自动同步后 ZCode 区块计数增长；重复同步不重复计数。
6. 降级验证：临时改名 `~/.zcode` 目录 → 额度区块显示登录引导、统计区块显示"未检测到
   ZCode 本地数据"，主程序与 opencode/bai 账户功能不受影响。
7. 打包冒烟：`build.bat` 编译通过（无新第三方依赖，requirements 不变）。
