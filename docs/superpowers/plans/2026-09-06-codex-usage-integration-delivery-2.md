# Codex 用量统计集成 · 交付二 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal（交付二）:** 在使用记录页实现统一来源筛选，把 `usage_records`、`zcode_usage`、`claudecode_usage`、`codex_usage` 四张持久化表归一为同一查询（T6），并完成交付二范围的功能门禁、截图与回归验证。

**前置条件:** 交付一已完成并签入（T1–T5、T7 与交付一验证），即：`codex_usage`/`codex_file_progress`/`codex_import_state` 表与幂等导入已落地，`codex_records_page`/`codex_session_stats_page` 存储层查询已实现并通过 DB 级测试，`/api/codex/summary` 与公共报表已可用，前端统计页/首页/文案已上线。交付一计划见 [2026-09-06-codex-usage-integration-delivery-1.md](2026-09-06-codex-usage-integration-delivery-1.md)。交付一阶段记录页不含 Codex 明细属已声明的已知边界；本交付消除该边界，T6 不得因拆分而取消。

**Architecture:** 在交付一的存储层之上新增统一查询层：四段只含常量的 SQL projection 归一四表字段，绑定参数筛选后统一 COUNT/排序/分页；server 按 `source` 白名单分派（省略时保持现状行为）；前端沿用现有记录/会话表格与分页，新增一个共享来源下拉。

**Tech Stack:** Python 3.12+、标准库 SQLite、原生 JavaScript、pytest 8+、Node.js（JS 验证）、PyInstaller（回归构建）。

**Spec:** [Codex 用量统计需求文档](../../../doc/需求文档/20260906-Codex用量统计需求文档.md)（§5.3 记录页、§6 统一记录/会话契约、§7 数据口径）

**状态:** 本计划由原总体计划按需求文档交付拆分裁决拆分而来（2026-09-07）。任务编号沿用需求文档 T1–T8 分期：本交付含 T6 及交付二范围的 T8 验证。本文代码块是待实施内容，评审代码块不等于功能测试通过；不得据此宣称已实现。

## Global Constraints

- 所有 Codex 总量使用 `SUM(total_tokens)`；缓存读、推理只作为子项，不二次相加。其他来源继续遵循各自既有口径，统一层只在各来源分别计算后合并。
- NULL 不是 0：`cost_available=false` 时 `cost_usd` 必须为 NULL，前端显示 `—`，不得渲染为 0；速度缺失样本同理。
- 省略 `source` 参数时保持现状行为（活跃账号 `usage_records`、原字段名与筛选语义）以向后兼容；显式 `source=all|opencode|bai|commandcode|zcode|claudecode|codex` 走统一查询；非法 source 返回 400。
- DSH 没有持久化明细表，不纳入 `source` 白名单；首页“仅今日 DSH”行为不受影响。
- 会话聚合按 `(source, account_id, session_id)` 分组，跨来源相同 session_id 不得合并；缺 session_id 回退 `(source, account_id, key_id)`，再缺回退到按来源和账号的“未归属”分组；Codex 的 `account_id` 固定 NULL 但仍按 `source` 隔离。
- 排序键固定 `started_at DESC, source ASC, source_record_id ASC`；后台导入导致数据变化时，前端刷新回到第 1 页，不承诺 offset 分页跨导入快照绝对稳定。
- Codex 导入与统一查询独立于远程登录状态；T6 路由不得引入登录依赖。
- 不修改 Codex 原始 JSONL 文件；本交付不改动采集器与镜像表结构。
- 当前工作区是脏工作区，执行前重新运行 `rtk proxy git status --short`，保留其他任务变更。
- 命令以 `rtk proxy` 运行；Python 检查使用 `python -m pytest`。PowerShell 不用 `&&` 串接提交。
- 本次授权仅为审查/修改计划。实施、提交均未执行；下列提交建议只用于后续获授权的实施阶段。

## 基线与事实修正

基线定位以符号为准，行号会随其他任务改变。先使用 CodeGraph；当前索引易命中 Chart.js 压缩文件时，再对具体源码定位，禁止以搜索结果代替阅读。

