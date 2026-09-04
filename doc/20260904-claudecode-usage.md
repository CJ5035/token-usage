# Claude Code 本地用量接入实施文档

> 状态：**已实施**（2026-09-04 subagent-driven 执行完毕；全量 317 passed；真机冒烟 660 文件
> /15157 条记录通过，秒速 avg 159.08 / max 491.43 tok/s）
> 日期：2026-09-04
> 参照：F:\GitHubs\zai-floating-monitor（`src-tauri/src/claude.rs` + `db.rs`，Rust/Tauri，关键机制已逐条核对原文）
> 集成模式：独立数据域（同 ZCode，见 `doc/20260903-zcode-integration.md`），复用其表结构/聚合/端点/前端模式

## 1. 背景与目标

用户希望参考 zai-floating-monitor 获取 Claude Code 用量的方式，在 GoGauge 中集成 Claude Code
用量展示，维度：**总量 + 今日 + 分模型 + 分渠道 + token 秒速（tok/s）**。

需求边界（含默认假设，可调整）：

1. **展示形态**：stats 页独立本地用量区块（同 ZCode 区块形态），**不进 accounts 体系**
   （无账号/登录概念）、不参与 `/api/sync` 账号分发。
2. **总量/今日**通过区块顶部 range 药丸切换呈现（`all`=总量、`today`=今日，同 ZCode 区块交互），
   另有 7d/30d；7 日趋势图与估算费用一并展示（费用复用现有定价表，JSONL 本身无费用字段）。
3. **渠道识别（默认策略，因 JSONL 无渠道字段）**：见 §4"启用时间戳"判定。
4. **范围外**：Anthropic OAuth 订阅额度（5h/周窗口，zai-floating-monitor 的另一条链路）不做。

## 2. 调研结论（zai-floating-monitor 实现方式，已核对原文）

- **数据源**：`~/.claude/projects/<项目目录>/<会话uuid>.jsonl`，子代理在
  `<会话uuid>/subagents/<uuid>.jsonl`，`collect_session_files` 递归下钻 **5 层**收集
  `*.jsonl` 并排序（claude.rs:279-299）；目录定位支持环境变量覆盖
  （claude.rs:39-48）。不读 `~/.claude.json`。
- **行过滤**（claude.rs:594-619）：只处理 `type=="assistant"` 行；`model` 为空或
  `"<synthetic>"`（CLI 中断占位）跳过；`usage` 缺失或四项之和 ≤ 0（流式 0 值占位行）跳过；
  `timestamp` 缺失/不可解析跳过（偏移仍推进）。
- **字段**（claude.rs:180-230）：`timestamp`(ISO8601 RFC3339)、`message.id`、
  `message.model`、`message.durationMs`（serde rename，该次调用总耗时 ms，旧版 CLI 无此
  字段 → None）、`usage{input_tokens, output_tokens, cache_read_input_tokens,
  cache_creation_input_tokens}`。无 total/cost/TTFT/reasoning（thinking 计入 output），
  total = 四项之和。
- **去重**（claude.rs:621-670）：`message.id` 为全局去重键（同一 id 边流式边落盘、usage
  逐行累计，**末行=终值**；resume/continue 是 fork 语义，新会话文件复制历史且保留原 id，
  必须跨文件去重）。**id 非空且不含 `|` 才用作键**（与兜底键形态天然隔离）；无 id 的行用
  `<session_id>|<行序号>` 兜底，行序号只对通过过滤的行递增。upsert：
  `ON CONFLICT(dedupe_key) DO UPDATE SET ... WHERE excluded.computed_total_tokens >
  model_usage.computed_total_tokens`（**总量更大者胜**，打 updated_at 修订标记；
  provider/cwd 等归属列不参与覆盖，首插为准）。
