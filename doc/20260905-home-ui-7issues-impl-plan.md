# 首页 UI 7 项问题修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 GoGauge 首页 7 项已确诊的 UI/性能问题（配额卡竖排、配额摘要条简陋、图表色暗、切渠道卡顿、GLM 卡归属错误、本地渠道占位文案、账期汇总错位）。

**Architecture:** 性能问题（问题 4）在 db.py 加 SQLite 表达式索引 + server.py 给 overview 组装加短 TTL 缓存；布局问题（问题 1/7）纯 CSS grid 声明；观感问题（问题 2/3）重写 quota-bar 渲染为渠道卡组 + 调亮渠道色板变量；归属问题（问题 5/6）前端显隐状态机 + 配额条并入 ZCode 额度 + 启动预热。

**Tech Stack:** Python 3.12.10（sqlite3 表达式索引）、原生 JS（无框架，Chart.js 4）、CSS Grid。

**Spec:** `doc/20260904-bug-diagnosis-home-ui-7issues.md`（v2 方案表 + Review 记录，已 3 轮 review 通过；本计划逐条实现该表，Review 备注 1/2/3 分别落在 Task 8/1/2）。

## Global Constraints

- Python 解释器：`python`（不可用时 `D:\.pyenv\pyenv-win\versions\3.12.10\python.exe`）；禁止 `py`、`py -3.12`、裸 `pip`。
- 每个任务完成标准：`python -m pytest tests/ -q` 全量通过（基线 334 passed）。
- 前端改动后必须通过 `node --check app/web/app.js`（node v22.17.0 已确认可用）。
- **不自动签入**：所有 `git commit` 步骤需人工确认后才执行（AGENTS.md 约定）。
- 外科手术式修改：不改任务范围外的代码、不重构、不顺手"优化"。
- 测试环境窗口限制：`test_report_api.py` 中 COMPARE_SKIP 相关用例在 0-3 点 / 22 点后跳过属正常，不算失败。
- 前端无自动化测试框架，前端任务的验证 = `node --check` + Task 10 手动验收清单。

## 文件结构总览

| 文件 | 涉及任务 | 职责 |
|------|----------|------|
| `app/db.py` | Task 1 | 表达式索引（聚合查询提速） |
| `app/server.py` | Task 2, 8 | overview TTL 缓存 + 失效；ZCode 额度预热函数 |
| `app/main.py` | Task 8 | 启动预热线程 |
| `app/web/app.js` | Task 3, 5, 6, 8, 9 | seq 守卫 / tabs 缓存 / 账期 title / quota-bar 重写 / zcode 显隐状态机 / 本地渠道隐藏 |
| `app/web/style.css` | Task 3, 4, 5, 6, 7 | swapping 提示 / 竖排修复 / 通栏标题 / 渠道卡样式 / 色板 |
| `tests/test_report_api.py` | Task 1 | 索引命中验证测试 |
| `tests/test_server_overview_cache.py` | Task 2（新建） | 缓存行为测试 |

**任务依赖：** Task 6 将 `renderQuotaBar` 签名改为 `(accounts, zdata = null)`，Task 8 消费该签名并传入 zcode 数据 —— Task 6 必须先于 Task 8。其余任务相互独立。

---

### Task 1: 聚合查询索引化 — datetime(col) 确定性表达式索引 + UTC 边界参数（问题 4①，v2 重写）

> **v2 修订原因（Review 第 1 轮实测）**：原方案的 `substr(datetime(col,'localtime'),1,10)` 表达式索引被 SQLite 拒绝——`'localtime'` 是非确定性修饰符，建索引直接报 `OperationalError: non-deterministic use of datetime() in an index`。改用已实测可行的等价路线：`datetime(col)`（无修饰符，确定性）建索引，谓词改为 `datetime(col) >= datetime(?)`，窗口边界由 Python 按本地时区算成 UTC 串传入。已实测：三种真实存储格式（带 Z / 空格 / 带偏移）经 `datetime()` 标准化后一致，等值与范围谓词均走 `SEARCH ... USING INDEX`。

**Files:**
- Modify: `app/db.py:289-291` 后（索引）、`db.py:2079-2087`（`_report_range_sql` 重写 + 新增边界函数）、`db.py:2110-2134`（report_daily）、`db.py:2168-2191`（`_win_zcode`/`_win_cc` 加 params 形参）、`db.py:2211-2257`（report_windows 内三个闭包）、`db.py:2294-2320`（report_channels）、`db.py:1337-1359`（daily_stats）、`db.py:1382-1397`（today_trend）、`db.py:2353-2383`（report_hourly）、`db.py:2417-2462`（channel_totals）
- Modify: `app/db.py` 顶部 import（补 `timedelta`）
- Test: `tests/test_report_api.py`（末尾追加 2 条）

**Interfaces:**
- Produces: `_report_range_sql(range_, ts_col) -> tuple[str, list[str]]`（**签名变化**：原返回 str；返回 (SQL 片段, 前置参数)，调用方参数顺序 = 本参数在前）；`_local_day_utc_start(d) -> str`；`_range_utc_bounds(range_) -> Optional[tuple[str, str]]`。SQL 输出键/值语义不变（前端契约零变化）。

- [ ] **Step 1: 写失败测试**

在 `tests/test_report_api.py` 末尾追加：

```python
def test_day_predicate_uses_expression_index(tmp_report_db):
    """性能修复 v2 (方案4① 路线C): datetime(col) 确定性表达式索引必须命中.
    today(等值边界) 与 7d(范围) 两档谓词都断言走 SEARCH USING INDEX."""
    ids = _seed_channels()
    db.insert_usage_records([_mkrec("u-ix", "2026-09-01T08:30:00Z")], ids["opencode"])
    for range_ in ("today", "7d"):
        where, params = db._report_range_sql(range_, "r.created_at")
        sql = ("SELECT COUNT(*) FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
               f" WHERE {where} AND COALESCE(a.source,'opencode') = 'opencode'")
        plan = " | ".join(r["detail"] for r in db.get_db().execute("EXPLAIN QUERY PLAN " + sql, params).fetchall())
        assert "USING" in plan and "INDEX" in plan, f"{range_} 谓词未命中索引: {plan}"


def test_range_sql_local_day_semantics(tmp_report_db):
    """边界语义: 本地今天中午(UTC 表示)的行命中 today 窗口, 前天行不命中;
    时区换算由 _local_day_utc_start 负责, 与原 substr(datetime(col,'localtime')) 逐日等价."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    ids = _seed_channels()
    noon_local = _dt.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    in_row = noon_local.astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_row = (noon_local - _td(days=2)).astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.insert_usage_records([_mkrec("u-in", in_row), _mkrec("u-out", out_row)], ids["opencode"])
    where, params = db._report_range_sql("today", "r.created_at")
    sql = ("SELECT COUNT(*) FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
           f" WHERE {where}")
    assert db.get_db().execute(sql, params).fetchone()[0] == 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_report_api.py -k "expression_index or local_day_semantics" -v`
Expected: FAIL，`ValueError: too many values to unpack`（`_report_range_sql` 仍返回 str，解包两个变量时字符串按字符展开超出 2 个）