| 已核对来源 | 事实及本计划的处理 |
|---|---|
| 交付一 T2 | `codex_records_page`/`codex_session_stats_page` 已实现并通过 DB 级测试；统一层只做组合与分派，不重写 per-source 查询 |
| `app/db.py::usage_records_page/session_stats_page` | 均无 `source` 参数，只查活跃账号 `usage_records`；cache_write 展示为 `cache_write_5m_tokens + cache_write_1h_tokens` |
| `app/server.py` 两条 usage 路由 | 现有 server 层用 `db.get_key_names()` 做 `key_name` enrichment；会话空 session 按 `key_id` 分组、前端显示“未归属”的先例保留 |
| `zcode_usage`/`claudecode_usage` 表结构 | ZCode 无 `speed_tps` 列（查询侧由 `output_tokens/duration_ms` 现算）、无 `file_path`；Claude Code 有 `speed_tps`/`duration_ms`/`file_path` 列；统一 projection 按表分别映射 |
| 需求 §5.3/§6 | 统一记录/会话固定字段、`source_record_id` 命名空间（远程 `<source>:<account_id>:<native_id>`，本地 `<source>:<native_id>`）、固定排序键与分页快照语义 |
| 交付一 T8 | `scripts/serve_codex_fixture.py` 与 `scripts/check_codex_ui.cjs` 已存在；本交付扩展二者，不新建第二套 fixture |
| 交付一 T2 实况（2026-09-08 复核） | `codex_records_page(page,page_size,model,period)`/`codex_session_stats_page(page,page_size,period)` 已存在并输出统一形状投影（`'codex' AS source`、`source_record_id`、account/key/cost 置 NULL），但时间参数名为 `period`（自然日窗口，走 `_report_range_sql`）而非 `days`；统一层对接时按 T6 Step 3“保留 days 旧含义”处理，不暗改语义 |
| 20260907 并行改动实况 | ①claudecode 双源合并已落地：`claudecode_usage` 无新增列，proxy 差集行以 `file_path="cc-switch:proxy"` 溯源、`channel` 盖章、speed/duration 为 NULL，本交付投影映射不受影响（proxy 行 speed 显示 `—`）；②渠道明细自澄清已执行（`renderChannelTable(rows, summary)`、`dataSince="数据起点"`、`unusedChannelsHint`），与本交付无文件级行冲突；③`check_codex_ui.cjs` 已扩至约 323 行（canvas/主题/route 拦截/乱序丢弃等），本交付只替换 records 区块的交付一边界断言（现约 L96-100），不碰其余断言 |

## 文件与依赖

| 任务 | 新增 | 修改/复核 |
|---|---|---|
| T6 记录/会话 | 无 | `app/db.py`、`app/server.py`、三个 web 文件、`tests/test_codex_server.py`, `tests/test_db_multiuser.py` |
| T8 交付二验证 | 无（复用并扩展交付一脚本） | `scripts/serve_codex_fixture.py`、`scripts/check_codex_ui.cjs`、`tests/test_db_credential_semantics.py` 复核、专项与回归 |

顺序 T6 → T8。T6 完成前记录页维持现状行为。执行时使用 iterative-plan-review，每项完成后检查 diff、测试结果与需求映射，再勾选本项；代码审查发现实质问题则修正后继续。

## 固定数据契约（统一记录/会话）

统一记录响应固定字段：`source`、`account_id`、`source_record_id`、`started_at`、`model`、`provider_id`、`session_id`、`input_tokens`、`output_tokens`、`reasoning_tokens`、`cache_read_tokens`、`cache_write_tokens`、`total_tokens`、`duration_ms`、`speed_tps`、`speed_source`、`cost_usd`、`cost_available`、`key_name`。