- **token 秒速**（db.rs:131-187）：zai 按查询时 `output_tokens × 1000 / durationMs`
  计算（无 TTFT 列时生成窗口退化为 duration_ms）。噪声过滤：输出 ≥ 10 tokens 且窗口
  ≥ 100 ms 且速度 ≤ 500 tok/s 才计入；聚合 AVG + MAX，无可信样本为 NULL。
  **真机核实（2026-09-04，本机 660 文件 / 26742 条 assistant 行）：`durationMs` 字段
  0 命中**（当前 CLI 版本不写该字段）→ zai 口径在本机永远无速度。故本集成改为
  **导入时计算并落库 `speed_tps`**，计算优先级：
  ① `durationMs` 存在 → `output × 1000 / durationMs`（zai 口径，向前兼容）；
  ② 缺失 → 同 `message.id` 多行的时间戳差估算（流式落盘 usage 逐行累计产生的副本行
  天然构成窗口）：`Δoutput × 1000 / Δt`（Δt = 该 id 末行 − 首行 timestamp，Δoutput =
  末行 − 首行 output）；
  ③ 单行无 durationMs → NULL。
  噪声过滤同上（窗口 ≥100ms、输出 ≥10 tok、tps ≤500）。
- **增量**（claude.rs:149-153、484-578、673-680）：派生自有 SQLite 库 +
  `file_progress(path→offset,size)` **字节偏移**续读；进度只推进到**最后一条完整行**；
  文件变短（被重写）→ 从头重解析，靠 UNIQUE 去重键幂等；`import_incremental` 5 秒节流
  （失败也计入节流窗口防重试风暴）；每文件一个事务。
- **渠道**：**没有**。provider 硬编码 `'claude'`，无法区分官方/中转（claude.rs:17-20、642）。
- **费用**：本地定价表计算（每百万 token 单价；精确匹配 → 小写归一兜底）。

## 3. 方案选型

| 决策点 | 备选 | 结论 |
|---|---|---|
| 集成模式 | 账户体系 / 独立数据域 | **独立数据域**（同 ZCode）：无登录、不进 `/api/sync` 分发、独立端点与前端区块 |
| 存储 | 每次实时全量扫描聚合 + TTL / 镜像表 + 字节偏移增量 | **镜像表**：`~/.claude/projects` 量大（数百 MB 级），字节偏移续读是被验证的方案（zai-floating-monitor 同款） |
| 表结构/聚合口径 | 自创新列名 / 对齐 zcode_usage | **对齐 zcode**：`started_at` UTC ISO、查询时 SQL 算速度、`period` 字符串过滤，前端渲染函数可近乎复制 |
| 渠道识别 | 不分 / 仅模型名启发 / 启发+当前配置 | **启用时间戳判定**（§4） |

### Dedupe Ticket

- **Intent signature**: 新增 Claude Code 本地 JSONL 用量采集模块（扫描/解析/去重/增量续读/渠道判定），并按 ZCode 独立数据域模式扩展镜像表、聚合、端点与前端区块。
- **Queries**: "本地数据源采集/用量镜像表"（zcode 集成）、"本地会话日志解析"、"claude 相关代码"、DSH 同构方案文档。
- **Top matches**: `app/zcode_api.py`（本地数据源采集范式）、`app/db.py:190,1408-1714`（zcode 镜像表与聚合）、`app/server.py:755-979`（防抖/端点/编排）、`doc/20260904-dsh-usage.md`（同构需求的既有方案）。
- **Decision**: **new + extend** —— 新建 `app/claudecode_api.py`（数据源格式为 JSONL 文件流 + 字节偏移增量，与 zcode 的 sqlite 表 + 时间水位机制不同，无法复用其实现）；`db.py`/`server.py`/前端为纯扩展点，照 zcode 模式追加。
- **Rationale**: 已检索确认仓库内无任何 claude 相关代码（app.js 全文 0 处 claude、无 claude 图标资产）；本文件级去重/续读机制在仓库内无先例，必须新模块承载；其余全部复用现成模式。

## 4. 渠道识别（关键设计）

JSONL 记录内**没有渠道（baseURL）字段**，只能近似归属。以**集成启用时刻**为分界：

- settings payload 新增白名单外键 `claudecode_enabled_at`（epoch ms；**首次导入启动时写入
  一次**，读写照 `get_zcode_watermark`/`save_zcode_watermark` 的 `_raw_payload` 模式，
  db.py:1520-1534）。