- [ ] **Step 3: 实现（db.py 全部改动）**

3a. import 补 `timedelta`：`from datetime import datetime, timedelta, timezone`（现文件已有 datetime/timezone 用法）。

3b. 索引（`db.py:289-291` idx_usage_account_time 之后追加）：

```python
    # 迁移 2d: UTC 确定性表达式索引 (方案4① v2 路线C) — 报表日粒度谓词改用
    # datetime(col) >= datetime(?) 走此索引 (原 substr(datetime(col,'localtime'))
    # 含非确定性修饰符, SQLite 禁止建索引, 且该形式本为全表扫描).
    # 注意: 存量库首次升级时 CREATE INDEX 需全表计算表达式, 一次性开销秒级.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_acct_utc ON usage_records"
        "(account_id, datetime(created_at))"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_usage_utc ON usage_records(datetime(created_at))"
    )
```

3c. `_report_range_sql` 重写 + 新增边界函数（替换 db.py:2079-2087）：

```python
def _local_day_utc_start(d) -> str:
    """本地日期 d 的零点对应的 UTC 时刻串 (YYYY-MM-DD HH:MM:SS).
    naive + astimezone() 挂系统本地时区, DST/时区偏移由标准库处理,
    与原 substr(datetime(col,'localtime'),1,10) 的本地日窗口逐日等价."""
    return datetime.combine(d, datetime.min.time()).astimezone() \
        .astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _range_utc_bounds(range_: str) -> Optional[tuple[str, str]]:
    """自然日窗口的 UTC 边界 (start_inclusive, end_exclusive); all -> None."""
    today = datetime.now().astimezone().date()
    n = _REPORT_RANGE_DAYS.get(range_)
    if range_ == "today":
        start, end = today, today + timedelta(days=1)
    elif range_ == "yesterday":
        start, end = today - timedelta(days=1), today
    elif n is not None:   # 7d/30d: 含今天共 N 天
        start, end = today - timedelta(days=n), today + timedelta(days=1)
    else:
        return None
    return _local_day_utc_start(start), _local_day_utc_start(end)


def _report_range_sql(range_: str, ts_col: str) -> tuple[str, list[str]]:
    """自然日窗口谓词 (v2 性能版): datetime(col) 确定性表达式走 idx_usage_*_utc.
    返回 (sql 片段, 前置参数) — 谓词位于各 WHERE 首位, 调用方参数须以本参数开头."""
    b = _range_utc_bounds(range_)
    if b is None:
        return "1=1", []
    start, end = b
    return (f"datetime({ts_col}) >= datetime(?) AND datetime({ts_col}) < datetime(?)",
            [start, end])
```

3d. `report_daily`（2110-2134）改造（注意 UNION ALL 参数按段顺序连接）：

```python
    exprs = _report_metric_exprs(metric)
    include_records = channel is None or channel in ("opencode", "bai", "commandcode")
    include_zcode = channel is None or channel == "zcode"
    include_cc = channel is None or channel == "claudecode"
    segs: list[str] = []
    params: list[Any] = []
    if include_records:
        range_sql, range_params = _report_range_sql(range_, "r.created_at")
        ch_where = ""
        ch_params: list[Any] = []
        if channel:
            ch_where = f" AND {_report_channels_expr()} = ?"
            ch_params.append(channel)
        segs.append(
            f"SELECT substr(datetime(r.created_at,'localtime'),1,10) AS b,"
            f" {_report_channels_expr()} AS ch, {exprs['records']} AS v"
            f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
            f" WHERE {range_sql}{ch_where} GROUP BY b, ch")
        params.extend(range_params)
        params.extend(ch_params)
    if include_zcode:
        range_sql, range_params = _report_range_sql(range_, "z.started_at")
        segs.append(
            f"SELECT substr(datetime(z.started_at,'localtime'),1,10) AS b, 'zcode' AS ch,"
            f" {exprs['zcode']} AS v FROM zcode_usage z"
            f" WHERE {range_sql} GROUP BY b")
        params.extend(range_params)
    if include_cc:
        range_sql, range_params = _report_range_sql(range_, "c.started_at")
        segs.append(
            f"SELECT substr(datetime(c.started_at,'localtime'),1,10) AS b, 'claudecode' AS ch,"
            f" {exprs['claudecode']} AS v FROM claudecode_usage c"
            f" WHERE {range_sql} GROUP BY b")
        params.extend(range_params)
```

（段内 SELECT/GROUP 的 `substr(datetime(col,'localtime'),1,10)` 保留——仅 WHERE 谓词需要索引，SELECT/GROUP 不影响。）

3e. `_win_zcode` / `_win_cc` 加 params 形参（2168-2191 区）：

```python
def _win_zcode(where: str, params: list[Any]) -> dict[str, Any]:
    row = get_db().execute(
        "SELECT SUM(z.input_tokens + z.output_tokens + z.reasoning_tokens) tokens,"
        " SUM(z.cost_raw)/1e8 cost, COUNT(*) requests FROM zcode_usage z WHERE " + where,
        params,
    ).fetchone()
    return {"tokens": row["tokens"] or 0, "cost": row["cost"] or 0.0, "requests": row["requests"] or 0}


def _win_cc(where: str, params: list[Any]) -> dict[str, Any]:
    row = get_db().execute(
        "SELECT SUM(c.input_tokens + c.output_tokens) tokens,"   # claudecode 无 reasoning 列 (R6)
        " SUM(c.cost_raw)/1e8 cost, COUNT(*) requests FROM claudecode_usage c WHERE " + where,
        params,
    ).fetchone()
    return {"tokens": row["tokens"] or 0, "cost": row["cost"] or 0.0, "requests": row["requests"] or 0}
```

3f. `report_windows` 内三个闭包改造（2211-2257）：

```python
    def records_where(range_: str, same_time: bool = False) -> tuple[str, list[Any]]:
        w, wp = _report_range_sql(range_, "r.created_at")
        if same_time:
            w += " AND datetime(r.created_at,'localtime') <= datetime('now','localtime')" \
                 if range_ == "today" else \
                 f" AND time(datetime(r.created_at,'localtime')) <= time('now','localtime')"
        return w + ch_filter, wp + list(ch_params)

    def local_where(range_: str, ts: str, same_time: bool = False) -> tuple[str, list[Any]]:
        w, wp = _report_range_sql(range_, ts)
        if same_time:
            w += f" AND datetime({ts},'localtime') <= datetime('now','localtime')" \
                 if range_ == "today" else \
                 f" AND time(datetime({ts},'localtime')) <= time('now','localtime')"
        return w, wp

    def window(range_: str, same_time: bool = False) -> dict[str, Any]:
        rw, rp = records_where(range_, same_time)
        zw, zp = local_where(range_, "z.started_at", same_time)
        cw, cp = local_where(range_, "c.started_at", same_time)
        return _win_merge(
            _win_records(rw, rp),
            _win_zcode(zw, zp) if not channel or channel == "zcode" else {"tokens": 0, "cost": 0.0, "requests": 0},
            _win_cc(cw, cp) if not channel or channel == "claudecode" else {"tokens": 0, "cost": 0.0, "requests": 0},
        )
```