- `source_record_id` 命名空间：远程来源 `<source>:<account_id>:<native_id>`（`native_id` 为 `usage_records.usg_id`），本地来源 `<source>:<native_id>`；Codex 记录 ID 为 `codex:<session_id>:<response_id>` 或 `codex:<session_id>:<event_seq>`（即 `codex_usage.id`）。
- 远程 `created_at` 映射为 `started_at`；`usage_records.cache_write_5m_tokens + cache_write_1h_tokens` 映射为 `cache_write_tokens`；ZCode/Claude Code 的既有字段按各自镜像表映射；Codex 的 `account_id`、`key_name`、`cost_usd` 为 NULL，`provider_id` 固定为 `codex`，`cost_available=false`。
- 统一会话响应固定字段：`source`、`account_id`、`group_id`、`session_id`、`key_name`、`request_count`、`total_tokens`、`total_input_tokens`、`uncached_input_tokens`、`total_output_tokens`、`total_reasoning_tokens`、`cache_hit_tokens`、`cache_write_tokens`、`avg_tps`、`cost_usd`、`cost_available`、`last_at`。`group_id` 是分页和分组的内部稳定键，展示用 `session_id` 缺失时显示“未归属”。
- 费用 SUM 忽略 NULL 但没有已知值时返回 NULL；混合会话加 `cost_partial`；平均速度只对有效行计算，不把缺失补 0。
- 排序与分页：`ORDER BY started_at DESC, source ASC, source_record_id ASC`，LIMIT/OFFSET 在 SQL 最后执行；模型下拉在分页前 distinct。

### Task 6: 来源筛选、明细和会话分页

**Files:** Modify db 的分页区、server 的 usage 路由、三个 web 文件、`tests/test_codex_server.py`, `tests/test_db_multiuser.py`。

**Interfaces:**

- `unified_records_page(source: str,page: int=1,page_size: int=20,model: str|None=None,days: int|None=None) -> tuple[list[dict],int]`
- `unified_sessions_page(source: str,page: int=1,page_size: int=10,model: str|None=None,days: int|None=None) -> tuple[list[dict],int]`
- `unified_models(source: str,days: int|None=None) -> list[str]`
- 两个 usage 路由 source 参数未提供：原函数原返回行为；显式 all/opencode/bai/commandcode/zcode/claudecode/codex 使用统一 SQL，非法 source=400，DSH 不在明细来源。
- 一个共享来源下拉 `rec-source-filter` 控制上下两表，模型筛选同步应用两表；默认选中“全部”并显式发送 `source=all`（需求 §5.3），不做“记住上次选择”的持久化；显式来源可跨该来源账号，all 跨所有账号；省略 `source` 的兼容行为仅保留给 API 旧调用方与既有测试。

- [ ] **Step 1: 测试真正的新接口，而非 T2 已完成的专属查询。**

以下加入 test_codex_server.py，复用交付一 T3 的 api_call。第三个测试加入 test_db_multiuser.py 并复用 conftest。

```python
def test_unified_route_not_active_account(tmp_codex_db, codex_row, monkeypatch, api_call):
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    db.import_codex_usage([codex_row()])
    missing = api_call("/api/usage/records")
    assert missing["data"]["total"] == 0
    explicit = api_call("/api/usage/records?source=codex")
    assert explicit["data"]["total"] == 1
    row = explicit["data"]["records"][0]
    assert row["source"] == "codex" and row["key_name"] is None
    assert row["total_tokens"] == 130 and row["cost_usd"] is None
    assert api_call("/api/usage/records?source=invalid")["status"] == 400

def test_unified_paging_and_sessions(tmp_codex_db, codex_row, monkeypatch, api_call):
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    db.import_codex_usage([codex_row("s:" + str(i)) for i in range(1, 10)])
    a = api_call("/api/usage/records?source=all&page=1&page_size=7")["data"]
    b = api_call("/api/usage/records?source=all&page=2&page_size=7")["data"]
    assert a["total"] == b["total"] == 9
    assert len({r["source_record_id"] for r in a["records"] + b["records"]}) == 9
    sessions = api_call("/api/usage/sessions?source=codex")["data"]
    assert sessions["total"] == 1 and sessions["records"][0]["total_tokens"] == 1170

def test_codex_survives_account_lifecycle(tmp_codex_db, codex_row):
    db.import_codex_usage([codex_row()])
    aid = db.add_account("t", "w")
    db.clear_account()
    db.delete_account(aid)
    assert db.codex_totals("all")["total_tokens"] == 130
```

- [ ] **Step 2: 红灯。**

`rtk proxy python -m pytest tests/test_codex_server.py -q`：缺 source分派/统一分页，交付一 summary/report 用例仍绿。

- [ ] **Step 3: SQL 归一化、排序与会话隔离。**

定义只含常量的四段 projection，输出一致列序，不读取所有行后 Python 排序：
```text
source, account_id, source_record_id, started_at, model, provider_id, session_id, key_id,
input_tokens, output_tokens, reasoning_tokens, cache_read_tokens,
cache_write_tokens, total_tokens, duration_ms, speed_tps, speed_source,
cost_usd, cost_available, request_count_exact
```