- 逐条记录判定（导入组装行时执行）：
  - 记录 `timestamp` ≥ `claudecode_enabled_at` → 读**当前** `~/.claude/settings.json` 的
    `env.ANTHROPIC_BASE_URL`（每次导入批量解析一次）：缺失或 host 为 `api.anthropic.com`
    → `官方`；否则取 hostname（cc-switch 切渠道会改写该文件，自动同步间隔足够短时归属
    基本准确）。
  - 记录 `timestamp` < `claudecode_enabled_at`（历史数据）→ **模型名启发式**：
    `claude-*` → `官方`；其他 → 模型名首段（`glm-4.6` → `glm`）。
- upsert"大者胜"只更新 token/duration/started_at/model/cost 列，**channel 首插为准**。

已知限制（记录于此，不在前端展示）：启用前的历史只能启发式标注；`claude-*` 模型走中转的
历史会被标为"官方"。

## 5. 数据层（`app/db.py`）

`_init_schema`（db.py:108）新增两张表（列名/口径对齐 zcode_usage，db.py:190-207）：

```sql
CREATE TABLE IF NOT EXISTS claudecode_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedupe_key TEXT NOT NULL UNIQUE,    -- message.id 全局；无 id/含'|' → "<session_id>|<行序号>"
  session_id TEXT,                    -- 会话 uuid（主会话=文件名 stem；子代理=父目录名）
  project_path TEXT,                  -- 行内顶层 cwd
  model TEXT,
  channel TEXT,                       -- 渠道标记（§4 判定）
  started_at TEXT NOT NULL,           -- UTC ISO（Z 后缀，同 zcode_usage；聚合用 'localtime'）
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens INTEGER NOT NULL DEFAULT 0,   -- ← cache_creation_input_tokens
  total_tokens INTEGER NOT NULL DEFAULT 0,         -- 四项之和
  duration_ms REAL,                   -- 旧版 CLI 行无此字段 → NULL
  speed_tps REAL,                     -- 导入时计算（§2 优先级 ①②③），查询侧仅 AVG/MAX
  cost_raw INTEGER NOT NULL DEFAULT 0,  -- 导入时估算（1e-8 USD，同 zcode 口径）
  file_path TEXT,
  updated_at TEXT,                    -- "总量大者胜"修订标记
  synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cc_time ON claudecode_usage(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_cc_channel ON claudecode_usage(channel);
CREATE INDEX IF NOT EXISTS idx_cc_model ON claudecode_usage(model);

CREATE TABLE IF NOT EXISTS claude_file_progress (
  path TEXT PRIMARY KEY,
  offset INTEGER NOT NULL DEFAULT 0,  -- 已消费字节偏移（最后一条完整行末尾）
  size INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT
);
```

新增 SQL 片段与聚合函数（全部照 zcode 模式，db.py:1408-1714）：

- `_CC_SPEED_COLS`：`AVG(speed_tps)/MAX(speed_tps)`（speed_tps 已在导入时按 §2 口径
  算好落库，查询侧不再 SQL 现算；无可信样本为 NULL，由 Python 侧转 None）。
- `_cc_period_where(period)`：照 `_zcode_period_where`（db.py:1541-1556），支持
  `today`/`all`/`Nd`（默认 30d）。
- `claudecode_totals(period="30d")` / `claudecode_channel_stats(period)`（GROUP BY channel）/
  `claudecode_model_stats(period)`（GROUP BY model）/ `claudecode_daily(days=7)`
  （本地日归组，照 `zcode_daily` db.py:1597）。行字段名与 zcode 完全一致：
  `request_count/total_input_tokens/uncached_input_tokens/cache_hit_tokens/
  cache_write_tokens/total_output_tokens/total_tokens/total_cost_usd`（+ 速度聚合的
  `avg_tps/max_tps`，无可信样本 → None）。
- `import_claudecode_usage(rows, pricing_models)`：行 dict 已含 channel（§4 判定在采集层
  做）与 `speed_tps`（§2 优先级 ①②③ 由采集层算好，缺省 None），
  费用延迟导入 `zcode_api.estimate_cost_raw`（同 `import_zcode_usage` db.py:1483 的延迟
  导入理由：db 不依赖采集层）。upsert 用 `executemany` +
  `ON CONFLICT(dedupe_key) DO UPDATE SET started_at/model/input/output/cache_read/
  cache_write/total/duration_ms/cost_raw/speed_tps = excluded...
  WHERE excluded.total_tokens > claudecode_usage.total_tokens`（修订行同步重算 cost_raw；
  channel/project/session/file 首插为准。实现注意：`updated_at` 用 DO UPDATE 的
  **尾参**绑定本次导入时刻，不写 `updated_at = excluded.updated_at`——payload 首插时
  该列为 None，照抄会把修订标记刷成 NULL；Task 1 已按尾参实现并有三分支测试锁定）。