`same7_where` 同步改造（近 7 个完整自然日 -7~-1 + 同时段）：

```python
    def same7_where(ts: str) -> tuple[str, list[Any]]:
        today = datetime.now().astimezone().date()
        start = _local_day_utc_start(today - timedelta(days=7))
        end = _local_day_utc_start(today)
        return (f"datetime({ts}) >= datetime(?) AND datetime({ts}) < datetime(?)"
                f" AND time(datetime({ts},'localtime')) <= time('now','localtime')",
                [start, end])
    same_7 = _win_merge(
        (lambda w, p: _win_records(w + ch_filter, p + list(ch_params)))(*same7_where("r.created_at")),
        _win_zcode(*same7_where("z.started_at")) if not channel or channel == "zcode" else {"tokens": 0, "cost": 0.0, "requests": 0},
        _win_cc(*same7_where("c.started_at")) if not channel or channel == "claudecode" else {"tokens": 0, "cost": 0.0, "requests": 0},
    )
```

同时段过滤（`time(datetime(col,'localtime')) <= time('now','localtime')`）与 report_windows 的"截至现在"谓词**保持原样**：它们左侧带 `'localtime'` 无法走新索引，但在 range 谓词先行过滤后的行集上执行，代价小（取舍记录，由 Task 2 缓存兜底）。

3g. `report_channels`（2294-2320）两处 `_report_range_sql` 调用点解包：

```python
    rows = get_db().execute(
        f"SELECT {_report_channels_expr()} AS ch,"
        f" {exprs_t['records']} tokens, SUM(r.input_tokens) input, SUM(r.output_tokens) output,"
        f" SUM(r.cache_read_tokens) cache_read, {_report_metric_exprs('requests')['records']} requests,"
        f" {exprs_c['records']} cost"
        f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
        f" WHERE {{range_sql}} GROUP BY ch",
        range_params,
    ).fetchall()
```

（函数入口先 `range_sql, range_params = _report_range_sql(range_, "r.created_at")` 再 f-string 引用；第二个循环体内 `range_sql, range_params = _report_range_sql(range_, ts)` 同理。）

3h. `channel_totals`（2417-2462）三处：zcode/claudecode 分支与 records 分支各 `range_sql, range_params = _report_range_sql(...)`，records 分支 params = `range_params + [channel]`（谓词在渠道参数之前）。

3i. `daily_stats`（1337-1359）WHERE 改造：

```python
    start_utc = _local_day_utc_start((datetime.now().astimezone() - timedelta(days=days)).date())
    rows = get_db().execute(
        """
        SELECT substr(datetime(created_at, 'localtime'), 1, 10) AS date,
               SUM(input_tokens + cache_read_tokens + cache_write_5m_tokens + cache_write_1h_tokens) AS total_input_tokens,
               SUM(input_tokens) AS uncached_input_tokens,
               SUM(reasoning_tokens) AS total_reasoning_tokens,
               SUM(cache_read_tokens) AS cache_hit_tokens,
               SUM(cache_write_5m_tokens + cache_write_1h_tokens) AS cache_write_tokens,
               SUM(output_tokens) AS total_output_tokens,
               SUM(cost_usd) AS total_cost_usd,
               COUNT(*) AS request_count
        FROM usage_records
        WHERE account_id = ? AND datetime(created_at) >= datetime(?)
        GROUP BY substr(datetime(created_at, 'localtime'), 1, 10)
        ORDER BY date ASC
        """,
        (aid, start_utc),
    ).fetchall()
```

3j. `today_trend`（1382-1397）：

```python
    today = datetime.now().astimezone().date()
    rows = get_db().execute(
        """
        SELECT CAST(strftime('%H', datetime(created_at, 'localtime')) AS INTEGER) AS h,
               SUM(input_tokens) AS input,
               SUM(output_tokens) AS output,
               SUM(reasoning_tokens) AS reasoning
        FROM usage_records
        WHERE account_id = ?
          AND datetime(created_at) >= datetime(?) AND datetime(created_at) < datetime(?)
        GROUP BY h
        """,
        (aid, _local_day_utc_start(today), _local_day_utc_start(today + timedelta(days=1))),
    ).fetchall()
```

3k. `report_hourly`（2353-2383）day 谓词改造（day 参数在段内首位，channel 参数在其后；UNION ALL 参数按段顺序连接）：

```python
    today = datetime.now().astimezone().date()
    start = _local_day_utc_start(today - timedelta(days=1)) if date_ == "yesterday" else _local_day_utc_start(today)
    end = _local_day_utc_start(today) if date_ == "yesterday" else _local_day_utc_start(today + timedelta(days=1))
    day_pred = "datetime({ts}) >= datetime(?) AND datetime({ts}) < datetime(?)"
    segs: list[str] = []
    params: list[Any] = []
    if channel is None or channel in ("opencode", "bai", "commandcode"):
        ch_where = ""
        if channel:
            ch_where = f" AND {_report_channels_expr()} = ?"
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(r.created_at,'localtime')) AS INTEGER) h,"
            f" {_report_channels_expr()} ch, SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) v"
            f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
            f" WHERE {day_pred.format(ts='r.created_at')}{ch_where} GROUP BY h, ch")
        if channel:
            params.append(start); params.append(end); params.append(channel)
        else:
            params.extend([start, end])
    if channel is None or channel == "zcode":
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(z.started_at,'localtime')) AS INTEGER) h, 'zcode' ch,"
            f" SUM(z.input_tokens + z.output_tokens + z.reasoning_tokens) v FROM zcode_usage z"
            f" WHERE {day_pred.format(ts='z.started_at')} GROUP BY h")
        params.extend([start, end])
    if channel is None or channel == "claudecode":
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(c.started_at,'localtime')) AS INTEGER) h, 'claudecode' ch,"
            f" SUM(c.input_tokens + c.output_tokens) v FROM claudecode_usage c"
            f" WHERE {day_pred.format(ts='c.started_at')} GROUP BY h")
        params.extend([start, end])
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_report_api.py -v`
Expected: 全部 PASS（原 17 + 新 2；含既有语义勾稽用例 `test_report_daily_range_and_channel_filter`/`test_channel_totals_zero_fallback_and_hit_rate` 等对边界语义的回归验证）

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 336 passed（334 基线 + 2 新增）

- [ ] **Step 6: Commit（需人工确认后执行）**

```bash
git add app/db.py tests/test_report_api.py
git commit -m "perf: UTC 确定性表达式索引+窗口边界参数化, 聚合查询走索引 (问题4①)"
```

---

### Task 2: /api/accounts/overview 组装加 3s TTL 缓存 + 失效（问题 4②）

**Files:**
- Modify: `app/server.py:61-65`（缓存变量声明区）、`server.py:1193-1232`（组装体抽函数）、失效点 `server.py:637/639`（sync_usage done）、`server.py:1165-1172`（logout）、`server.py:1258`（switch）、`server.py:1267`（rename）、`server.py:1282`（delete）
- Create: `tests/test_server_overview_cache.py`