| 表 | 字段映射 |
|---|---|
| usage_records r JOIN accounts a | `source=a.source`、`account_id=r.account_id`、`source_record_id=<source>:<account_id>:<native_id>`（`native_id` 为 `r.usg_id`）、`started_at=r.created_at`、`provider_id=r.provider`；cache_write=5m+1h；其余原字段；`total_tokens=input_tokens+output_tokens`（`usage_records` 无 total 列，与 Codex 缺总量回退口径一致，含缓存/推理不再另加）；duration/speed/speed_source=NULL；cost_available=true |
| zcode_usage z | `source_record_id=zcode:<z.id>`、`started_at=z.started_at`、`model=z.model_id`、`provider_id=provider_name` 优先否则 `provider_id`；input 保持原已含缓存，cache_write 保留；total=z.total_tokens；duration/speed/speed_source 沿用既有有效字段（zcode 无 speed_tps 列，按既有查询侧公式由 output_tokens/duration_ms 现算）；cost=z.cost_raw/1e8、cost_available=true |
| claudecode_usage c | `source_record_id=claudecode:<c.id>`、`started_at=c.started_at`、`model=c.model`、`provider_id=c.channel`；reasoning=0；total=c.total_tokens；duration=c.duration_ms、speed=c.speed_tps、speed_source=duration（有值时）；cost=c.cost_raw/1e8、cost_available=true |
| codex_usage x | `source_record_id=x.id`、`started_at=x.started_at`、`provider_id=x.provider_id`；account/key NULL；total=x.total_tokens、duration/speed/speed_source 按记录保留；cost NULL、`cost_available=false`、request_count_exact 按事件模式保留 |

所有来源 ID 在对外 `source_record_id` 加 source 前缀，避免跨表同 id；session 以 (source,account_id,原session_id) 分组，空会话按该来源旧 key_id 规则，无 key 时用记录 ID，防止所有本地无会话混为一组。显示 session_id 保留原值，另回 group_id。CommandCode 只取已有 usage_records 明细，不把 charts_buckets 当请求，保留其历史明细范围提示。会话聚合的 `uncached_input_tokens` 统一按 `MAX(input_tokens-cache_read_tokens,0)`、`cache_hit_tokens` 按 `cache_read_tokens` 计算（与 Codex 聚合及现有 hit_rate 口径一致）。

对 projection 合并的 CTE 使用绑定参数筛选 source/model/time，然后统一 COUNT 和 `ORDER BY started_at DESC, source ASC, source_record_id ASC LIMIT ? OFFSET ?`。sessions 在 CTE 上按 `(source,account_id,session_id)` 生成 `group_id` 后分组 SUM/COUNT，再用同过滤计算总组数；模型下拉在分页前 distinct，不能只有本页模型。保留默认 days 的旧含义与上限，不对所有来源暗改成 spec自然日；Codex period 专属汇总仍用自然日。

费用 SUM 忽略 NULL但没有已知值时返回NULL，混合会话加 cost_partial；计算平均速度只用有效行，不把缺失补0。legacy source=None 不添加全局过滤或修改字段。

- [ ] **Step 4: 接口和前端消费。**

server 只对白名单来源调用上述统一函数；对 Codex key_name保留NULL，不再用 key_names.get 覆盖；models/filter返回相同 source/model/days。`source` 为 `codex` 或 `all` 的统一路由在查询前调用 `_maybe_trigger_codex_import()`（带节流与单飞、不等待扫描完成，需求 §6：统一记录/会话接口属触发点；当前 records/sessions 路由没有该触发点，需新增——T6 测试已 stub 此函数即依据于此）；专属其他来源查询不触发。
示意路由分派（在两条 GET 分支分别落地）：

```python
source = query.get("source", [None])[0]
if source is not None and source not in {
        "all", "opencode", "bai", "commandcode", "zcode", "claudecode", "codex"}:
    _json_response(handler, {"error": "invalid source"}, 400)
    return
if source is None:
    rows, total = db.usage_records_page(page, page_size, model, days)
else:
    rows, total = db.unified_records_page(source, page, page_size, model, days)
```