- `get_claudecode_enabled_at()` / `save_claudecode_enabled_at(ms)`（settings 白名单
  外键，照水位读写模式）、`get_claude_file_progress_all() -> dict[str, tuple[int, int]]`
  （path → (offset, size)，一次载入供采集编排）、`save_claude_file_progress(path,
  offset, size)`、`claudecode_last_import_at()`（`MAX(synced_at)`，供端点）。

## 6. 采集模块（新增 `app/claudecode_api.py`）

职责边界：解析 `~/.claude/projects` JSONL → 产出待导入行 dict；不 import server/main，
不直接写 GoGauge 库（同 zcode_api 与 db 的关系）。

- 常量：`CLAUDE_DIR = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")`
  （CLAUDE_CONFIG_DIR 为 Claude Code 官方环境变量；测试 monkeypatch 模块常量）、
  `CLAUDE_PROJECTS = CLAUDE_DIR / "projects"`、`CLAUDE_SETTINGS = CLAUDE_DIR / "settings.json"`。
- `scan_session_files() -> list[Path]`：递归下钻 5 层收集 `*.jsonl`，排序保证导入顺序稳定
  （照 `collect_session_files`；不用无界 `**` glob）。
- `parse_session_file(path, start_offset) -> (rows, new_offset)`：二进制 seek 到偏移只读
  新增字节，按行 split；半行不消费、偏移只推进到最后一条完整行末尾；逐行
  `json.loads`（失败跳过该行）+ §2 行过滤；utf-8 解码 `errors="replace"`（脏字节行
  跳过）；`timestamp` 用
  `datetime.fromisoformat` 解析（Python 3.12 支持 Z 后缀）→ epoch ms（供渠道判定）
  与 UTC ISO（落库）。产出行 dict：`dedupe_key/session_id/project_path/model/
  started_at/tokens 四项/total/duration_ms/speed_tps/file_path`（**不含 channel**——
  `parse_session_file` 保持纯解析，channel 由 `import_incremental` 组装 FileBatch 前
  按 `resolve_channel(model, ts_ms, enabled_ts_ms, base_url)` 统一盖章。`speed_tps`
  在 parse 内按 §2 优先级计算：同文件内按 message.id 分组，durationMs 优先，否则
  Δoutput/Δt（该 id 末行−首行），窗口 ≥100ms 且输出 ≥10 tok 且 ≤500 tok/s 才有效，
  单行无 durationMs → None；值附着在该 id 的末行（即 upsert 幸存行））。`session_id`：主会话取文件名
  stem；子代理取所属会话目录名（路径形如 `<项目>/<会话uuid>/subagents/<x>.jsonl` 时取
  `<会话uuid>`）。
- `resolve_channel(model, record_ts_ms, enabled_ts_ms, base_url) -> str`：§4 两分支；
  settings.json 缺失/非法 → base_url 视为 None（`官方`/启发式兜底）。
- `read_base_url() -> Optional[str]`：读 `CLAUDE_SETTINGS` 的
  `env.ANTHROPIC_BASE_URL`，提取 hostname；`api.anthropic.com` → 返回 None（官方）。
- `compute_total(usage) -> int`：四项之和。
- `import_incremental(enabled_ts_ms, progress, force=False) -> list[FileBatch]`：
  采集编排（`progress` 为 server 传入的 `path → (offset, size)` 字典；模块不 import
  db，只读外部 JSONL，保持 zcode_api 式分层）。模块级 5 秒节流（失败也计入
  窗口；模块变量可被测试 monkeypatch 重置）；遍历 `scan_session_files()`：查 `progress`
  的 offset/size——`size` 未变小 → 续读，变小 → offset 重置 0 全量重读（幂等靠去重键）；
  `read_base_url()` 每轮读一次；产出按文件分批的 `FileBatch{path, rows, new_offset,
  size}` 列表。单文件解析异常跳过不中断整体，编排级异常吞掉静默降级（同 zcode 采集口径）。