**Interfaces:**
- Produces: `_accounts_overview_payload() -> dict[str, Any]`（路由层调用）、`_invalidate_overview_cache() -> None`（各状态变更点调用）。Task 8 不依赖本接口，但依赖其性能效果。

- [ ] **Step 1: 写失败测试**

新建 `tests/test_server_overview_cache.py`：

```python
"""accounts/overview 组装缓存测试 (方案4②): TTL 内不重查库, 失效后重查."""
from __future__ import annotations

import pytest

from app import db, server


@pytest.fixture()
def tmp_report_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


@pytest.fixture()
def _no_side_effect(monkeypatch):
    """隔离组装路径的外部副作用: 配额后台刷新会发真实网络请求, 汇率缓存
    首次未命中会 urlopen(10s 超时) — 测试必须打桩."""
    monkeypatch.setattr(server, "_ensure_quota_async", lambda aid=None: None)
    monkeypatch.setattr(server, "_fetch_usd_cny", lambda: 7.2)


def test_overview_payload_cached_until_invalidated(tmp_report_db, _no_side_effect, monkeypatch):
    server._invalidate_overview_cache()
    calls = {"n": 0}
    real_list = db.list_accounts

    def counting_list():
        calls["n"] += 1
        return real_list()

    monkeypatch.setattr(db, "list_accounts", counting_list)
    server._accounts_overview_payload()
    server._accounts_overview_payload()  # TTL 内第二次: 不重查
    assert calls["n"] == 1
    server._invalidate_overview_cache()
    server._accounts_overview_payload()  # 失效后: 重查
    assert calls["n"] == 2


def test_overview_payload_reflects_account_change_after_invalidate(tmp_report_db, _no_side_effect):
    server._invalidate_overview_cache()
    before = len(server._accounts_overview_payload()["accounts"])
    db.add_account("tok-x", "ws-x", switch=False, dedupe_key="ws-x")
    server._invalidate_overview_cache()  # 模拟 switch/delete 等入口的失效调用
    after = len(server._accounts_overview_payload()["accounts"])
    assert after == before + 1
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_server_overview_cache.py -v`
Expected: FAIL，`AttributeError: module 'app.server' has no attribute '_invalidate_overview_cache'`

- [ ] **Step 3: 实现**

3a. `app/server.py:64`（`_EXCHANGE_TTL` 声明之后）加：

```python
_overview_cache: dict[str, Any] = {"at": 0.0, "data": None}  # overview 组装缓存 (方案4②)
_OVERVIEW_TTL = 3.0


def _invalidate_overview_cache() -> None:
    """账号切换/增删/改名/退出/同步完成时调用, 下次 overview 重新组装."""
    _overview_cache["at"] = 0.0
    _overview_cache["data"] = None
```

3b. 把 `server.py:1193-1232` 路由体改造为组装函数。路由 `if route == "/api/accounts/overview" and method == "GET":` 块整体替换为一行调用：

```python
    if route == "/api/accounts/overview" and method == "GET":
        _json_response(handler, _accounts_overview_payload())
        return
```

并在该路由之前（模块函数区，建议 `_report_channels_response` 之后）新增组装函数 —— 函数体即原 1194-1231 行逻辑原样搬移，仅首尾包缓存：

```python
def _accounts_overview_payload() -> dict[str, Any]:
    """GET /api/accounts/overview 数据组装 (含 3s TTL 缓存, 方案4②):
    切换渠道页签时首页并发拉本端点, 原实现逐账号 3 个全表聚合排队;
    TTL 内直返缓存, 账号/同步状态变化由 _invalidate_overview_cache 失效."""
    now = time.time()
    if _overview_cache["data"] is not None and now - _overview_cache["at"] < _OVERVIEW_TTL:
        return _overview_cache["data"]
    # ↓↓↓ 原 1194-1230 行逻辑原样搬入 (accounts 列表组装) ↓↓↓
    active_id = db.get_active_account_id()
    accounts: list[dict[str, Any]] = []
    for acc in db.list_accounts():
        if not acc["has_token"]:
            continue
        aid = acc["id"]
        _ensure_quota_async(aid)
        slot = _quota_cache.get(aid)
        quota = slot.get("data") if slot else None
        sync_state = db.get_sync_state(aid)
        accounts.append(
            {
                "id": aid,
                "name": acc["name"],
                "source": acc["source"],
                "logged_in": True,
                "active": aid == active_id,
                "quota": quota,
                "today": db.totals("today", aid),
                "today_trend": db.today_trend(aid),
                "daily7": db.daily_stats(7, aid),
                "last_sync_at": sync_state.get("last_sync_at"),
                "last_sync_status": sync_state.get("last_sync_status"),
                "cc_summary": (db.get_cc_summary(aid) if acc["source"] == "commandcode" else None),
            }
        )
    payload = {
        "ok": True,
        "accounts": accounts,
        "active_id": active_id,
        "exchange_rate": {"usd_cny": _fetch_usd_cny(), "currency": "CNY"},
        "server_time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    _overview_cache["at"] = time.time()
    _overview_cache["data"] = payload
    return payload
```

3c. 五处失效调用（各在状态变更成功之后、`_json_response` 之前或紧后插入一行 `_invalidate_overview_cache()`）：

| 位置 | 插入点 |
|------|--------|
| `server.py:637` 与 `:639`（sync_usage 两个 done 分支） | `_set_phase("done", ...)` 之后各加一行 |
| `server.py:1169`（logout，`_quota_cache.pop` 之后） | 加一行 |
| `server.py:1258`（switch，`db.set_active_account(aid)` 之后） | 加一行 |
| `server.py:1267`（rename 成功分支内，`db.rename_account` 返回真后） | 加一行 |
| `server.py:1282`（delete，`_quota_cache.pop(aid, None)` 之后） | 加一行 |

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_server_overview_cache.py tests/test_report_api.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 338 passed（336 + 2 新增）

- [ ] **Step 6: Commit（需人工确认后执行）**

```bash
git add app/server.py tests/test_server_overview_cache.py
git commit -m "perf: accounts/overview 组装 3s TTL 缓存 + 状态变更失效 (问题4②)"
```

---

### Task 3: 前端切换体验 — seq 守卫 + 加载提示 + tabs 请求收敛（问题 4③④⑤）

**Files:**
- Modify: `app/web/app.js:493-519`（loadDashboard 单渠道分支）、`app/web/app.js:536-544`（renderChannelTabs）
- Modify: `app/web/style.css:483` 之后（新增 .swapping 规则）

**Interfaces:**
- Consumes: 现有 `state.channel`、`api()`、`switchChannel()`。
- Produces: 模块级 `chSeq`（数值，单渠道分支过期响应守卫）、`channelTabsCache`（60s 内存缓存）；`.swapping` CSS 类。无跨任务消费方。

- [ ] **Step 1: 单渠道分支加 seq 守卫 + 加载提示**

`loadDashboard` 单渠道分支（app.js:503-518）改为（新增行已注释标记）：