前端 state.records.source 默认 `"all"`（“全部”），loadRecords/loadSessions 显式携带 `source=all`；选择来源清空不在新来源的模型，两个 page 重置1；携同过滤，保留各自seq。新增来源、渠道、total、reasoning、缓存写、speed列（需求 §5.3：Codex 行显示时间、模型、渠道、输入、输出、缓存、reasoning、总 token、tok/s），Codex未知费用/Key用NULL显示；colspan、补齐7行占位列数、错误行一并按实际表头计算。两表放 overflow-x:auto 容器，窄窗优先保证可横向检查，不能缩到文字重叠。切换账号不改变来源选择；“全部”视图包含所有持久化来源，不随活跃账号变化。后台导入使数据集变化时刷新回第 1 页。

- [ ] **Step 5: 全来源、跨账号与参数回归。**

新增造数验证每个白名单来源1条、重复 session_id 分源隔离、model筛选跨页、两远程账号默认/显式范围、非法source、并列时间排序；验证 tests/test_db_multiuser.py 的 Codex 生命周期新用例。
`rtk proxy python -m pytest tests/test_codex_server.py tests/test_db_multiuser.py tests/test_db_credential_semantics.py -q`。
`rtk proxy git add app/db.py app/server.py app/web/index.html app/web/app.js app/web/style.css tests/test_codex_server.py tests/test_db_multiuser.py`
`rtk proxy git commit -m "feat: unify usage records and sessions by source"`

### Task 8（交付二）: 统一记录验证、截图与回归

**Files:** Modify `scripts/serve_codex_fixture.py`（增加可分页种子数据）、`scripts/check_codex_ui.cjs`（把交付一边界断言替换为统一记录断言）；复核 `tests/test_db_credential_semantics.py` 不受影响；复核 GoGauge.spec（无新模块，仅确认 archive 仍完整）。此任务不重新运行已完成且无变化的同一全量套件两遍。

**Interfaces:** fixture服务只使用临时数据库且禁止扫描真实日志/外呼；浏览器断言覆盖来源筛选、统一明细、会话分组与分页；输出实际断言/截图，不把文档静态检查称为功能通过。

- [ ] **Step 1: 运行一次专项与全量。**

```powershell
rtk proxy python -m pytest tests/test_codex_api.py tests/test_codex_db.py tests/test_codex_server.py tests/test_codex_ui_contract.py tests/test_report_api.py tests/test_db_multiuser.py -q
rtk proxy python -m pytest -q
rtk proxy node --check app/web/app.js
```

全量基线本身不全绿则报告已存在失败和新增失败，不削弱旧断言。

- [ ] **Step 2: 数据勾稽（含记录/会话层）。**

同一 frozen/临时数据集、同一 source/range、导入空闲状态验证：
Codex totals=channels合计=models合计=Codex report tokens=Codex小时合计=Codex记录全部页合计；来源相同条件下 sessions合计也一致。全渠道新增Codex前后delta=Codex total。
统一明细保留各来源的含缓存全量，旧公共报表有自己的历史口径，不把二者全来源相等作为门禁；本需求只要求 Codex 贡献及同口径的报表一致。DSH只有当日快照，不参与明细来源勾稽。

- [ ] **Step 3: 扩展 fixture 与浏览器断言。**

`serve_codex_fixture.py` 增加可分页 Codex 种子数据（例如 9 条同会话记录，与 test_unified_paging_and_sessions 同形态；可与原 `codex:ui:1` 共存，总记录数 ≥8 保证 7 条/页下有两页），其余桩保持不变。`check_codex_ui.cjs` 把交付一的边界断言（`#rec-source-filter` 不存在）替换为统一记录断言，并补充分页与会话：

```javascript
await page.locator('[data-page="records"]').click();
// 默认“全部”（显式 source=all）：fixture 无远程账号时仅含 Codex 种子记录
await page.locator("#records-body").getByText("codex-ui-model").waitFor();
// 显式 codex：统一明细可见模型与 130 total；来源列显示 Codex
await page.locator("#rec-source-filter").selectOption("codex");
assert.doesNotMatch(await page.locator("#records-body").innerText(), /NaN|undefined/);
// source=all 分页：第 1/2 页 source_record_id 不重复
await page.locator("#rec-source-filter").selectOption("all");
await page.locator("#pg-next").click();
await page.locator("#records-body").waitFor();
// 会话用量：同 source 下 codex 会话合计与明细一致
const sessionsText = await page.locator("#sessions-body").innerText();
assert.match(sessionsText, /codex-ui-model|ui/);
```