## 7. 服务层（`app/server.py` / `app/main.py`）

- 端点：`GET /api/claudecode/summary?range=today|7d|30d|all`（照 `/api/zcode/summary`
  server.py:974-979 与 `_zcode_summary_payload` server.py:825-862 的纯函数组装）：

  ```json
  {
    "db_found": true, "last_import_at": "...", "error": null, "range": "7d",
    "totals":   { "request_count": 0, "total_input_tokens": 0, "uncached_input_tokens": 0,
                  "cache_hit_tokens": 0, "cache_write_tokens": 0, "total_output_tokens": 0,
                  "total_tokens": 0, "total_cost_usd": 0.0, "avg_tps": null, "max_tps": null },
    "daily7":   [ { "date": "2026-09-04", "...同 totals 但无速度" } ],
    "channels": [ { "channel": "官方", "...同 totals" } ],
    "models":   [ { "model": "claude-sonnet-4-5", "...同 totals" } ]
  }
  ```

  口径：`totals`/`channels`/`models` 跟随 range（range→period 映射照 zcode：
  today/7d/all，其余 30d）；`daily7` 固定 7 天（同 zcode）。**总量 = range `all`，
  今日 = range `today`**，前端药丸切换（同 ZCode 区块）。`db_found` =
  `CLAUDE_PROJECTS.is_dir()`；目录不存在 → 返回 `db_found:false` + 各空字段（前端空态，
  同 zcode server.py:838-849）。
- 触发点（照 ZCode 三触发，独立 `_cc_import_lock`，锁顺序恒定 `_sync_lock → _cc_import_lock`）：
  1. 每轮 `sync_usage` 末尾 piggyback（server.py:624-628 旁，`with _cc_import_lock`）；
  2. 启动后台线程（main.py:466 zcode 启动线程旁，加一行
     `threading.Thread(target=server.claude_import_async, ...)`）；
  3. `/api/claudecode/summary` 请求防抖 60 s 触发（照 `_maybe_trigger_zcode_import`
     server.py:797-805 的模块级时间戳防抖，请求不等待导入）。
- `claude_import_async()` / `_sync_claude_local()`：照 `zcode_import_async`/
  `_sync_zcode_local`（server.py:686-701）：拿 `_cc_import_lock` →
  `db.get_claudecode_enabled_at()`（0 则取当前时间写入 = 启用时刻；锁内执行无竞态）→
  `db.get_claude_file_progress_all()` 取进度快照 →
  `claudecode_api.import_incremental(enabled_at, progress)` 拿按文件分批 → 逐批
  `db.import_claudecode_usage(batch.rows, _load_model_pricing())` +
  `db.save_claude_file_progress(batch.path, batch.new_offset, batch.size)`
  （行落库与 progress 两步提交，无跨表事务；两步之间崩溃则下次重读该文件，
  去重键幂等兜底）；错误记 `_cc_sync_error` 文案供 summary 返回。
  命名约定：server 侧公开入口 `claude_*`、内部状态 `_cc_*`（同 zcode 的
  `zcode_import_async`/`_zcode_*` 惯例）。

## 8. 前端（`app/web/index.html` / `app.js` / `style.css` / `icons/`）

- `index.html`：`#page-stats` 的 zcode-stats 区块（:106-115）旁新增 claudecode 区块
  （结构复制：标题 + 费用 hint + `db_found:false` 空态 + KPI 行 + 两张表 + 趋势图 canvas）。
  KPI 行 5 项：总 tokens、输出 tokens、请求数、平均秒速、累计费用（跟随 range）。
- `app.js`：
  - `loadClaudecodeSummary`/`renderClaudecodeSummary`/`chartClaudecodeTrend`：
    近乎复制 `loadZcodeSummary`(:637)/`renderZcodeSummary`(:672)/`chartZcodeTrend`(:734)，
    挂载点同（switchPage stats 分支 :427、汇率刷新 :417）。
  - 渠道名直接渲染 `channel` 字段（导入时已落中文名/hostname，无需前端映射）。
  - **`modelIcon`（app.js:1016-1027）现有 map 无 `claude` 键，claude-* 模型会错误回退
    deepseek 图标** → map 增加 `claude: "claude"`。