```js
    // 单渠道: 消耗走 report 接口(与活跃账号无关), 配额块/账期卡走 accounts/overview 逐账号 (spec v5/v8)
    const seq = ++chSeq;                                  // 新增: 快速切渠道时丢弃过期响应 (方案4④)
    $("report-single").classList.add("swapping");         // 新增: 加载提示 (方案4③)
    Promise.all([
      api(`/api/report/channel-overview?range=${state.range}&channel=${state.channel}`),
      api(`/api/report/channel-trend?date=${state.range === "yesterday" ? "yesterday" : "today"}&channel=${state.channel}`),
      api(`/api/accounts/overview`),
    ]).then(([totals, trend, ov]) => {
      if (seq !== chSeq) return;                          // 新增: 过期响应丢弃
      $("report-single").classList.remove("swapping");    // 新增
      const chAccounts = ov.accounts.filter((a) => a.source === state.channel);
      renderQuotaSingle(chAccounts);
      const rangeHint = document.querySelector(".overview .hint");   // 新R1 N13: dsh 仅今日口径提示
      if (rangeHint) rangeHint.textContent = totals.today_only ? t("dataSinceToday") : t("followRange");
      renderOverview(totals, state.channel);          // 概览 6 格: channel_totals 键与 db.totals 对齐 (T5)
      chartToday(trend);                              // 24h input/output 双系列 (spec v8)
      const isCc = state.channel === "commandcode";
      $("cc-summary").hidden = !isCc;
      if (isCc) renderCcAccounts(chAccounts);         // 账期卡逐账号 (spec v5); 全部 tab 不显示
    }).catch((e) => {
      if (seq === chSeq) $("report-single").classList.remove("swapping");   // 新增
      if (!quiet) toast(t("loadFailed") + ": " + e);
    });
```

并在文件中 `let loadSeq = 0;`（app.js:491）旁加一行声明：

```js
let chSeq = 0;   // 单渠道响应序号: 快速连点渠道 tab 时丢弃旧响应 (方案4④)
```

- [ ] **Step 2: renderChannelTabs 60s 缓存收敛**

`renderChannelTabs`（app.js:536-544）整体替换：

```js
let channelTabsCache = { at: 0, data: null };   // 方案4⑤: 切渠道高频触发, 60s 内复用
function renderChannelTabs() {
  if (channelTabsCache.data && Date.now() - channelTabsCache.at < 60000) {
    renderChannelTabsFrom(channelTabsCache.data);
    return;
  }
  api("/api/report/channels?range=today").then((d) => {
    channelTabsCache = { at: Date.now(), data: d };
    renderChannelTabsFrom(d);
  }).catch(() => {});
}
function renderChannelTabsFrom(d) {
  const tabs = [{ ch: "all", label: t("channelAll") }]
    .concat(d.summary.map((s) => ({ ch: s.channel, label: s.channel, n: s.accounts })));
  $("channel-tabs").innerHTML = tabs.map((x) =>
    `<button class="pill${x.ch === state.channel ? " active" : ""}" data-ch="${x.ch}">${x.label}${x.n > 1 ? ` <small>·${x.n}</small>` : ""}</button>`).join("");
  if (state.channel !== "all" && !d.summary.some((s) => s.channel === state.channel)) switchChannel("all"); // 账号被删回退
}
```

已知取舍（写入代码注释即可，不另处理）：缓存 60s 内账号增删后 tab 账号数角标可能过时，60s 后自愈。

- [ ] **Step 3: 加 .swapping 样式**

`app/web/style.css:483`（`.acct-name` 规则）之后加：

```css
/* 切渠道加载提示: 响应到达前旧内容降不透明度 (方案4③) */
.swapping { opacity: .55; transition: opacity .15s; }
```

- [ ] **Step 4: 语法检查**

Run: `node --check app/web/app.js`
Expected: 无输出（语法通过）

- [ ] **Step 5: 全量回归（前端不涉及 pytest，跑一遍确认未碰坏 Python 侧）**

Run: `python -m pytest tests/ -q`
Expected: 338 passed

- [ ] **Step 6: Commit（需人工确认后执行）**

```bash
git add app/web/app.js app/web/style.css
git commit -m "perf: 切渠道 seq 守卫/加载提示/tabs 请求 60s 收敛 (问题4③④⑤)"
```

---

### Task 4: 配额三卡横排（问题 1）

**Files:**
- Modify: `app/web/style.css:483` 之后（.acct-quota-body 规则，紧邻 Task 3 的 .swapping）

**Interfaces:** 无代码接口，纯 CSS。渲染结构不变（`#usage-blocks > .acct-quota > .acct-name + .acct-quota-body > .ub×N`）。

- [ ] **Step 1: 加 grid 规则**

`app/web/style.css` 在 `.acct-name` 规则后加：

```css
/* 单渠道逐账号配额: 内部窗口卡 3 列横排 (问题1) — 原先 .usage-blocks 的
   3 列只作用于 .acct-quota 层, 内部 .ub 块级堆叠呈竖排 */
.acct-quota-body { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
```

- [ ] **Step 2: 语法检查 + 全量回归**

Run: `node --check app/web/app.js && python -m pytest tests/ -q`
Expected: 语法通过；338 passed

- [ ] **Step 3: Commit（需人工确认后执行）**

```bash
git add app/web/style.css
git commit -m "fix: 单渠道配额窗口卡改 3 列横排 (问题1)"
```

---

### Task 5: 账期汇总账号名通栏（问题 7）

**Files:**
- Modify: `app/web/style.css`（Task 4 追加规则之后）
- Modify: `app/web/app.js:654`（renderCcAccounts 的 acct-name 加 title）

**Interfaces:** 选择器限定 `#cc-grid .acct-name`，不影响 renderQuotaSingle 场景的 `.acct-name`（Review 第 1 轮 P2 项）。

- [ ] **Step 1: CSS 通栏 + 省略**

`app/web/style.css` Task 4 规则之后加：

```css
/* 账期汇总: 账号名通栏标题行, 不与 4 张 KPI 卡争 4 列格位 (问题7);
   限定 #cc-grid — .acct-name 同时被单渠道配额分组标题复用 (renderQuotaSingle) */
#cc-grid .acct-name { grid-column: 1 / -1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
```

- [ ] **Step 2: app.js 账号名加完整值 title**

`renderCcAccounts`（app.js:654）中：

```js
    return `<div class="acct-name" title="${escapeHtml(a.name)}">${escapeHtml(a.name)}</div>` + cards.map((c) =>
```

- [ ] **Step 3: 语法检查 + 全量回归**

Run: `node --check app/web/app.js && python -m pytest tests/ -q`
Expected: 语法通过；338 passed

- [ ] **Step 4: Commit（需人工确认后执行）**

```bash
git add app/web/style.css app/web/app.js
git commit -m "fix: 账期汇总账号名通栏+省略, 修复卡位错乱 (问题7)"
```

---

### Task 6: 各渠道配额卡组化（问题 2）

**Files:**
- Modify: `app/web/app.js:2057-2090`（renderQuotaBar 整体重写）、`app/web/app.js:2038`（调用点传 zdata 占位 null）
- Modify: `app/web/style.css:477-479`（.qb-row/.qb-ch 替换为卡片样式）

**Interfaces:**
- Produces: `renderQuotaBar(accounts, zdata = null)` —— Task 8 传入 `/api/zcode/quota` 响应；`zdata` 形状 = `{ success: boolean, level: string, windows: [{label, used, ...}] }`，失败/为 null 时不出 zcode 卡。