zh/en 与亮暗主题各过一轮记录页；窄视口（390px）确认两表容器内横向滚动可用、无文字重叠。截图存入 `artifacts/codex-ui/records-*.png`。

- [ ] **Step 4: 构建回归。**

```powershell
rtk proxy python -m PyInstaller --noconfirm --distpath .probe/codex-build-d2/dist --workpath .probe/codex-build-d2/work GoGauge.spec
rtk proxy pyi-archive_viewer -r -l .probe/codex-build-d2/dist/GoGauge.exe
```

本交付无新模块，确认 archive 列表仍含 app.codex_api 与 web 资产、构建退出 0 即可；构建产物目录与交付一区分，不覆盖他人输出。

- [ ] **Step 5: 最终检查与交付。**

`rtk proxy git diff --check`
`rtk proxy git status --short`

记录实际测试通过/跳过/失败和截图路径；根据下表逐条核实。交付说明确认交付一的已知边界（记录页无 Codex 明细）已在本交付消除。业务代码只有上述文件；需求文档变更必须另经确认，不自动重写需求。
`rtk proxy git add scripts/serve_codex_fixture.py scripts/check_codex_ui.cjs`
`rtk proxy git commit -m "test: verify codex unified records end to end (delivery 2)"`

## 需求覆盖与验证证据（交付二）

| 需求 | 实施任务 | 实施后须提供的证据 |
|---|---|---|
| 记录页来源筛选 | T6 | 全部/OpenCode/BAI/CommandCode/ZCode/Claude Code/Codex 七项；显式 source 与省略 source 行为分层；非法 source=400 |
| 统一明细 | T6 | 四表固定字段投影；`source_record_id` 命名空间；Codex 费用/Key NULL 显示 `—`；稳定 SQL 分页跨页不重复 |
| 统一会话 | T6 | `(source,account_id,session_id)` 分组隔离；跨来源同 session_id 不合并；“未归属”回退；Codex 会话合计与明细一致 |
| 登录独立性 | T6 | 未登录远程账号时 `source=codex/all` 仍可查；Codex 不受账号切换/删除/退出影响 |
| tok/s（记录层） | T6 | 记录显示 per-record `speed_tps`；无明确耗时时 `—`；聚合 avg 只对有效行 |
| 费用缺失 | T6 | 单 Codex 费用 NULL；混合小计 partial；NULL 不渲染为 0 |
| 回归/交付 | T8 | 真实 pytest、浏览器状态/截图和构建记录，不能使用计划文本证明实现通过；交付一边界已消除 |

## 本次计划评审记录

本表只记录“计划与需求的一致性、可执行性”，不记录功能实现完成度。每次完整评审算一轮；补读和编辑属于该轮，不凭工具调用次数增加轮数。连续两轮通过立即停止；如仍有缺陷最多完成第6轮（超过5次时马上停止），不得继续第7轮。