- `icons/claude.svg`：**新增资产**（16×16 简约 Claude 标识，深浅色同用）。
- `style.css`：复用 `.card/.kpi-row/.tbl/.chart-box/.zcode-missing` 等现有类，尽量零新增。
- i18n：`I18N.zh`/`I18N.en` 同步补区块标题、空态、KPI 标签、费用 hint 等文案。

## 9. 测试（pytest，全部临时目录 + monkeypatch，不读本机真实文件）

fixture 照 `tests/test_zcode_sync.py:20-33`：`tmp_db` 重定向 `db.data_dir` 并
`db._DB = None`；采集层 monkeypatch `claudecode_api.CLAUDE_DIR`（或 CLAUDE_PROJECTS/
CLAUDE_SETTINGS）指向临时目录；节流用 monkeypatch 重置模块变量。

- `tests/test_claudecode_api.py`：文件发现（subagents/深度 5/排序稳定）、行过滤
  （synthetic/0 值/无 timestamp/非法 JSON 行）、dedupe key（有 id 全局；id 含 `|` 或
  无 id → session 序号键）、`compute_total`、秒速（durationMs 路径 / Δoutput÷Δt 回退 /
  单行 NULL / 窗口<100ms、输出<10、tps>500 排除 / 值附着末行）、
  `resolve_channel` 两分支
  （≥/＜ enabled_at；settings.json 存在/缺失/非法/api.anthropic.com）、
  增量续读只消费新增字节（含半行悬挂）、文件变短重扫、5 秒节流与 force。
- `tests/test_claudecode_sync.py`：建表迁移、导入幂等（重复导入不重复计）、
  "总量大者胜"修订（token/cost/speed_tps/updated_at 更新、channel 首插不变）、progress 推进/
  回退、enabled_at 首次写入、聚合函数（totals/channels/models/daily、
  存储列 speed_tps 的 AVG/MAX 与 NULL 忽略、period 过滤 today/all/Nd）、费用估算接入。
- `tests/test_claudecode_server.py`：端点返回形状、`db_found:false` 空态、
  summary 防抖触发（60s 内不重复）、`_sync_claude_local` 异常吞掉不外抛、
  与 zcode 端点互不干扰。

## 10. 实施步骤

1. `app/db.py`：两张表 + SQL 片段 + 导入/聚合/enabled_at/progress 函数
   → 验证：`python -m pytest tests/test_claudecode_sync.py` 全绿
2. `app/claudecode_api.py`：扫描/解析/去重/增量/渠道/编排
   → 验证：`python -m pytest tests/test_claudecode_api.py` 全绿
3. `app/server.py` + `app/main.py`：端点 + 三触发点
   → 验证：`python -m pytest tests/test_claudecode_server.py` 全绿
4. 前端四件（index.html/app.js/style.css/icons/claude.svg）+ i18n
   → 验证：`python -m pytest` 全量回归 + 真机跑 `~/.claude` 核对总量/今日/渠道归属
5. 全量回归：`python -m pytest`（解释器 `python`，禁 `py`/裸 `pip`）

## 11. 已知限制与后续可选项

- 渠道归属为近似策略（§4），启用前的历史无法精确回溯。
- OAuth 订阅额度（5h/周窗口百分比、重置时间）本次不做，需要时另立文档。
- 无 id 的极老旧行去重键含行序号，文件被截断重写的极端场景可能残留旧记录
  （zai-floating-monitor 同等限制）；修订行以"总量大者胜"兜底。
- 分渠道归属依赖导入时刻的 settings.json 快照，离线期间（程序未运行时）切换渠道的
  新增会话可能误标，后续可结合模型名交叉校验（不在本期）。
- (offset,size) 增量判定的固有盲区：文件先变短、后重新长过旧 size（如重写为 50 字节后又
  追加到 120 字节）会被判"未变短"而从旧 offset 续读，中间字节永久跳过——zai 同款方案
  同等限制，概率极低，接受。