- [ ] **Step 1: 重写 renderQuotaBar**

app.js 中 `renderQuotaBar`（2057-2090）整体替换为：

```js
function renderQuotaBar(accounts, zdata = null) {
  const byCh = {};
  for (const a of accounts) {
    (byCh[a.source] = byCh[a.source] || []).push(a);
  }
  const cards = Object.keys(byCh).map((ch) => {
    const list = byCh[ch];
    // 同步归并 (spec v10): 时间取最陈旧 min; 任一失败 -> 红点
    const times = list.map((a) => a.last_sync_at).filter(Boolean).sort();
    const failed = list.some((a) => a.last_sync_status && a.last_sync_status !== "ok");
    const foot = `${list.length}${t("accountsUnit")}${times.length ? ` · ${fmtAgo(times[0])}` : ""}${failed ? ' <span class="sync-fail" title="同步失败">⚠</span>' : ""}`;
    let main;
    if (ch === "opencode") {
      // 窗口百分比不可聚合 -> 最紧张账号 max% (spec v5)
      const pct = Math.max(0, ...list.map((a) => (a.quota && a.quota.windows || []).reduce((m, x) => Math.max(m, x.label === "5h Rolling" ? (x.used || 0) : 0), 0)));
      main = `<div class="qb-bar"><div class="qb-bar-fill" style="width:${Math.min(100, pct).toFixed(1)}%"></div></div>
        <div class="qb-sub">${t("rolling")} 5h · <b>${Math.max(0, pct).toFixed(0)}%</b></div>`;
    } else if (ch === "bai") {
      // 积分余额跨账号合计 (新R1)
      const pts = list.reduce((s, a) => s + (((a.quota && a.quota.windows || [])
        .find((x) => x.unit === "points" || x.points_balance != null) || {}).points_balance || 0), 0);
      main = `<div class="qb-val">${t("quotaPointsBalance").replace("{n}", fmtInt(pts))}</div>`;
    } else if (ch === "commandcode") {
      // USD 剩余额度跨账号合计 (与 renderUsageBlocks USD 分支同字段)
      const rem = list.reduce((s, a) => s + (((a.quota && a.quota.windows || [])
        .filter((x) => x.unit === "USD")
        .reduce((u, x) => u + ((Number(x.total) || 0) - (Number(x.used) || 0)), 0)) || 0), 0);
      main = `<div class="qb-val">${fmtUsd(rem)}</div><div class="qb-sub">${t("remaining")}</div>`;
    } else {
      main = `<div class="qb-val">${list.length}</div><div class="qb-sub">${t("accountsUnit")}</div>`;
    }
    return `<div class="qb-card">
      <div class="qb-head"><span class="qb-dot" style="background:${chColor(ch)}"></span><span class="qb-name" style="color:${chColor(ch)}">${ch}</span></div>
      ${main}
      <div class="qb-foot">${foot}</div>
    </div>`;
  });
  if (zdata && zdata.success) {   // Task 8 接入 ZCode 额度; 本任务先支持入参
    const wins = zdata.windows || [];
    const segs = wins
      .filter((x) => x.label === "5h Rolling" || x.label === "Weekly")
      .map((x) => `${(QUOTA_LABEL[x.label] || (() => x.label))()} ${(Number(x.used) || 0).toFixed(0)}%`);
    cards.push(`<div class="qb-card">
      <div class="qb-head"><span class="qb-dot" style="background:${chColor("zcode")}"></span><span class="qb-name" style="color:${chColor("zcode")}">zcode</span>${zdata.level ? `<span class="zcode-badge">${escapeHtml(zcodeLevelText(zdata.level))}</span>` : ""}</div>
      <div class="qb-sub">${segs.join(" · ") || t("zcodeNoData")}</div>
      <div class="qb-foot">GLM Coding Plan</div>
    </div>`);
  }
  $("quota-bar").innerHTML = cards.join("");
}
```

调用点 `loadReportAll`（app.js:2038）暂保持 `renderQuotaBar(ov.accounts)`（第二参数默认 null，行为不变；Task 8 再传实参）。

- [ ] **Step 2: 替换样式**

`app/web/style.css` 中删除旧规则（477-479 行）：

```css
/* 配额摘要条 (T9) */          ← 删除
.qb-row { ... }                ← 删除
.qb-ch { ... }                 ← 删除
```

`.sync-fail { color: #dc2626; }` 保留（新结构仍用）。替换为：

```css
/* 配额摘要条: 渠道小卡组 (问题2, 替代原文本行+字符进度条).
   选择器必须用 #quota-bar — 外层 card 的 class 恰好也是 quota-bar
   (index.html: <div class="card quota-bar">), 用类选择器会把标题与卡组并排破版 */
#quota-bar { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; padding: 12px 14px 8px; }
.qb-card { border: 1px solid var(--border); border-radius: 10px; padding: 10px 12px 8px; background: var(--muted); }
.qb-head { display: flex; align-items: center; gap: 7px; margin-bottom: 8px; }
.qb-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.qb-name { font-size: 12.5px; font-weight: 600; }
.qb-bar { height: 6px; background: var(--border); border-radius: 99px; overflow: hidden; }
.qb-bar-fill { height: 100%; border-radius: 99px; background: var(--grad-brand); }
.qb-val { font-size: 16px; font-weight: 700; font-family: var(--font-mono); letter-spacing: -0.3px; }
.qb-sub { font-size: 11.5px; color: var(--text3); margin-top: 6px; font-variant-numeric: tabular-nums; }
.qb-foot { font-size: 11px; color: var(--text3); margin-top: 6px; }
```

- [ ] **Step 3: 语法检查 + 全量回归**

Run: `node --check app/web/app.js && python -m pytest tests/ -q`
Expected: 语法通过；338 passed

- [ ] **Step 4: Commit（需人工确认后执行）**

```bash
git add app/web/app.js app/web/style.css
git commit -m "feat: 各渠道配额改渠道小卡组, 支持接入 ZCode 额度 (问题2)"
```

---

### Task 7: 渠道色板调亮 + 环形图描边（问题 3）

**Files:**
- Modify: `app/web/style.css:31-36`（亮色主题 `--ch-*` 两处色值）
- Modify: `app/web/app.js:2172`（chartReportDonut borderWidth）

**Interfaces:** 无接口。`chColor()` 读 CSS 变量，改变量即全局生效（堆叠图/环形图/图例/配额卡色点/渠道明细表）。

- [ ] **Step 1: 调亮两处色值（其余保留）**

`app/web/style.css` 亮色主题 `:root`（31-36 行）仅改：

```css
  --ch-bai: #f59e0b;            /* 原 #d97706: 暗琥珀 → 亮琥珀 (问题3) */
  --ch-claudecode: #fb7185;     /* 原 #e11d48: 暗玫红 → 亮玫红 (问题3) */
```

明确定不做（记录取舍）：`--ch-dsh` 亮色主题保留 `#64748b`（Review 第 2 轮：亮色底上抄暗色主题值 `#94a3b8` 对比度不足）；堆叠柱不加 canvas 渐变（现有 `borderRadius:2` 已有圆角，渐变实现脚本化复杂增益小）。