| 轮次 | 结论 | 发现与处置 |
|---|---|---|
| 1–4 | 见交付一计划评审记录 | 原总体计划四轮评审（2 次修订后连续 2 轮通过）适用于本文 T6/T8 继承的任务内容 |
| 5 | 已修订，待复审 | 同步需求文档后统一 records 端点、projection 字段（`source_record_id/started_at/provider_id/duration_ms/speed_source/cost_available`）与固定排序键已在本文 T6 落实 |
| 6 | 已修订（拆分） | 2026-09-07 按需求文档交付拆分裁决，原总体计划拆分为交付一（T1–T5、T7 与交付一验证）与交付二（本文：T6 与交付二验证）；明确前置条件（交付一已落地，per-source 存储查询复用 T2 成果）、交付一边界由本交付消除、fixture/浏览器脚本复用交付一产物并扩展、构建产物目录区分。 |
| 7 | 已修订，待复审 | 2026-09-07 与需求文档逐条比对复审，发现 3 项不一致并全部修正：①记录页默认来源与需求 §5.3“前端默认选中‘全部’且显式发送 source=all”相反（计划原为默认“当前账号”），已改默认 `source=all` 并同步调整切换账号语义与 T8 浏览器默认态断言；②明细列清单缺需求 §5.3 要求的 reasoning 与缓存写列；③省略 `source` 的兼容行为限定为仅保留给 API 旧调用方与既有测试。 |
| 8 | 通过 | 2026-09-07 第 3 轮全量无改动复核：默认 `source=all` 在约束/接口/测试/浏览器断言四处一致；`test_unified_route_not_active_account` 保留的“省略 source=活跃账号空库 total=0”断言与 API 兼容层语义吻合；前置条件、勾稽范围与交付一产物复用关系无矛盾。未发现新的问题。 |
| 9 | 通过，停止 | 2026-09-07 第 4 轮终审：T6→T8 顺序、Files 声明、前置条件与交付一产物的复用关系（存储查询/fixture/浏览器脚本/构建目录）全部核验通过。连续通过数=2（与交付一联合评审），评审结束。 |
| 10 | 已修订，待复审 | 2026-09-07 新一轮复审：发现 2 项投影口径模糊——`usage_records` 无 total 列但投影未说明 `total_tokens` 来源（已明确为 `input_tokens+output_tokens`，与 Codex 缺总量回退口径一致）；会话聚合 `uncached_input_tokens`/`cache_hit_tokens` 口径未说明（已明确为 `MAX(input-cache_read,0)` 与 `cache_read_tokens`，与现有 hit_rate 口径一致）。 |
| 11 | 通过 | 2026-09-07 第 2 轮复核：两处投影口径修订落位（行 126 total 来源、行 131 uncached/cache_hit 口径）；与交付一 `codex_row` fixture、`api_call` 夹具的复用关系无矛盾；统一查询默认 `source=all` 与省略兼容层语义在约束/接口/测试/浏览器断言四处仍一致。未发现新的问题。 |
| 12 | 通过，停止 | 2026-09-07 第 3 轮终审（结构完整性）：代码块围栏配对、无行尾空白、评审记录表 8 行无重复/畸形；第 10/11 轮修订点复核无回退。连续通过数=2（与交付一联合评审），本轮评审结束。 |
| 13 | 已修订，待复审 | 2026-09-08 代码落地后复审（计划 vs 当前实况）：逐项核验通过——conftest 三夹具逐字段一致（id="s:1"/token_count/130）、`api_call` 夹具一致、`codex_records_page/codex_session_stats_page` 已存在且输出统一形状投影、`rec-source-filter`/`unified_*` 确实不存在、`/api/state.codex` 与交付一前端四符号（canUseLocalCodex/loadCodexSummary/CH_COLOR.codex/fmtOptionalMoney）已落地、check_codex_ui.cjs 含待替换的边界断言。发现 3 项并修订：①T6 Step 4 缺“source=codex/all 统一路由调用 `_maybe_trigger_codex_import`”（需求 §6 触发点要求；当前 records/sessions 路由无触发点，测试已 stub 该函数）；②基线表补交付一实况（per-source 查询时间参数为 `period` 而非 `days`）与 20260907 并行改动实况（claudecode 双源 proxy 行、渠道明细自澄清已执行、check_codex_ui.cjs 约 323 行只动 records 区块）；③T8 种子数据与原 fixture 共存及分页页数下限说明。 |
| 14 | 通过 | 2026-09-08 第 2 轮复核：第 13 轮 3 项修订全部落位（T6 Step 4 触发点、基线表两实况行、T8 种子说明）；需求文档排查确认 diff 规模由既有未签入的第 1–15 轮与设计修订累积解释，无他方新增评审轮次，本计划引用的需求依据（§5.3 默认 source=all、省略兼容层、统一记录字段）未变。未发现新的问题。 |
| 15 | 通过，停止 | 2026-09-08 第 3 轮终审：评审记录表 1–4/5–13 连续无重复无畸形（基线表“20260907 并行改动实况”行为日期开头导致的计数误报，已排除）；代码围栏配对、无行尾空白；计划对当前代码的全部依赖（函数签名、夹具、路由现状、前端 id、脚本区块）均经实况核验。连续通过数=2，评审结束：交付二计划与需求文档一致、与当前代码实况吻合、可执行。 |