- [ ] **Step 2: 环形图加描边**

`chartReportDonut`（app.js:2172）：

```js
    data: { labels: chs, datasets: [{ data: totals, backgroundColor: chs.map(chColor), borderWidth: 2, borderColor: cssVar("--card") }] },
```

- [ ] **Step 3: 语法检查 + 全量回归**

Run: `node --check app/web/app.js && python -m pytest tests/ -q`
Expected: 语法通过；338 passed

- [ ] **Step 4: Commit（需人工确认后执行）**

```bash
git add app/web/style.css app/web/app.js
git commit -m "feat: 渠道色板调亮+环形图描边 (问题3)"
```

---

### Task 8: GLM 卡归属 zcode 页签 + 配额条并入 ZCode（问题 5）

**Files:**
- Modify: `app/web/app.js:350`（applyLang 条件）、`app.js:503-508`（单渠道分支显隐+主动渲染）、`app.js:2032-2038`（loadReportAll 并入 zcode 请求）
- Modify: `app/server.py:839` 之后（`zcode_quota_warmup()`）
- Modify: `app/main.py:466` 之后（预热线程）

**Interfaces:**
- Consumes: Task 6 的 `renderQuotaBar(accounts, zdata)`；现有 `zcodeQuotaLast` / `loadZcodeQuota()` / `renderZcodeQuota()` / `zcodeLevelText()`；`_ensure_zcode_quota_async()`（server.py:824，后台刷新不阻塞）。
- Produces: `zcode_quota_warmup() -> None`（server.py 公开函数，main.py 调用）。

- [ ] **Step 1: 单渠道显隐状态机（Review 第 1 轮 P1 项，两半缺一不可）**

`loadDashboard` 单渠道分支，在 `$("report-all").hidden = true; $("report-single").hidden = false;`（app.js:501）之后加：

```js
    // GLM Coding Plan 额度卡只属于 zcode 渠道页签 (问题5):
    // a) 非本页签隐藏; b) 本页签主动渲染 — loadZcodeQuota 仅统计页分支会调,
    // 冷启动直达 zcode 页签时 zcodeQuotaLast 为 null, 必须主动拉取
    $("zcode-quota").hidden = state.channel !== "zcode";
    if (state.channel === "zcode") {
      zcodeQuotaLast ? renderZcodeQuota(zcodeQuotaLast) : loadZcodeQuota();
    }
```

- [ ] **Step 2: applyLang 补渠道条件（Review 第 2 轮备注 1）**

app.js:350：

```js
  if (zcodeQuotaLast && state.page === "home" && state.channel === "zcode") renderZcodeQuota(zcodeQuotaLast);
```

- [ ] **Step 3: loadReportAll 并入 zcode 额度**

`loadReportAll`（app.js:2032-2038）的 Promise.all 增加第四个请求并传入渲染（`.catch(() => null)` 容错，ZCode 不可用不影响配额条其余渠道）：

```js
    const [w, rows, ov, zq] = await Promise.all([
      api(`/api/report/windows`),
      api(`/api/report/channels?range=${range}`),
      api(`/api/accounts/overview`),                    // R1: 摘要条数据并入同一并发 (T9 renderQuotaBar)
      api(`/api/zcode/quota`).catch(() => null),        // 问题5: ZCode 额度并入配额条, 失败不出卡
    ]);
    renderWindows(w, rows.rows.some((r) => r.estimated));
    renderQuotaBar(ov.accounts, zq);
```

- [ ] **Step 4: 后端预热（Review 第 1 轮 P2 项：/api/zcode/quota 进程首次同步调用上限 15s）**

`app/server.py` 在 `_ensure_zcode_quota_async`（839 行 `threading.Thread(...).start()` 之后、函数定义结束处）加：

```python
def zcode_quota_warmup() -> None:
    """启动预热 ZCode 额度缓存 (后台线程): 免前端首个 /api/zcode/quota
    走 _zcode_quota_payload 的同步首采路径 (上限 15s)."""
    _ensure_zcode_quota_async()
```

`app/main.py:466`（claude 预热线程之后）加：

```python
    # ZCode 额度缓存启动预热 (问题5): 首个 /api/zcode/quota 请求免 15s 同步首采
    threading.Thread(target=server.zcode_quota_warmup, daemon=True, name="gousage-zcode-quota-warm").start()
```

- [ ] **Step 5: 语法检查 + 全量回归**

Run: `node --check app/web/app.js && python -m pytest tests/ -q`
Expected: 语法通过；338 passed

- [ ] **Step 6: Commit（需人工确认后执行）**

```bash
git add app/web/app.js app/server.py app/main.py
git commit -m "fix: GLM Coding Plan 额度卡归属 zcode 页签+并入各渠道配额+启动预热 (问题5)"
```

---

### Task 9: 本地渠道整块隐藏配额（问题 6）

**Files:**
- Modify: `app/web/app.js:634-641`（renderQuotaSingle）、`app.js:118` 与 `:230`（删除 localNoQuota i18n 键）

**Interfaces:** 无新接口。`localNoQuota` 键全库仅 renderQuotaSingle 一处引用，删除键与引用（grep 确认过）。

- [ ] **Step 1: renderQuotaSingle 状态机（含 Review 第 1 轮 P1 项的复位配套）**

`renderQuotaSingle`（app.js:634-641）整体替换：

```js
function renderQuotaSingle(accounts) {
  const box = $("usage-blocks");
  if (!accounts.length) {   // 本地渠道 (zcode/claudecode/dsh) 无账号 -> 整块隐藏, 不显示占位文字 (问题6)
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;       // 复位: hidden 不随 innerHTML 更新自动恢复, 漏掉会让有账号页签配额卡消失
  box.innerHTML = accounts.map((a) =>
    `<div class="acct-quota"><div class="acct-name">${escapeHtml(a.name)}</div><div class="acct-quota-body" id="aq-${a.id}"></div></div>`).join("");
  accounts.forEach((a) => renderUsageBlocks(a.quota, $(`aq-${a.id}`)));
}
```

- [ ] **Step 2: 删除 i18n 键**

`app/web/app.js:118`（zh）删除 `localNoQuota: "本地渠道，无配额概念",`；`:230`（en）删除 `localNoQuota: "Local source — no quota",`。

- [ ] **Step 3: 确认无残留引用 + 语法检查 + 全量回归**

Run: `grep -n "localNoQuota" app/web/app.js && node --check app/web/app.js && python -m pytest tests/ -q`
Expected: grep 无输出（exit 1 会让 && 短路——分两条跑：先 grep 预期无结果，再 check + pytest 338 passed）

- [ ] **Step 4: Commit（需人工确认后执行）**

```bash
git add app/web/app.js
git commit -m "fix: 本地渠道整块隐藏配额区, 移除占位文案 (问题6)"
```

---

### Task 10: 全量验证 + 手动验收

**Files:** 无代码改动（只读验证）。

- [ ] **Step 1: 自动化全量**

Run: `python -m pytest tests/ -q && node --check app/web/app.js`
Expected: 全部 passed（338：334 基线 + Task 1 新增 2 条 + Task 2 新增 2 条）；语法通过

- [ ] **Step 2: 性能验证（可选但推荐）**

对真实数据目录跑 EXPLAIN 确认表达式索引命中（复制诊断报告「验证动作」的 Python 片段），并启动应用人工感受切换渠道流畅度。

- [ ] **Step 3: 手动验收清单（启动应用逐项核对）**

| # | 操作 | 预期 |
|---|------|------|
| 1 | commandcode 页签 | 滚动/每周/每月三卡一行三列横排（问题1） |
| 2 | 全部渠道页签 | 各渠道配额为色点+数值+进度条小卡组，无 `▓▓▓░` 字符（问题2） |
| 3 | 全部渠道页签图表 | bai 亮琥珀、claudecode 亮玫红，环形图有卡片色描边（问题3） |
| 4 | 快速连续切换渠道页签 | 无秒级无响应；切换瞬间旧内容降透明度，到达后更新；连点无内容闪烁回退（问题4） |
| 5 | bai / commandcode / claudecode 页签 | 无 GLM Coding Plan 卡；zcode 页签有且各渠道配额含 zcode 卡（问题5） |
| 6 | claudecode / dsh 页签 | 顶部无「本地渠道，无配额概念」，无空配额容器（问题6） |
| 7 | commandcode 页签账期汇总 | 账号名通栏省略显示（悬停见全名），请求/Token/费用/成功率一行四卡对齐（问题7） |
| 8 | 语言切换（中文↔English）×5 次 | zcode 页签外不出现 GLM 卡残留（applyLang 条件回归点） |
| 9 | 设置页切换账号 → 回首页 | 配额条/概览反映新账号（overview 缓存失效回归点） |
| 10 | 手动「立即全量同步」完成后切渠道 | 数据含新同步记录（sync 失效回归点） |

- [ ] **Step 4: 汇报**

向用户汇报验收结果；全部通过后由**人工确认**是否执行各任务积压的 git commit。

---

## 自审记录（Self-Review）

1. **Spec 覆盖**：v2 方案表 7 行 → Task 1(4①)/2(4②)/3(4③④⑤)/4(1)/5(7)/6(2)/7(3)/8(5)/9(6)；Review 备注 1→Task 8 Step 2、备注 2→Task 1 取舍注释+Task 2 缓存掩盖、备注 3→Task 2 失效点表（含 switch/rename/delete/logout/sync 五处，delete/logout 覆盖账号删除退出场景）。无遗漏。
2. **占位符扫描**：所有代码步骤给出完整可粘贴代码；无 TBD/类似 Task N 引用；Task 6→8 的签名依赖已显式声明。
3. **类型一致性**：`renderQuotaBar(accounts, zdata = null)` 定义（Task 6）与调用（Task 8 Step 3）一致；`_invalidate_overview_cache` 定义（Task 2）与测试引用一致；`zcode_quota_warmup` 定义（Task 8 Step 4）与 main.py 调用一致。

---

## Review 记录

### 第 1 轮（2026-09-05）：不通过 → 已修订

对计划逐任务核验，关键断言均以实测验证。发现 3 项问题：

| 级别 | 任务 | 问题 | 证据 | 修订 |
|------|------|------|------|------|
| P1（路线错误） | Task 1 | `substr(datetime(col,'localtime'),1,10)` 表达式索引**被 SQLite 拒绝**：`'localtime'` 为非确定性修饰符，`CREATE INDEX` 直接报 `OperationalError: non-deterministic use of datetime() in an index`，方案在真实库上第一步就会失败 | 内存库实测复现 | Task 1 整体重写为路线 C：`datetime(col)`（无修饰符，确定性）表达式索引 + `_report_range_sql` 改返回 `(sql, params)` + Python 端 `_local_day_utc_start()` 计算本地零点的 UTC 边界。路线 C 已实测：索引可建、三种真实存储格式标准化一致、等值/范围谓词均走 `SEARCH USING INDEX`、`daily_stats` 型走 COVERING INDEX |
| P1（必现破版） | Task 6 | `.quota-bar` 类选择器命中**外层卡片**——HTML 为 `<div class="card quota-bar"><div class="card-h">…</div><div id="quota-bar">`，外层 card 变 grid 后标题与卡组并排成两列 | index.html:69 | 选择器改 `#quota-bar` 并注明原因 |
| P2（测试可靠性） | Task 2 | 测试未隔离外部副作用：`_ensure_quota_async` 会对测试账号起后台线程发真实网络请求；`_fetch_usd_cny` 进程首次未命中缓存会 urlopen（10s 超时） | server.py:1202/1228 调用链 | 测试补 `_no_side_effect` fixture 打桩两函数 |
| P3（表述） | Task 1 Step 2 | 预期 FAIL 描述不准（str 可迭代，实际报 `too many values to unpack`） | Python 语义 | 已修正 |

其余核验通过的项：Task 1 v2 的 9 处 `_report_range_sql` 调用点全覆盖（2124/2129/2134/2217/2225/2305/2315/2431/2445/2459）；`daily_stats`/`today_trend`/`report_hourly` 谓词改造与原语义逐日等价（含 DST，Python `astimezone` 处理）；UNION ALL 参数按段顺序连接的陷阱已在 3d/3k 显式处理；Task 3 的 swapping 状态机在「单渠道→全部→响应到达」时序下无残留；Task 5 选择器限定不波及 renderQuotaSingle；Task 8 预热函数 `_ensure_zcode_quota_async` 无前置条件（实测确认直接后台刷新）；Task 9 复位配套完整。

### 第 2 轮（2026-09-05）：通过

复核修订后计划：① 路线 C 的 11 处改造点（3a-3k）与 db.py 实际代码逐段比对，签名变化 `_report_range_sql -> tuple` 的所有消费方均已列出；② `daily_stats` 原 `-N days` 语义（含 N+1 天的宽松窗口）在新实现中保持不变——只改谓词形式不改语义；③ Task 2 打桩后测试零网络/零线程依赖；④ `#quota-bar` 作用域下 `.qb-*` 子类无命名冲突；⑤ 各任务期望测试数递进一致（334→336→338）。**路线 C 与原谓词的语义等价性实测**：造 96 行覆盖前天/昨天/今天各时刻（含 UTC 边界小时），today/yesterday/7d 三档新谓词与原 `substr(datetime(col,'localtime'))` 谓词命中数逐一相同（48/72/96）。无新增问题，**判定正确且可执行**。

### 第 3 轮（2026-09-05）：通过

交叉验证第 2 轮结论：① Task 1 路线 C 的语义等价性再次独立推演——`substr(datetime(col,'localtime'),1,10) >= date('now','localtime','-N days')` ⟺ `datetime(col) >= 本地N天前零点的UTC`，两式在任意时区/DST 下逐日等价，参数化后 SQLite 标准化字符串比较与时间比较一致；② 执行顺序依赖唯一（Task 6 签名 → Task 8 消费），与任务编号顺序一致；③ 手动验收清单覆盖 7 问题 + 3 回归点，无缺项。**连续第 2 次通过，review 终止。**
