# 用量统计页分层视图实施计划（回退存档版）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**文档说明**：本文件为 2026-09-09 从误删中恢复的存档（内容为评审通过版）。**该计划的代码实施已被用户要求回退**，回退执行见 [20260909-stats-layered-view-rollback.md](20260909-stats-layered-view-rollback.md)。本文档仅作历史参考，不代表当前代码方向。

**Goal:** 将 page-stats（用量统计页）重构为"全局汇总 + 占比条导航 + 数据源手风琴面板 + 空源收纳区"的分层视图，替换现有的全局卡片 + 四个本地渠道堆叠区块。

**Architecture:** 后端新增 `/api/stats/sources`（薄封装复用 `db.report_channels`）、`/api/stats/sources/{id}/detail`（远程账号/Top Keys/模型，本地 Provider/模型，DSH 今日）、`/api/stats/models`（全渠道模型用量）三组端点；前端重写 page-stats 的 DOM 与加载逻辑，移除 ZCode/DSH/Claude Code/Codex 四个独立区块，全局图表（Token 构成/模型用量/用量趋势）改为全渠道口径并默认折叠。

**Tech Stack:** Python 3.12（stdlib http.server + sqlite3）、pytest、原生 JS（无框架）+ Chart.js、CSS 变量暗色主题。

**Spec:** [doc/20260907-usage-stats-layered-view.md](20260907-usage-stats-layered-view.md)（评审通过版）；交互原型 [doc/20260908-stats-display-mockup.html](20260908-stats-display-mockup.html)

## Global Constraints

- range 参数白名单（`server.py:1219` `_RANGE_WHITELIST`）：`today / yesterday / 7d / 30d / all`；非法值回落 `"7d"`（本视图默认）。
- 渠道清单 7 个：`opencode / bai / commandcode`（远程，`usage_records JOIN accounts` 取 `accounts.source` 判定）、`zcode / claudecode / codex`（本地镜像表）、`dsh`（无表，文件型仅今日）。
- 费用口径三态：`cost_available=true`（实际）/ `estimated=true`（估算徽标）/ `cost_available=false`（codex、dsh，费用恒 `null` 不是 0）。
- 命中率口径（加权）：`SUM(cache_read) / SUM(cache_read + input) * 100`，分母为 0 时 `null`，禁止简单平均。
- DSH 仅 `range=today` 进主列表（requests/cost 不虚报）；其余范围进 `empty_sources`，reason="仅提供今日数据"。
- 不引入 hash 路由；跳转记录页用 `switchPage("records")` + 预设 `state.records.source`。
- 汇总聚合**必须复用** `db.report_channels(range_)`，禁止另写平行的跨渠道聚合 SQL。
- 测试模式：pytest fixture 重定向 `db.data_dir` 到 `tmp_path` 并重置 `db._DB = None`（参照 `tests/test_report_api.py::tmp_report_db`）。
- 前端复用现有辅助：`t()` `fmtTokens()` `fmtInt()` `fmtMoney()` `escapeHtml()` `api()` `switchPage()` `syncSourceFilter()` `setChartEmpty()`。
- i18n：所有新文案键必须 zh/en 双语（`tests/test_i18n_consistency.py` 会校验）。
- Python 解释器：`D:\.pyenv\pyenv-win\versions\3.12.10\python.exe`（或 `python`）；测试命令 `python -m pytest tests/xxx.py -v`。
- 修改完成后必须 `python -m py_compile app/server.py app/db.py` 编译通过。

---

### Task 1: 后端 `_stats_sources_payload()` 核心聚合

**Files:**
- Modify: `app/server.py`（在 `_RANGE_WHITELIST` 定义之后，约 1221 行处新增）
- Test: `tests/test_stats_sources.py`（新建）

**Interfaces:**
- Consumes: `db.report_channels(range_) -> list[dict]`，行字段：`channel/tokens/input/output/cache_read/cache_write/reasoning/requests/cost/cost_available/cost_partial/request_count_exact/data_since/estimated`；`_RANGE_WHITELIST`。
- Produces: `_stats_sources_payload(range_param: str) -> dict`，返回 `{"range", "sources": [...], "totals": {...}}`；sources 行字段见下方代码（Task 2/6/7 依赖此形状）。**注意：此函数不含 DSH 与 empty_sources（Task 2 追加）。**

- [ ] **Step 1: 写失败测试**

新建 `tests/test_stats_sources.py`：

```python
"""用量统计页数据源分层视图 API 测试: /api/stats/sources 汇总与 detail."""
from __future__ import annotations

import pytest

from app import db, server


@pytest.fixture()
def tmp_stats_db(tmp_path, monkeypatch):
    """独立临时库 (与 test_report_api.tmp_report_db 同型)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path


def _now_utc_iso() -> str:
    """当前时刻 UTC ISO (带 Z): usage_records.created_at 为 UTC 口径 (SQLite datetime()
    按 UTC 解析, 同 test_report_api._to_utc_iso; 用本地 naive 串在东八区 16:00 后会
    掉出 today 窗口)。"""
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _seed_remote(source="opencode", key_id="k1", cost=1.0, inp=100, out=50, cr=40,
                 created=None):
    """种 1 条 usage_records; 账号按 source 复用 (不存在才创建)。created 缺省为当前
    UTC (落在 today/7d/30d 任意窗口, 测试与运行日期无关)。"""
    created = created or _now_utc_iso()
    conn = db.get_db()
    row = conn.execute("SELECT id FROM accounts WHERE source = ? LIMIT 1", (source,)).fetchone()
    if row:
        aid = row["id"]
    else:
        cur = conn.execute(
            "INSERT INTO accounts (name, workspace_id, token, source, created_at, updated_at)"
            " VALUES (?, 'ws', 'tok', ?, '2026-01-01', '2026-01-01')",
            (f"acc-{source}", source),
        )
        aid = cur.lastrowid
    conn.execute(
        "INSERT INTO usage_records (usg_id, created_at, model, provider, input_tokens,"
        " output_tokens, reasoning_tokens, cache_read_tokens, cache_write_5m_tokens,"
        " cache_write_1h_tokens, cost_raw, cost_usd, key_id, session_id, plan, synced_at,"
        " account_id) VALUES (?, ?, 'm', 'p', ?, ?, 0, ?, 0, 0, ?, ?, 's', 'p', '2026-09-07', ?)",
        (f"u-{source}-{key_id}-{cost}", created, inp, out, cr, int(cost * 1e8), cost, key_id, aid),
    )
    conn.commit()


def test_stats_sources_basic_shape(tmp_stats_db):
    _seed_remote("opencode", cost=2.0)
    _seed_remote("bai", cost=1.0)
    payload = server._stats_sources_payload("all")
    assert payload["range"] == "all"
    ids = [s["source_id"] for s in payload["sources"]]
    assert ids[:2] == ["opencode", "bai"]          # 费用降序
    oc = payload["sources"][0]
    assert oc["source_type"] == "remote"
    assert oc["cost_available"] is True and oc["estimated"] is False
    assert oc["total_cost_usd"] == 2.0
    assert oc["pct_cost"] == pytest.approx(2.0 / 3.0 * 100)
    assert oc["pct_tokens"] == pytest.approx(150 / 300 * 100)
    # 命中率加权: cr/(cr+inp) = 40/140
    assert oc["hit_rate"] == pytest.approx(40 / 140 * 100)


def test_stats_sources_invalid_range_falls_back(tmp_stats_db):
    payload = server._stats_sources_payload("bogus")
    assert payload["range"] == "7d"


def test_stats_sources_totals_weighted_hit_rate(tmp_stats_db):
    _seed_remote("opencode", key_id="a", inp=100, cr=50)   # 50/150
    _seed_remote("bai", key_id="b", inp=900, cr=50)        # 50/950
    payload = server._stats_sources_payload("all")
    # 加权 = 100/1150 ≈ 8.7%; 简单平均 ≈ 19.4% (必须不等于)
    assert payload["totals"]["hit_rate"] == pytest.approx(100 / 1150 * 100)
    assert payload["totals"]["total_cost_usd"] == pytest.approx(2.0)
    # Token 构成 (全局图表 Token 构成面板消费)
    for k in ("total_input_tokens", "total_output_tokens", "total_reasoning_tokens",
              "total_cache_read_tokens", "total_cache_write_tokens"):
        assert k in payload["totals"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stats_sources.py -v`
Expected: FAIL，`AttributeError: module 'app.server' has no attribute '_stats_sources_payload'`

- [ ] **Step 3: 实现 `_stats_sources_payload()`**

`app/server.py` 在 `_RANGE_WHITELIST = (...)` 行之后新增：

```python
# ---------------------------------------------------------------------------
# 用量统计页数据源分层视图 (GET /api/stats/sources*; 方案 20260907-usage-stats-layered-view)
# 汇总复用 db.report_channels (与首页渠道明细同口径), 仅补充占比/排序/totals。
# ---------------------------------------------------------------------------

_STATS_SOURCE_NAMES = {
    "opencode": "OpenCode", "bai": "BAI", "commandcode": "CommandCode",
    "zcode": "ZCode", "claudecode": "Claude Code", "codex": "Codex", "dsh": "DSH",
}
_STATS_REMOTE_SOURCES = ("opencode", "bai", "commandcode")
_STATS_LOCAL_TABLE_SOURCES = ("zcode", "claudecode", "codex")
_STATS_ALL_SOURCES = ("opencode", "bai", "commandcode", "zcode", "claudecode", "codex", "dsh")


def _weighted_hit_rate(cache_read, input_) -> float | None:
    """命中率加权口径: cache_read / (cache_read + input) * 100; 分母为 0 → None。"""
    cr, inp = cache_read or 0, input_ or 0
    if cr + inp <= 0:
        return None
    return cr * 100.0 / (cr + inp)


def _stats_sources_payload(range_param: str) -> dict[str, Any]:
    """GET /api/stats/sources 数据组装 (纯函数便于测试)。不含 DSH 与 empty_sources,
    由 _stats_sources_with_dsh 追加 (DSH 文件型仅今日, 非纯函数)。"""
    range_ = range_param if range_param in _RANGE_WHITELIST else "7d"
    rows = db.report_channels(range_)
    sources: list[dict[str, Any]] = []
    for r in rows:
        ch = r["channel"]
        sources.append({
            "source_id": ch,
            "source_name": _STATS_SOURCE_NAMES.get(ch, ch),
            "source_type": "remote" if ch in _STATS_REMOTE_SOURCES else "local",
            "request_count": r["requests"],
            "request_count_exact": bool(r["request_count_exact"]),
            "total_tokens": r["tokens"] or 0,
            "total_cost_usd": (r["cost"] if r["cost_available"] else None),
            "cost_available": bool(r["cost_available"]),
            "estimated": bool(r["estimated"]),
            "hit_rate": _weighted_hit_rate(r["cache_read"], r["input"]),
            "_input": r["input"] or 0,
            "_cache_read": r["cache_read"] or 0,
        })
    cost_pool = sum(s["total_cost_usd"] or 0 for s in sources if s["cost_available"])
    tok_pool = sum(s["total_tokens"] for s in sources)
    for s in sources:
        s["pct_cost"] = (s["total_cost_usd"] / cost_pool * 100
                         if s["cost_available"] and cost_pool > 0 else None)
        s["pct_tokens"] = (s["total_tokens"] / tok_pool * 100) if tok_pool > 0 else 0.0
    # 费用可用按费用降序在前; 不可用按 Token 降序在后
    sources.sort(key=lambda s: (not s["cost_available"],
                                -(s["total_cost_usd"] or 0), -s["total_tokens"]))
    totals = {
        "request_count": sum(s["request_count"] or 0 for s in sources),
        "total_tokens": tok_pool,
        "total_cost_usd": cost_pool,  # 仅费用可用渠道之和 (codex 费用未知不计入)
        "hit_rate": _weighted_hit_rate(sum(s["_cache_read"] for s in sources),
                                       sum(s["_input"] for s in sources)),
        "total_input_tokens": sum(s["_input"] for s in sources),
        "total_output_tokens": sum((r["output"] or 0) for r in rows),
        "total_reasoning_tokens": sum((r["reasoning"] or 0) for r in rows),
        "total_cache_read_tokens": sum(s["_cache_read"] for s in sources),
        "total_cache_write_tokens": sum((r["cache_write"] or 0) for r in rows),
    }
    for s in sources:
        del s["_input"], s["_cache_read"]
    return {"range": range_, "sources": sources, "totals": totals}
```

- [ ] **Step 4: 跑测试确认通过 + 编译**

Run: `python -m pytest tests/test_stats_sources.py -v && python -m py_compile app/server.py`
Expected: 3 passed；编译无输出

- [ ] **Step 5: 跑 report 回归**

Run: `python -m pytest tests/test_report_api.py -v`
Expected: 全部通过（本任务未改动既有逻辑）

---

### Task 2: DSH 今日并入 + empty_sources + `/api/stats/sources` 路由

**Files:**
- Modify: `app/server.py`（Task 1 代码块后追加函数；`_handle_api` 中注册路由）
- Test: `tests/test_stats_sources.py`

**Interfaces:**
- Consumes: Task 1 `_stats_sources_payload()`；`dsh_api.get_dsh_usage() -> {"found": bool, "today": {"input","output","reasoning","cache",...}, ...}`（参照 `_report_channels_response` 的 DSH 并入写法，server.py:1335 起）；`_json_response(handler, payload)`。
- Produces: `_stats_sources_with_dsh(range_, payload) -> dict`（追加 dsh 行与 `empty_sources` 键）；HTTP `GET /api/stats/sources?range=`。

- [ ] **Step 1: 写失败测试（追加到 tests/test_stats_sources.py）**

```python
def _mock_dsh(monkeypatch, inp=50, out=20, rea=0):
    from app import dsh_api
    monkeypatch.setattr(dsh_api, "get_dsh_usage", lambda: {
        "found": True, "today": {"input": inp, "output": out, "reasoning": rea, "cache": 0},
        "updated_at": "2026-09-08T10:00:00"})


def test_stats_sources_dsh_today_merged(tmp_stats_db, monkeypatch):
    _seed_remote("opencode", cost=1.0)   # created 缺省=当前 UTC, 必落 today 窗口
    _mock_dsh(monkeypatch)
    payload = server._stats_sources_with_dsh("today", server._stats_sources_payload("today"))
    dsh = [s for s in payload["sources"] if s["source_id"] == "dsh"]
    assert len(dsh) == 1
    assert dsh[0]["request_count"] is None and dsh[0]["total_cost_usd"] is None
    assert dsh[0]["cost_available"] is False
    assert dsh[0]["total_tokens"] == 70
    # opencode 在 today 有数据: 费用可用组在前, dsh 垫底
    assert payload["sources"][0]["source_id"] == "opencode"
    assert payload["sources"][-1]["source_id"] == "dsh"
    # dsh 并入后 pct_tokens 全量按新分母 (含 dsh) 重算, 口径与 totals 一致
    oc = payload["sources"][0]
    assert oc["pct_tokens"] == pytest.approx(150 / 220 * 100)
    assert dsh[0]["pct_tokens"] == pytest.approx(70 / 220 * 100)


def test_stats_sources_dsh_non_today_goes_empty(tmp_stats_db, monkeypatch):
    _seed_remote("opencode", cost=1.0)
    _mock_dsh(monkeypatch)
    payload = server._stats_sources_with_dsh("7d", server._stats_sources_payload("7d"))
    assert all(s["source_id"] != "dsh" for s in payload["sources"])
    dsh_empty = [e for e in payload["empty_sources"] if e["source_id"] == "dsh"]
    assert dsh_empty and dsh_empty[0]["reason"] == "仅提供今日数据"


def test_stats_sources_empty_sources_cover_all_channels(tmp_stats_db):
    payload = server._stats_sources_with_dsh("7d", server._stats_sources_payload("7d"))
    ids = {e["source_id"] for e in payload["empty_sources"]}
    assert ids == set(server._STATS_ALL_SOURCES)          # 空库: 7 渠道全部进收纳区
    assert all(e["reason"] for e in payload["empty_sources"])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stats_sources.py -v`
Expected: FAIL，`AttributeError: ... '_stats_sources_with_dsh'`

- [ ] **Step 3: 实现 `_stats_sources_with_dsh()` + 路由**

Task 1 代码块后追加：

```python
def _stats_sources_with_dsh(range_: str, payload: dict[str, Any]) -> dict[str, Any]:
    """DSH 无历史表: range=today 并入主列表 (tokens=input+output+reasoning,
    requests/cost 不虚报); 其余范围进 empty_sources。empty_sources 覆盖
    主列表未出现的全部 7 渠道 (含无账号远程渠道, 保留渠道发现性)。"""
    dsh = dsh_api.get_dsh_usage()
    if range_ == "today" and dsh.get("found"):
        t = dsh.get("today") or {}
        tok = (t.get("input") or 0) + (t.get("output") or 0) + (t.get("reasoning") or 0)
        if tok > 0:
            payload["sources"].append({
                "source_id": "dsh", "source_name": _STATS_SOURCE_NAMES["dsh"],
                "source_type": "local", "request_count": None, "request_count_exact": False,
                "total_tokens": tok, "total_cost_usd": None, "cost_available": False,
                "estimated": False, "hit_rate": None, "pct_cost": None, "pct_tokens": 0.0,
            })
            payload["totals"]["total_tokens"] += tok
            payload["totals"]["total_input_tokens"] += t.get("input") or 0
            payload["totals"]["total_output_tokens"] += t.get("output") or 0
            payload["totals"]["total_reasoning_tokens"] += t.get("reasoning") or 0
            # dsh 并入后分母变化: 全量重算 pct_tokens, 与 totals 口径一致 (占比条 flex 权重同源)
            pool = payload["totals"]["total_tokens"]
            for s in payload["sources"]:
                s["pct_tokens"] = (s["total_tokens"] / pool * 100) if pool > 0 else 0.0
    present = {s["source_id"] for s in payload["sources"]}
    payload["empty_sources"] = [
        {"source_id": c, "source_name": _STATS_SOURCE_NAMES[c],
         "reason": "仅提供今日数据" if c == "dsh" and range_ != "today" else "所选范围无数据"}
        for c in _STATS_ALL_SOURCES if c not in present
    ]
    return payload
```

`_handle_api` 中（`/api/report/channels` 路由附近）注册：

```python
    if route == "/api/stats/sources" and method == "GET":
        payload = _stats_sources_payload(query.get("range", ["7d"])[0])
        _json_response(handler, _stats_sources_with_dsh(payload["range"], payload))
        return
```

- [ ] **Step 4: 跑测试确认通过 + 编译**

Run: `python -m pytest tests/test_stats_sources.py -v && python -m py_compile app/server.py`
Expected: 6 passed

---

### Task 3: 远程渠道详情接口（账号分布 + Top Keys + 模型用量）

**Files:**
- Modify: `app/db.py`（`report_channels` 附近新增 3 个查询函数）
- Modify: `app/server.py`（`_remote_source_detail()` + 详情路由）
- Test: `tests/test_stats_sources.py`

**Interfaces:**
- Consumes: `db._report_range_sql(range_, ts_col) -> (sql, params)`；`db.get_key_names() -> dict[key_id, 显示名]`（server.py:394/1743 已有用法）。
- Produces: `db.source_account_stats(source, range_)`、`db.source_key_stats(source, range_, limit=5)`、`db.source_model_stats(source, range_)`；server `_remote_source_detail(source, range_param) -> {"source_id","range","accounts","top_keys","models"}`。详情路由形状：`/api/stats/sources/{source_id}/detail`（Task 4 复用同一路由注册）。

- [ ] **Step 1: 写失败测试**

```python
def test_remote_source_detail(tmp_stats_db):
    _seed_remote("opencode", key_id="k1", cost=2.0)
    _seed_remote("opencode", key_id="k2", cost=1.0)
    _seed_remote("bai", key_id="k3", cost=5.0)               # 不应混入 opencode 详情
    db.save_key_names({"k1": "生产环境"})
    detail = server._remote_source_detail("opencode", "all")
    assert detail["source_id"] == "opencode"
    assert len(detail["accounts"]) == 1                       # 同账号两条记录合并
    assert detail["accounts"][0]["requests"] == 2
    assert detail["accounts"][0]["percentage"] == pytest.approx(100.0)
    names = [k["key_name"] for k in detail["top_keys"]]
    assert names[0] == "生产环境" and names[1] == "k2"        # 无映射回退 key_id
    assert detail["top_keys"][0]["cost"] == 2.0               # 按费用降序
    assert any(k["key_id"] == "k3" for k in detail["top_keys"]) is False
    assert detail["models"][0]["model"] == "m"
    assert detail["models"][0]["percentage"] == pytest.approx(100.0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stats_sources.py::test_remote_source_detail -v`
Expected: FAIL

- [ ] **Step 3: 实现 db 层 3 个查询函数**

`app/db.py` 在 `report_channels` 函数之后新增：

```python
def source_account_stats(source: str, range_: str) -> list[dict[str, Any]]:
    """远程渠道账号分布 (统计页数据源详情): 按 account 分组, 费用降序。"""
    range_sql, params = _report_range_sql(range_, "r.created_at")
    rows = get_db().execute(
        f"SELECT r.account_id, a.name AS account_name, COUNT(*) AS requests,"
        f" SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) AS tokens,"
        f" SUM(r.cost_usd) AS cost"
        f" FROM usage_records r JOIN accounts a ON a.id = r.account_id"
        f" WHERE {range_sql} AND {_report_channels_expr()} = ?"
        f" GROUP BY r.account_id ORDER BY cost DESC",
        [*params, source],
    ).fetchall()
    return [dict(r) for r in rows]


def source_key_stats(source: str, range_: str, limit: int = 5) -> list[dict[str, Any]]:
    """远程渠道 Top Keys (按费用降序; key_id 空归 ''), 超出 limit 的并入 '其他' 由
    server 层处理 —— 本函数只返回 limit+1 行供截断判断。"""
    range_sql, params = _report_range_sql(range_, "r.created_at")
    rows = get_db().execute(
        f"SELECT COALESCE(r.key_id, '') AS key_id, COUNT(*) AS requests,"
        f" SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) AS tokens,"
        f" SUM(r.cost_usd) AS cost"
        f" FROM usage_records r JOIN accounts a ON a.id = r.account_id"
        f" WHERE {range_sql} AND {_report_channels_expr()} = ?"
        f" GROUP BY key_id ORDER BY cost DESC LIMIT ?",
        [*params, source, limit + 1],
    ).fetchall()
    return [dict(r) for r in rows]


def source_model_stats(source: str, range_: str) -> list[dict[str, Any]]:
    """远程渠道模型用量 (tokens 降序)。"""
    range_sql, params = _report_range_sql(range_, "r.created_at")
    rows = get_db().execute(
        f"SELECT r.model, COUNT(*) AS requests,"
        f" SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) AS tokens"
        f" FROM usage_records r JOIN accounts a ON a.id = r.account_id"
        f" WHERE {range_sql} AND {_report_channels_expr()} = ?"
        f" GROUP BY r.model ORDER BY tokens DESC",
        [*params, source],
    ).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 4: 实现 server 层 `_remote_source_detail()` + 详情路由**

`app/server.py` Task 2 代码块后：

```python
def _remote_source_detail(source: str, range_param: str) -> dict[str, Any]:
    """GET /api/stats/sources/{远程渠道}/detail: 账号分布 + Top Keys (前5+其他) + 模型用量。"""
    range_ = range_param if range_param in _RANGE_WHITELIST else "7d"
    accounts = db.source_account_stats(source, range_)
    keys = db.source_key_stats(source, range_)
    models = db.source_model_stats(source, range_)
    key_names = db.get_key_names()
    acc_cost = sum(a["cost"] or 0 for a in accounts)
    for a in accounts:
        a["percentage"] = (a["cost"] / acc_cost * 100) if acc_cost > 0 else 0.0
    if len(keys) > 5:  # 第 6 行起并入 "其他"
        rest = keys[5:]
        keys = keys[:5] + [{
            "key_id": None, "requests": sum(k["requests"] for k in rest),
            "tokens": sum(k["tokens"] for k in rest),
            "cost": sum(k["cost"] or 0 for k in rest),
            "key_name": f"其他 {len(rest)} 个 Key",
        }]
    key_cost = sum(k["cost"] or 0 for k in keys)
    for k in keys:
        if not k.get("key_name"):   # "其他" 行已带 key_name; 空 key_id → "未归属"
            k["key_name"] = key_names.get(k["key_id"] or "", k["key_id"] or "未归属")
        k["percentage"] = (k["cost"] / key_cost * 100) if key_cost > 0 else 0.0
    model_tokens = sum(m["tokens"] or 0 for m in models)
    for m in models:
        m["percentage"] = (m["tokens"] / model_tokens * 100) if model_tokens > 0 else 0.0
    return {"source_id": source, "range": range_,
            "accounts": accounts, "top_keys": keys, "models": models}
```

`_handle_api` 注册（Task 2 路由之后）：

```python
    if route.startswith("/api/stats/sources/") and route.endswith("/detail") and method == "GET":
        parts = route.split("/")          # ['', 'api', 'stats', 'sources', '{id}', 'detail']
        source_id = parts[4]
        range_param = query.get("range", ["7d"])[0]
        if source_id in _STATS_REMOTE_SOURCES:
            _json_response(handler, _remote_source_detail(source_id, range_param))
        elif source_id in _STATS_LOCAL_TABLE_SOURCES:
            _json_response(handler, _local_source_detail(source_id, range_param))   # Task 4
        elif source_id == "dsh":
            _json_response(handler, _dsh_source_detail())                            # Task 4
        else:
            _json_response(handler, {"error": "unknown source"}, 404)
        return
```

- [ ] **Step 5: 跑测试确认通过 + 编译**

Run: `python -m pytest tests/test_stats_sources.py -v && python -m py_compile app/server.py app/db.py`
Expected: 7 passed

---

### Task 4: 本地渠道详情接口（Provider/Channel + 模型）+ DSH 今日详情

**Files:**
- Modify: `app/db.py`（新增 2 个参数化查询函数）
- Modify: `app/server.py`（`_local_source_detail()`、`_dsh_source_detail()`）
- Test: `tests/test_stats_sources.py`

**Interfaces:**
- Consumes: 本地表列名——`zcode_usage(provider_id, provider_name, model_id, input_tokens, output_tokens, reasoning_tokens, cache_read_tokens, cost_raw, started_at)`；`claudecode_usage(channel, model, ..., 无 reasoning 参与 tokens 口径: input+output)`；`codex_usage(provider_id, model, total_tokens, cost 恒未知)`。费用换算 `SUM(cost_raw)/1e8`（同 `_report_metric_exprs`）。
- Produces: `db.local_provider_stats(source, range_)`、`db.local_model_stats(source, range_)`；`_local_source_detail(source, range_param) -> {"source_id","range","providers","models"}`；`_dsh_source_detail() -> {"source_id":"dsh","today":{...}}`。

- [ ] **Step 1: 写失败测试**

```python
def _seed_zcode(provider="glm", model="glm-5", tokens_in=60, tokens_out=40, cost_raw=int(0.5e8),
                started="2026-09-07T02:00:00Z"):
    conn = db.get_db()
    conn.execute(
        "INSERT INTO zcode_usage (id, started_at, session_id, provider_id, provider_name,"
        " model_id, status, input_tokens, output_tokens, reasoning_tokens,"
        " cache_write_tokens, cache_read_tokens, total_tokens, duration_ms, ttft_ms,"
        " cost_raw, synced_at) VALUES (?, ?, 's', ?, ?, ?, 'ok', ?, ?, 0, 0, 0, ?, 0, 0, ?, '2026-09-07')",
        (f"z-{provider}-{model}-{tokens_in}", started, provider, provider, model,
         tokens_in, tokens_out, tokens_in + tokens_out, cost_raw),
    )
    conn.commit()


def test_local_source_detail_zcode(tmp_stats_db):
    _seed_zcode("glm", "glm-5", tokens_in=80, cost_raw=int(0.8e8))   # tokens=120, 消除并列保证降序确定
    _seed_zcode("glm", "glm-4", cost_raw=int(0.2e8))
    _seed_zcode("kimi", "kimi-k3", cost_raw=int(0.5e8))
    detail = server._local_source_detail("zcode", "all")
    provs = [(p["provider_id"], p["percentage"]) for p in detail["providers"]]
    assert provs[0][0] == "glm" and provs[0][1] == pytest.approx(1.0 / 1.5 * 100)
    assert detail["providers"][0]["cost"] == pytest.approx(1.0)     # cost_raw/1e8
    models = [m["model"] for m in detail["models"]]
    assert models[0] == "glm-5"                                      # tokens 降序
    assert all(m["tokens"] for m in detail["models"])


def test_local_source_detail_codex_cost_unavailable(tmp_stats_db):
    conn = db.get_db()
    conn.execute(
        "INSERT INTO codex_usage (id, session_id, event_seq, event_mode, response_id,"
        " started_at, model, provider_id, input_tokens, output_tokens, cache_read_tokens,"
        " cache_write_tokens, reasoning_tokens, total_tokens, duration_ms, speed_tps,"
        " speed_source, request_count_exact, cost_available, cost_raw, file_path,"
        " model_revision_at, synced_at) VALUES ('x1', 's', 1, 'turn', 'r',"
        " '2026-09-07T02:00:00Z', 'gpt-5.3-codex', 'codex', 30, 20, 0, 0, 10, 60,"
        " 0, 0, '', 1, 0, NULL, 'f', 0, '2026-09-07')",
    )
    conn.commit()
    detail = server._local_source_detail("codex", "all")
    assert detail["providers"][0]["cost"] is None                    # 费用未知 = NULL
    assert detail["providers"][0]["percentage"] == pytest.approx(100.0)  # 费用不可用按 tokens 占比
    assert detail["models"][0]["tokens"] == 60


def test_dsh_source_detail(tmp_stats_db, monkeypatch):
    _mock_dsh(monkeypatch)
    detail = server._dsh_source_detail()
    assert detail["source_id"] == "dsh"
    assert detail["today"]["tokens"] == 70
    assert detail["today"]["cost_available"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stats_sources.py -v -k "local or dsh_source"`
Expected: FAIL

- [ ] **Step 3: 实现 db 层参数化查询**

`app/db.py` Task 3 函数之后：

```python
# 本地渠道详情维度映射: (表, 维度列, 模型列, tokens 表达式, cost 表达式或 None)
_LOCAL_SOURCE_TABLES = {
    "zcode": ("zcode_usage", "provider_id", "model_id",
              "input_tokens + output_tokens + reasoning_tokens", "SUM(cost_raw)/1e8"),
    "claudecode": ("claudecode_usage", "channel", "model",
                   "input_tokens + output_tokens", "SUM(cost_raw)/1e8"),
    "codex": ("codex_usage", "provider_id", "model", "total_tokens", None),
}


def local_provider_stats(source: str, range_: str) -> list[dict[str, Any]]:
    """本地渠道 Provider/Channel 分布 (统计页数据源详情); codex 费用恒 None。"""
    table, dim, _model, tok_expr, cost_expr = _LOCAL_SOURCE_TABLES[source]
    range_sql, params = _report_range_sql(range_, "started_at")
    cost_sel = f"{cost_expr} AS cost" if cost_expr else "NULL AS cost"
    rows = get_db().execute(
        f"SELECT COALESCE({dim}, '') AS provider_id, COUNT(*) AS requests,"
        f" SUM({tok_expr}) AS tokens, {cost_sel}"
        f" FROM {table} WHERE {range_sql}"
        f" GROUP BY {dim} ORDER BY tokens DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def local_model_stats(source: str, range_: str) -> list[dict[str, Any]]:
    """本地渠道模型用量 (tokens 降序)。"""
    table, _dim, model_col, tok_expr, _cost = _LOCAL_SOURCE_TABLES[source]
    range_sql, params = _report_range_sql(range_, "started_at")
    rows = get_db().execute(
        f"SELECT COALESCE({model_col}, '') AS model, COUNT(*) AS requests,"
        f" SUM({tok_expr}) AS tokens"
        f" FROM {table} WHERE {range_sql}"
        f" GROUP BY {model_col} ORDER BY tokens DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows]
```

注意：`_report_range_sql` 生成的时间条件作用于裸列名 `started_at`；本地三表时间列均为 `started_at`（zcode/claudecode/codex 一致），无需别名。

- [ ] **Step 4: 实现 server 层两个 detail 函数**

`app/server.py` Task 3 代码块后：

```python
def _local_source_detail(source: str, range_param: str) -> dict[str, Any]:
    """GET /api/stats/sources/{本地渠道}/detail: Provider/Channel 分布 + 模型用量。
    费用可用渠道 (zcode/claudecode) percentage 按费用; 费用不可用 (codex) 按 tokens。"""
    range_ = range_param if range_param in _RANGE_WHITELIST else "7d"
    providers = db.local_provider_stats(source, range_)
    models = db.local_model_stats(source, range_)
    cost_pool = sum(p["cost"] or 0 for p in providers)
    tok_pool = sum(p["tokens"] or 0 for p in providers)
    for p in providers:
        if p["cost"] is not None:
            p["percentage"] = (p["cost"] / cost_pool * 100) if cost_pool > 0 else 0.0
        else:  # codex: 费用恒未知, 按 tokens 占比 (前端条形才不为全 0)
            p["percentage"] = (p["tokens"] / tok_pool * 100) if tok_pool > 0 else 0.0
    model_tokens = sum(m["tokens"] or 0 for m in models)
    for m in models:
        m["percentage"] = (m["tokens"] / model_tokens * 100) if model_tokens > 0 else 0.0
    return {"source_id": source, "range": range_, "providers": providers, "models": models}


def _dsh_source_detail() -> dict[str, Any]:
    """DSH 仅今日汇总 (无历史表, 无下钻维度)。"""
    dsh = dsh_api.get_dsh_usage()
    t = dsh.get("today") or {}
    tok = (t.get("input") or 0) + (t.get("output") or 0) + (t.get("reasoning") or 0)
    return {"source_id": "dsh",
            "today": {"tokens": tok, "input": t.get("input") or 0,
                      "output": t.get("output") or 0, "reasoning": t.get("reasoning") or 0,
                      "cache_read": t.get("cache") or 0,
                      "cost_available": False, "request_count": None}}
```

Task 3 注册的路由已分派到这两个函数，无需再改路由。

- [ ] **Step 5: 跑测试确认通过 + 编译**

Run: `python -m pytest tests/test_stats_sources.py -v && python -m py_compile app/server.py app/db.py`
Expected: 10 passed

---

### Task 5: 全渠道模型用量接口 `/api/stats/models`（全局图表用）

**Files:**
- Modify: `app/db.py`（新增 `report_models`）
- Modify: `app/server.py`（`_stats_models_payload()` + 路由）
- Test: `tests/test_stats_sources.py`

**Interfaces:**
- Consumes: `db._report_range_sql`；本地三表映射 `_LOCAL_SOURCE_TABLES`（Task 4）；`usage_records` 远程三渠道。
- Produces: `db.report_models(range_) -> list[{"model","requests","tokens"}]`（四表 UNION，tokens 降序）；`GET /api/stats/models?range= -> {"range","models"}`。前端全局图表"模型用量"消费（Task 8）。

- [ ] **Step 1: 写失败测试**

```python
def test_stats_models_all_channels(tmp_stats_db):
    _seed_remote("opencode")                     # model='m', tokens=150
    _seed_zcode("glm", "glm-5")                  # tokens=100
    payload_models = server._stats_models_payload("all")["models"]
    by_model = {m["model"]: m["tokens"] for m in payload_models}
    assert by_model["m"] == 150 and by_model["glm-5"] == 100
    assert payload_models[0]["model"] == "m"     # tokens 降序
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_stats_sources.py::test_stats_models_all_channels -v`
Expected: FAIL

- [ ] **Step 3: 实现 `db.report_models()`**

`app/db.py` Task 4 函数之后：

```python
def report_models(range_: str) -> list[dict[str, Any]]:
    """全渠道模型用量 (统计页全局图表; 四表 UNION, tokens 降序)。
    DSH 无历史表不参与; claudecode tokens 口径 input+output (同 _report_metric_exprs)。"""
    segs: list[str] = []
    params: list[Any] = []
    sql, p = _report_range_sql(range_, "r.created_at")
    segs.append(f"SELECT r.model AS model, COUNT(*) AS requests,"
                f" SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) AS tokens"
                f" FROM usage_records r WHERE {sql} GROUP BY r.model")
    params += p
    for src, (table, _dim, model_col, tok_expr, _cost) in _LOCAL_SOURCE_TABLES.items():
        sql, p = _report_range_sql(range_, "started_at")
        segs.append(f"SELECT {model_col} AS model, COUNT(*) AS requests,"
                    f" SUM({tok_expr}) AS tokens FROM {table} WHERE {sql} GROUP BY {model_col}")
        params += p
    rows = get_db().execute(
        f"SELECT model, SUM(requests) AS requests, SUM(tokens) AS tokens"
        f" FROM ({' UNION ALL '.join(segs)}) GROUP BY model ORDER BY tokens DESC",
        params,
    ).fetchall()
    return [dict(r) for r in rows if r["model"]]
```

- [ ] **Step 4: 实现 server payload + 路由**

```python
def _stats_models_payload(range_param: str) -> dict[str, Any]:
    """GET /api/stats/models: 全渠道模型用量 (统计页全局图表)。"""
    range_ = range_param if range_param in _RANGE_WHITELIST else "7d"
    return {"range": range_, "models": db.report_models(range_)}
```

`_handle_api` 注册：

```python
    if route == "/api/stats/models" and method == "GET":
        _json_response(handler, _stats_models_payload(query.get("range", ["7d"])[0]))
        return
```

- [ ] **Step 5: 跑测试确认通过 + 编译 + report 回归**

Run: `python -m pytest tests/test_stats_sources.py tests/test_report_api.py -v && python -m py_compile app/server.py app/db.py`
Expected: 全部通过

---

### Task 6: index.html page-stats DOM 重构 + UI 契约测试更新

**Files:**
- Modify: `app/web/index.html:100-168`（page-stats 整段重写）
- Modify: `tests/test_codex_ui_contract.py`（codex-stats 区块 id 已移除，更新断言）

**Interfaces:**
- Consumes: 现有 page-stats 内 `stats-pills`、`stats-total-cards`、`stats-detail6`（Token 构成）、`mr-chart/mr-list`（模型用量）、`trend-chart`（用量趋势）的 id 与卡片结构。
- Produces: 新 DOM id 契约（Task 7/8 依赖）：`share-metric`、`share-bar`、`share-legend`、`share-note`、`stats-charts-panel`、`stats-charts-head`、`stats-charts-body`、`sources-container`、`empty-zone`、`empty-zone-head`、`empty-zone-title`、`empty-zone-body`。**移除 id**：`zcode-stats`、`dsh-stats`、`claudecode-stats`、`codex-stats` 及其内部全部 id（`zcode-kpis`、`zcode-prov-head/body`、`zcode-model-head/body`、`zcode-trend-chart`、`dsh-*`、`claudecode-*`、`codex-kpis`、`codex-prov-*`、`codex-model-*`、`codex-trend-chart` 等）。

- [ ] **Step 1: 更新 UI 契约测试（先失败）**

`tests/test_codex_ui_contract.py::test_codex_stats_nodes` 断言的旧 id 集合将被移除。改断言为新契约：

```python
def test_stats_layered_view_nodes():
    """统计页分层视图 DOM 契约: 占比条 + 数据源面板容器 + 收纳区 + 全局图表折叠面板."""
    p = Nodes()
    p.feed((ROOT / "app/web/index.html").read_text(encoding="utf-8"))
    expected = {"stats-total-cards", "share-metric", "share-bar", "share-legend",
                "share-note", "stats-charts-panel", "stats-charts-body",
                "sources-container", "empty-zone", "empty-zone-body"}
    missing = expected - p.ids
    assert not missing, f"index.html 缺少统计页分层视图节点: {missing}"
    removed = {"zcode-stats", "dsh-stats", "claudecode-stats", "codex-stats"}
    leaked = removed & p.ids
    assert not leaked, f"旧本地渠道区块应已移除: {leaked}"
```

（同时删除/替换原 `test_codex_stats_nodes`；该文件其余断言首页节点的用例不动。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_codex_ui_contract.py -v`
Expected: FAIL（缺新节点）

- [ ] **Step 3: 重写 page-stats 段**

`app/web/index.html` 第 100-168 行（`<!-- ============ 用量统计 ============ -->` 整段）替换为：

```html
    <!-- ============ 用量统计 (数据源分层视图) ============ -->
    <section class="page" id="page-stats" hidden>
      <div class="ph"><h2 class="ph-title" data-i18n="statsTitle">用量统计</h2><div class="ph-right"><div class="pill-row" id="stats-pills"><button class="pill" data-r="today" data-i18n="today">今天</button><button class="pill" data-r="yesterday" data-i18n="yesterday">昨天</button><button class="pill active" data-r="7d" data-i18n="d7">近7天</button><button class="pill" data-r="30d" data-i18n="d30">近30天</button><button class="pill" data-r="all" data-i18n="all">全部</button></div></div></div>
      <div class="scope-hint" id="stats-scope-hint" hidden></div>
      <div class="kpi-row kpi4" id="stats-total-cards"></div>

      <!-- 数据源占比条 (可视化 + 导航合一, Token/费用可切换) -->
      <div class="card share-card">
        <div class="share-head">
          <span class="share-title" data-i18n="shareTitle">数据源占比（点击色块展开对应数据源）</span>
          <span class="seg" id="share-metric"><button class="active" data-m="tokens" data-i18n="segTokens">Token</button><button data-m="cost" data-i18n="cost">费用</button></span>
        </div>
        <div class="share-bar" id="share-bar"></div>
        <div class="share-legend" id="share-legend"></div>
        <div class="share-note" id="share-note" data-i18n="shareCostNote" hidden>※ 部分渠道费用不可用，未计入费用占比</div>
      </div>

      <!-- 全局图表 (Token 构成 / 模型用量 / 用量趋势, 默认折叠, 首次展开时渲染) -->
      <div class="panel" id="stats-charts-panel">
        <div class="panel-head" id="stats-charts-head"><span class="arrow">▶</span><span data-i18n="globalChartsTitle">📈 全局图表（Token 构成 · 模型用量 · 用量趋势）</span></div>
        <div class="panel-body" id="stats-charts-body">
          <div class="card detail6">
            <div class="card-h"><h3 data-i18n="tokenBreakdown">Token 构成</h3></div>
            <div class="d6-grid" id="stats-detail6"></div>
          </div>
          <div class="two-col">
            <div class="card model-rank">
              <div class="card-h"><h3 data-i18n="modelUsage">模型用量</h3></div>
              <div class="mr-body">
                <div class="chart-box" style="min-height:200px"><canvas id="mr-chart"></canvas><div class="zcode-chart-empty" id="mr-empty" hidden></div></div>
                <div class="mr-list" id="mr-list"></div>
              </div>
            </div>
            <div class="card usage-trend">
              <div class="card-h"><h3 data-i18n="usageTrend">用量趋势</h3><span class="hint" data-i18n="trendAllChannels">全渠道</span></div>
              <div class="chart-box" style="min-height:240px"><canvas id="trend-chart"></canvas><div class="zcode-chart-empty" id="trend-empty" hidden></div></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 数据源手风琴面板 (JS 渲染) -->
      <div id="sources-container"></div>

      <!-- 无数据源收纳区 -->
      <div class="empty-zone" id="empty-zone" hidden>
        <div class="zone-head" id="empty-zone-head"><span class="arrow">▶</span><span id="empty-zone-title"></span></div>
        <div class="zone-body" id="empty-zone-body" hidden></div>
      </div>
    </section>
```

说明：
- `stats-pills` 增加"昨天"（白名单已支持）；`mr-dim`（输入/输出/成本切换）移除——新模型图为全渠道 tokens 口径，维度切换属旧账号口径功能。
- 四个本地 stats 区块（zcode/dsh/claudecode/codex-stats）整段删除。

- [ ] **Step 4: 跑契约测试确认通过**

Run: `python -m pytest tests/test_codex_ui_contract.py -v`
Expected: PASS

---

### Task 7: 前端核心 JS——状态、汇总渲染、占比条、手风琴

**Files:**
- Modify: `app/web/app.js`（state 定义约 265-277 行处加 `statsView`；`switchPage()` 约 540 行改 stats 分支；新增一组渲染函数；`stats-pills` 事件约 2315 行改绑）

**Interfaces:**
- Consumes: Task 2 的 `/api/stats/sources` 响应形状；`t()`/`fmtTokens()`/`fmtInt()`/`fmtMoney()`/`escapeHtml()`/`api()`；现有 i18n 键 `srcOpencode/sourceBai/sourceCommandcode/srcZcode/srcClaudecode/srcCodex`。
- Produces: `state.statsView = {range, metric, expandedSource, sourcesData, detailsCache, chartsRendered}`；`loadStatsSources()`、`renderStatsSources(data)`、`expandSource(id, fromShareBar)`；常量 `SOURCE_COLOR`。Task 8 消费 `state.statsView` 与 `expandSource`。

- [ ] **Step 1: state 与常量**

state 对象中（`reportMetric: "tokens",` 行后）新增：

```javascript
  statsView: { range: "7d", metric: "tokens", expandedSource: null,
               sourcesData: null, detailsCache: {}, chartsRendered: false },
```

常量区（`COLOR` 定义附近）新增（渠道显示名统一由后端 `source_name` 返回，品牌名双语通用，前端不建 i18n 映射）：

```javascript
const SOURCE_COLOR = { opencode: "#5b8def", bai: "#4fc3f7", commandcode: "#9a6ff0",
  zcode: "#34b37e", claudecode: "#e8a33d", codex: "#6b7488", dsh: "#8d6e63" };
```

- [ ] **Step 2: 渲染函数（新增，放在 records 相关函数之前）**

```javascript
/* ---------------- 用量统计 · 数据源分层视图 ---------------- */
async function loadStatsSources() {
  try {
    const data = await api(`/api/stats/sources?range=${state.statsView.range}`);
    state.statsView.sourcesData = data;
    renderStatsSources(data);
    // range 切换后图表面板处于展开态时立即重渲 (chartsRendered 已被 pills 处理器重置,
    // 否则图表保持旧 range 数据直到用户手动收起再展开)
    if (!state.statsView.chartsRendered && $("stats-charts-panel").classList.contains("expanded")) {
      renderStatsCharts();
    }
  } catch (e) {
    $("sources-container").innerHTML =
      `<div class="panel"><div class="panel-body" style="color:var(--red)">${t("loadFailed")}: ${escapeHtml(e.message)}</div></div>`;
  }
}

function renderStatsSources(data) {
  // 1. KPI 汇总卡
  const tt = data.totals;
  $("stats-total-cards").innerHTML = `
    <div class="card kpi c-blue"><div class="kpi-l">${t("totalRequests")}</div><div class="kpi-v">${fmtInt(tt.request_count)}</div></div>
    <div class="card kpi c-violet"><div class="kpi-l">${t("totalTokens")}</div><div class="kpi-v">${fmtTokens(tt.total_tokens)}</div></div>
    <div class="card kpi c-amber"><div class="kpi-l">${t("totalCost")}</div><div class="kpi-v">${fmtMoney(tt.total_cost_usd)}</div></div>
    <div class="card kpi c-green"><div class="kpi-l">${t("hitRate")}</div><div class="kpi-v">${tt.hit_rate == null ? "—" : tt.hit_rate.toFixed(1) + "%"}</div></div>`;

  // 2. 占比条 (费用口径下跳过费用不可用渠道)
  const metric = state.statsView.metric;
  const barSources = data.sources.filter((s) => metric === "tokens" || s.cost_available);
  $("share-bar").innerHTML = barSources.map((s) => {
    const pct = metric === "tokens" ? s.pct_tokens : s.pct_cost;
    return `<div class="share-seg" style="flex:${pct};background:${SOURCE_COLOR[s.source_id] || "#6b7488"}"
      title="${escapeHtml(s.source_name)} ${pct.toFixed(1)}%"
      onclick="expandSource('${s.source_id}', true)">${pct >= 6 ? pct.toFixed(0) + "%" : ""}</div>`;
  }).join("");
  $("share-legend").innerHTML = data.sources.map((s) =>
    `<span><span class="share-dot" style="background:${SOURCE_COLOR[s.source_id] || "#6b7488"}"></span>${escapeHtml(s.source_name)} ${s.cost_available ? fmtMoney(s.total_cost_usd) + (s.estimated ? ` (${t("estimated")})` : "") : t("costUnavailable")}</span>`
  ).join("");
  $("share-note").hidden = metric !== "cost" || barSources.length === data.sources.length;

  // 3. 数据源面板 (手风琴: 仅 expandedSource 展开)
  $("sources-container").innerHTML = data.sources.map((s) => {
    const expanded = state.statsView.expandedSource === s.source_id;
    const pct = metric === "tokens" ? s.pct_tokens : (s.pct_cost != null ? s.pct_cost : s.pct_tokens);
    const badges = [
      s.estimated ? `<span class="badge" title="${t("estimateTip")}">${t("estimated")}</span>` : "",
      s.cost_available ? "" : `<span class="badge badge-muted">${t("costUnavailable")}</span>` : "",
      s.source_id === "dsh" ? `<span class="badge badge-muted">${t("todayOnly")}</span>` : "",
    ].join("");
    const statsText = s.cost_available
      ? `${pct.toFixed(1)}% | ${fmtMoney(s.total_cost_usd)}`
      : `${fmtTokens(s.total_tokens)} | ${t("costUnavailable")}`;
    return `
    <div class="panel source-panel ${expanded ? "expanded" : ""}" id="src-${s.source_id}">
      <div class="panel-head" onclick="expandSource('${s.source_id}')">
        <span class="arrow">▶</span>
        <span class="src-icon">${s.source_type === "remote" ? "☁️" : "💾"}</span>
        <span class="src-name">${escapeHtml(s.source_name)}</span>${badges}
        <span class="src-head-stats">
          <span class="src-mini-bar"><span style="width:${pct}%;background:${SOURCE_COLOR[s.source_id] || "#6b7488"}"></span></span>
          <span class="src-stats">${statsText}</span>
          <span class="src-toggle">${expanded ? "🔽" : ""}</span>
        </span>
      </div>
      <div class="panel-body" id="src-body-${s.source_id}">${expanded ? `<div class="loading">${t("loading")}</div>` : ""}</div>
    </div>`;
  }).join("");

  // 4. 无数据源收纳区
  const zone = $("empty-zone");
  zone.hidden = !data.empty_sources.length;
  $("empty-zone-title").textContent = `${t("emptySources")} (${data.empty_sources.length})`;
  $("empty-zone-body").innerHTML = data.empty_sources.map((e) =>
    `<span class="empty-src">💾 ${escapeHtml(e.source_name)} · ${escapeHtml(e.reason)}</span>`).join("");

  // 5. 默认展开排序第一名; 已展开项加载详情
  if (!state.statsView.expandedSource && data.sources.length) {
    state.statsView.expandedSource = data.sources[0].source_id;
    renderStatsSources(data);
    return;
  }
  if (state.statsView.expandedSource) loadSourceDetail(state.statsView.expandedSource);
}

// 手风琴单开; fromShareBar=true 时滚动到位
function expandSource(sourceId, fromShareBar = false) {
  state.statsView.expandedSource =
    state.statsView.expandedSource === sourceId && !fromShareBar ? null : sourceId;
  renderStatsSources(state.statsView.sourcesData);
  if (state.statsView.expandedSource && fromShareBar) {
    const el = $(`src-${sourceId}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
}
```

- [ ] **Step 3: 接线——switchPage、stats-pills、metric 切换、收纳区展开**

`switchPage()` 中 stats 分支改为（旧的 `loadZcodeSummary/loadDshUsage/loadClaudecodeSummary/loadCodexSummary` 调用在 Task 9 删除，本步先加新调用）：

```javascript
  if (page === "stats") loadStatsSources().catch(() => {});
```

`stats-pills` 点击处理器（约 2315 行）改为：

```javascript
  document.querySelectorAll("#stats-pills .pill").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#stats-pills .pill").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    state.statsView.range = b.dataset.r;
    state.statsView.expandedSource = null;   // 切范围重置手风琴, 重新默认展开第一名
    state.statsView.detailsCache = {};
    state.statsView.chartsRendered = false;
    loadStatsSources();
  }));
```

初始化绑定区（stats-pills 绑定附近）新增：

```javascript
  $("share-metric").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    $("share-metric").querySelectorAll("button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    state.statsView.metric = b.dataset.m;
    if (state.statsView.sourcesData) renderStatsSources(state.statsView.sourcesData);
  }));
  $("stats-charts-head").addEventListener("click", () => {
    $("stats-charts-panel").classList.toggle("expanded");
    if ($("stats-charts-panel").classList.contains("expanded")) renderStatsCharts();   // Task 8
  });
  $("empty-zone-head").addEventListener("click", () => {
    const body = $("empty-zone-body");
    body.hidden = !body.hidden;
    $("empty-zone-head").querySelector(".arrow").style.transform = body.hidden ? "" : "rotate(90deg)";
  });
```

- [ ] **Step 4: 编译检查（JS 无编译，做语法检查）**

Run: `node --check app/web/app.js`（若无 node，`python -c "print('skip')"` 跳过并靠 Task 11 浏览器验证）
Expected: 无语法错误

---

### Task 8: 前端详情渲染 + 按需缓存 + gotoRecords + 全局图表懒加载

**Files:**
- Modify: `app/web/app.js`（Task 7 函数块后追加）

**Interfaces:**
- Consumes: `/api/stats/sources/{id}/detail`（Task 3/4 形状）；`/api/stats/models`（Task 5）；`/api/report/daily?range=&metric=tokens`（现有路由，首页堆叠图同款，labels/series 形状）；`state.statsView`（Task 7）。
- Produces: `loadSourceDetail(sourceId)`、`renderSourceDetail(sourceId, detail)`、`gotoRecords(sourceId)`、`renderStatsCharts()`。

- [ ] **Step 1: 详情加载与渲染（30s TTL 缓存）**

```javascript
async function loadSourceDetail(sourceId) {
  const cacheKey = `${sourceId}|${state.statsView.range}`;
  const hit = state.statsView.detailsCache[cacheKey];
  if (hit && Date.now() - hit.at < 30000) {
    renderSourceDetail(sourceId, hit.data);
    return;
  }
  try {
    const detail = await api(`/api/stats/sources/${sourceId}/detail?range=${state.statsView.range}`);
    state.statsView.detailsCache[cacheKey] = { at: Date.now(), data: detail };
    if (state.statsView.expandedSource === sourceId) renderSourceDetail(sourceId, detail);
  } catch (e) {
    const body = $(`src-body-${sourceId}`);
    if (body) body.innerHTML = `<div style="color:var(--red)">${t("loadFailed")}: ${escapeHtml(e.message)}</div>`;
  }
}

function _dimRows(rows, color, nameKey) {
  return rows.map((r) => `
    <div class="dim-row">
      <span class="dim-name" title="${escapeHtml(r[nameKey] || "")}">${escapeHtml(r[nameKey] || "—")}</span>
      <span class="dim-bar"><span class="dim-fill" style="width:${r.percentage || 0}%;background:${color}"></span></span>
      <span class="dim-val">${(r.percentage || 0).toFixed(0)}%</span>
    </div>`).join("");
}

function renderSourceDetail(sourceId, detail) {
  const body = $(`src-body-${sourceId}`);
  if (!body) return;
  const color = SOURCE_COLOR[sourceId] || "#6b7488";
  let html = "";
  if (detail.accounts) {
    // 远程: 账号分布 + Top Keys + 模型用量
    html = `
      <div class="detail-grid">
        <div class="detail-block"><h4>👥 ${t("accountDist")}</h4>${_dimRows(detail.accounts, color, "account_name")}</div>
        <div class="detail-block"><h4>🔑 ${t("topKeys")}</h4>${_dimRows(detail.top_keys, color, "key_name")}</div>
      </div>
      <div class="detail-block" style="margin-top:14px"><h4>🤖 ${t("modelUsage")}</h4>${_dimRows(detail.models, color, "model")}</div>`;
  } else if (detail.providers) {
    // 本地: Provider/Channel 分布 + 模型用量
    html = `
      <div class="detail-grid">
        <div class="detail-block"><h4>🔌 ${t("providerDist")}</h4>${_dimRows(detail.providers, color, "provider_id")}</div>
        <div class="detail-block"><h4>🤖 ${t("modelUsage")}</h4>${_dimRows(detail.models, color, "model")}</div>
      </div>`;
  } else if (detail.today) {
    // DSH: 仅今日汇总, 无下钻
    const d = detail.today;
    html = `<div class="src-summary">📊 ${fmtTokens(d.tokens)} Token · ${t("input")} ${fmtTokens(d.input)} · ${t("output")} ${fmtTokens(d.output)} · ${t("cacheRead")} ${fmtTokens(d.cache_read)}</div>`;
  }
  // DSH 无逐条记录 (无表), 不显示"查看详细记录"; codex 记录在记录页可按来源筛选
  if (sourceId !== "dsh") {
    html += `<a class="src-link" onclick="gotoRecords('${sourceId}')">${t("viewRecords")} →</a>`;
  }
  body.innerHTML = html;
}

// 跳转记录页并预设来源筛选 (复用现有切页与 SOURCE_OPTIONS 下拉; 无 hash 路由)
function gotoRecords(sourceId) {
  state.records.source = sourceId;
  state.records.page = 1;
  state.sessions.page = 1;
  switchPage("records");          // 内部触发 loadSessions + loadRecords
  syncSourceFilter();             // 同步下拉选中态 (switchPage 后 select 已存在)
}
```

- [ ] **Step 2: 全局图表懒加载（首次展开渲染，全渠道口径）**

```javascript
let cStatsTrend = null, cStatsModels = null;
async function renderStatsCharts() {
  if (state.statsView.chartsRendered) return;
  state.statsView.chartsRendered = true;
  const range = state.statsView.range;
  try {
    const [models, daily] = await Promise.all([
      api(`/api/stats/models?range=${range}`),
      api(`/api/report/daily?range=${range}&metric=tokens`),
    ]);
    renderStatsDetail6(state.statsView.sourcesData ? state.statsView.sourcesData.totals : null);
    chartStatsModels(models.models);
    chartStatsTrend(daily);
  } catch (e) { /* 图表失败不阻断主视图; 空态由 setChartEmpty 处理 */ }
}

// Token 构成: 复用 totals 的构成字段 (Task 1 已随汇总返回)
function renderStatsDetail6(totals) {
  if (!totals) return;
  const items = [
    ["input", totals.total_input_tokens], ["output", totals.total_output_tokens],
    ["reasoning", totals.total_reasoning_tokens], ["cacheRead", totals.total_cache_read_tokens],
    ["cacheWrite", totals.total_cache_write_tokens],
  ];
  $("stats-detail6").innerHTML = items.map(([k, v]) =>
    `<div class="d6-item"><div class="d6-l">${t(k)}</div><div class="d6-v">${fmtTokens(v)}</div></div>`).join("");
}

// 模型用量: 横向条形 (样式对齐现有 mr-chart 用法; Chart.js 全局已加载)
function chartStatsModels(models) {
  const top = models.slice(0, 10);
  setChartEmpty("mr-chart", "mr-empty", top.length ? null : "noDataInRange");
  if (cStatsModels) { cStatsModels.destroy(); cStatsModels = null; }
  if (!top.length) return;
  cStatsModels = new Chart($("mr-chart"), {
    type: "bar",
    data: { labels: top.map((m) => m.model),
            datasets: [{ data: top.map((m) => m.tokens), backgroundColor: "#5b8def" }] },
    options: { indexAxis: "y", responsive: true, maintainAspectRatio: false,
               plugins: { legend: { display: false } } },
  });
  $("mr-list").innerHTML = top.map((m) =>
    `<div class="mr-item"><span>${escapeHtml(m.model)}</span><span class="num">${fmtTokens(m.tokens)}</span></div>`).join("");
}

// 用量趋势: /api/report/daily 的各渠道 series 逐日求和为总趋势线
function chartStatsTrend(daily) {
  const labels = daily.labels || [];
  const totals = labels.map((_, i) =>
    (daily.series || []).reduce((acc, s) => acc + ((s.data || [])[i] || 0), 0));
  setChartEmpty("trend-chart", "trend-empty", labels.length ? null : "noDataInRange");
  if (cStatsTrend) { cStatsTrend.destroy(); cStatsTrend = null; }
  if (!labels.length) return;
  cStatsTrend = new Chart($("trend-chart"), {
    type: "line",
    data: { labels, datasets: [{ data: totals, borderColor: "#5b8def", fill: false, tension: 0.3 }] },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } } },
  });
}
```

注意：`/api/report/daily` 返回形状以实际为准（`labels`/`series[].data`，首页 `report-stack` 同款消费，见 app.js:2535/2695 附近）；若字段名不同（如 `days`/`channels`），以该路由真实响应调整两处访问器，并在 Task 11 集成验证中确认。

- [ ] **Step 3: 语法检查**

Run: `node --check app/web/app.js`
Expected: 无语法错误

---

### Task 9: 旧本地区块清理 + i18n 文案

**Files:**
- Modify: `app/web/app.js`（删除旧 loader 调用与孤儿函数；I18N zh/en 加键）
- Test: `tests/test_i18n_consistency.py`（既有，自动校验）

**Interfaces:**
- Consumes: Task 6 移除的 DOM id；Task 7/8 新函数名。
- Produces: i18n 新键（zh/en）：`shareTitle/shareCostNote/globalChartsTitle/trendAllChannels/estimated/costUnavailable/todayOnly/emptySources/accountDist/topKeys/providerDist/viewRecords`（渠道名由后端 `source_name` 返回，不需要 srcDsh 等渠道名键；`loading` 若已存在则复用，先查重）。

- [ ] **Step 1: 解除 stats 页与账号口径 loadDashboard 的绑定（关键，防双重渲染冲突）**

新视图复用了旧 stats 页的 DOM id（`stats-total-cards` / `stats-detail6` / `mr-chart` / `trend-chart`），而旧渲染路径仍向这些 id 写**账号口径**数据，必须全部拆除：

1. `switchPage()`（app.js:545）：`if (page === "home" || page === "stats") loadDashboard();` 改为 `if (page === "home") loadDashboard();`（stats 页由 Task 7 的 `loadStatsSources` 驱动）。
2. sync 完成后的按页刷新（app.js:1379 附近，原 stats 页走 `loadCodexSummary`）：改为 `else if (state.page === "stats") loadStatsSources().catch(() => {});`。

- [ ] **Step 2: 删除旧 stats 页渲染函数及其全部调用点**

以下 4 个函数只服务于旧 stats 页 id（这些 id 已被 Task 7/8 的新渲染逻辑接管），函数整体成为孤儿，连同调用点一起删除：

| 函数 | 定义 | 调用点（均需删除） |
|---|---|---|
| `renderStatsTotal` | app.js:1449 | loadDashboard 回调（约 1753）、`applyCurrency`（约 530，不看当前页，必删） |
| `renderDetail6` | 同区域 | loadDashboard 回调、`applyCurrency`（约 531） |
| `chartModel` | app.js:1497 | loadDashboard 回调（约 1755）、可见性分支（约 1731） |
| `chartTrend` | app.js:1535 | loadDashboard 回调（约 1756）、resize 分支（约 2845） |
| `updateStatsScopeHint` | renderStatsTotal 内调用 | 仅服务旧 stats 页，一并删除（新 DOM 保留 `stats-scope-hint` 但恒 hidden） |

删除后验证（应 0 命中）：

Run: `grep -n "renderStatsTotal\|renderDetail6\|chartModel\|chartTrend\|updateStatsScopeHint" app/web/app.js`

注意：Task 8 的新函数 `renderStatsDetail6/chartStatsModels/chartStatsTrend` 名称相近但不同，勿误删；`applyCurrency` 中 `renderOverview(state.data.totals)` 是首页逻辑，保留。统计页货币切换的即时重渲随以上调用点删除而失效，由 switchPage 回页重载 / 切 range 兜底（与 EVOLUTION-9 设置页内不重渲的既有约定一致）。

- [ ] **Step 3: 移除四个本地 summary loader 调用并删除孤儿函数**

`switchPage()` 中删除 stats 分支的 4 行：`loadZcodeSummary()`、`loadDshUsage()`、`loadClaudecodeSummary()`、`loadCodexSummary()`。

**删除已移除 DOM id 的初始化绑定（高危，遗漏会导致整 app 初始化崩溃）**：`#mr-dim` 和 `#dsh-dim` 已在 Task 6 从 DOM 移除，而 app.js:2322/2328 是 `$("mr-dim").addEventListener(...)` / `$("dsh-dim").addEventListener(...)` 写法——`$()` 返回 null 后 `.addEventListener` 抛 TypeError，初始化中断。必须删除这两个绑定块（约 2322-2331 行）。验证：

Run: `grep -n "mr-dim\|dsh-dim" app/web/app.js`
Expected: 0 命中（1031 行注释提及随 `dshUsageLast` 所在函数一并删除）

然后删除孤儿函数（先查引用再删）：

Run: `grep -n "loadZcodeSummary\|loadDshUsage\|loadClaudecodeSummary\|loadCodexSummary\|renderZcodeSummary\|renderDshUsage\|renderClaudecodeSummary\|renderCodexSummary\|zcodeSummaryLast\|claudecodeSummaryLast\|codexSummaryLast" app/web/app.js`

逐个确认仅剩定义处与彼此间的引用后删除（包括货币/语言重渲染处对 `renderZcodeSummary/renderClaudecodeSummary/renderCodexSummary` 的调用行，约 535-536 行）。删除后再次 grep 上述符号应为 0 命中。

- [ ] **Step 4: 加 i18n 键（I18N zh/en 两处）**

zh（在 stats 相关键附近）：

```javascript
shareTitle: "数据源占比（点击色块展开对应数据源）", shareCostNote: "※ 部分渠道费用不可用，未计入费用占比",
globalChartsTitle: "📈 全局图表（Token 构成 · 模型用量 · 用量趋势）", trendAllChannels: "全渠道",
estimated: "估算值", costUnavailable: "费用不可用", todayOnly: "仅今日",
emptySources: "无数据的数据源", accountDist: "账号分布", topKeys: "Top Keys",
providerDist: "Provider 分布", viewRecords: "查看详细记录", srcDsh: "DSH",
```

en：

```javascript
shareTitle: "Usage share by source (click a segment to expand)", shareCostNote: "※ Some sources have no cost data and are excluded from cost share",
globalChartsTitle: "📈 Global charts (Token breakdown · Models · Trend)", trendAllChannels: "All channels",
estimated: "Estimated", costUnavailable: "Cost N/A", todayOnly: "Today only",
emptySources: "Sources with no data", accountDist: "Accounts", topKeys: "Top Keys",
providerDist: "Providers", viewRecords: "View records", srcDsh: "DSH",
```

同时确认 `totalRequests/totalTokens/totalCost/hitRate/estimateTip/noDataInRange/loadFailed/input/output/cacheRead/cacheWrite/reasoning/cost/segTokens/loading` 键已存在（大部分既有）；缺哪个补哪个（zh/en 都补）。

- [ ] **Step 5: 跑 i18n 一致性测试**

Run: `python -m pytest tests/test_i18n_consistency.py -v`
Expected: PASS（zh/en 键数一致）

- [ ] **Step 6: 语法检查 + 全量前端相关回归**

Run: `node --check app/web/app.js && python -m pytest tests/test_dark_theme.py tests/test_narrow_layout.py -v`
Expected: 通过

---

### Task 10: CSS 样式（含暗色主题）

**Files:**
- Modify: `app/web/style.css`

**Interfaces:**
- Consumes: Task 6 DOM 结构；现有变量 `--bg1/--bg2/--bg3/--border/--text1/--text2/--text3/--amber/--red`（先 grep 确认变量名存在，不存在则用最接近的既有变量）。
- Produces: `.share-card/.share-head/.share-bar/.share-seg/.share-legend/.share-dot/.share-note`、`.panel/.panel-head/.panel-body/.arrow`、`.source-panel` 内 `.src-icon/.src-name/.src-head-stats/.src-mini-bar/.src-stats`、`.badge/.badge-muted`、`.detail-grid/.detail-block/.dim-row/.dim-name/.dim-bar/.dim-fill/.dim-val`、`.src-link`、`.empty-zone/.zone-head/.zone-body/.empty-src`。

- [ ] **Step 1: 确认 CSS 变量**

Run: `grep -n "\-\-bg2\|\-\-bg3\|\-\-border\|\-\-text3\|\-\-amber" app/web/style.css | head`
Expected: 均有定义（暗色主题为默认或 `:root` 双套）

- [ ] **Step 2: 追加样式（与模拟页 doc/20260908-stats-display-mockup.html 的 <style> 一致，色值改为变量）**

将模拟页中以下选择器的样式原样移植，硬编码色值替换为变量：`--bg1/--bg2/--bg3/--border/--text1/--text2/--text3`；`.share-seg` 文字色 `rgba(255,255,255,.92)`；`.badge` 用 `rgba(232,163,61,.15)` 底 + `var(--amber)` 字；`.badge-muted` 用 `var(--bg3)` 底 + `var(--text3)` 字。面板折叠规则：

```css
.panel .panel-body { display: none; }
.panel.expanded .panel-body { display: block; }
.panel .arrow { transition: transform .2s; }
.panel.expanded .arrow { transform: rotate(90deg); }
```

- [ ] **Step 3: 清理死 CSS（Task 6 删除 DOM 后产生的孤儿样式）**

先确认类名未被其他页面（首页 zcode-quota 等）复用：

Run: `grep -n "zcode-stats\|dsh-stats\|codex-stats\|zcode-missing\|zcode-trend" app/web/index.html app/web/app.js`
Expected: 0 命中（Task 6/9 已完成 DOM 与 JS 清理后）

确认后删除 `style.css` 中对应样式块：`.zcode-stats` 及其子选择器（约 483-489 行）、`.dsh-stats` 及其子选择器、`.codex-stats` 及其子选择器（约 499-505 行）、`.zcode-missing`、`.zcode-trend-box`。**保留**：`.zcode-chart-empty`（新视图 mr-empty/trend-empty 等空态仍在用）、首页 `.zcode-quota/.zcode-head/.zcode-cards/.zcode-badge` 相关类。

- [ ] **Step 4: 暗色主题验证**

Run: `python -m pytest tests/test_dark_theme.py -v`
Expected: PASS（该测试校验 style.css 暗色变量契约；若新增类引用了不存在的变量会在此暴露）

---

### Task 11: 集成验证 + 全量回归

**Files:** 无新增（验证任务）

- [ ] **Step 1: 全量 pytest**

Run: `python -m pytest tests/ -x -q`
Expected: 全部通过；如有与旧 page-stats DOM/loader 耦合的用例失败，回到 Task 9 补清理

- [ ] **Step 2: 编译检查**

Run: `python -m py_compile app/server.py app/db.py`
Expected: 无输出

- [ ] **Step 3: 启动服务手动验证 checklist**

Run: `python -m app.server`（或项目既有启动方式），浏览器打开统计页：

- [ ] 首屏：KPI 卡 + 占比条 + 排序第一名面板自动展开并加载详情，其余折叠
- [ ] 占比条点击色块 → 对应面板展开、其他收起、平滑滚动到位
- [ ] Token/费用切换：费用口径下 Codex/DSH 色块消失、显示脚注
- [ ] 本地渠道显示"估算值"徽标；Codex 显示"费用不可用"；range=today 时 DSH 出现（"仅今日"徽标），切到 7d 后 DSH 进入收纳区
- [ ] 全局图表默认折叠，首次展开渲染 Token 构成/模型用量/用量趋势（全渠道口径）
- [ ] "查看详细记录 →"跳转记录页且来源筛选已预设（DSH 面板无此链接）
- [ ] 切时间范围：全部联动更新，手风琴重置
- [ ] 暗色/浅色主题（如有切换）样式无异常；中英文切换无缺失键

- [ ] **Step 4: 提交（人工确认后）**

```bash
git add app/server.py app/db.py app/web/index.html app/web/app.js app/web/style.css tests/test_stats_sources.py tests/test_codex_ui_contract.py
git commit -m "feat: rebuild stats page as layered source view with share-bar navigation"
```

（按项目规则：不自动签入，人工确认后执行。）

---

## Self-Review 记录

- **Spec coverage**：占比条导航（T7）、手风琴+默认展开第一名（T7）、空源收纳区（T2/T7）、估算值/费用不可用/仅今日徽标（T7/T8）、记录页跳转预设筛选（T8）、远程账号/TopKeys/模型详情（T3）、本地 Provider/模型详情（T4）、DSH 今日特殊处理（T2/T4/T8）、全局图表默认折叠（T6/T8）、复用 report_channels（T1）、加权命中率（T1）、range 白名单（T1-T5）、i18n（T9）、暗色主题（T10）。
- **设计文档与代码事实偏差说明**：设计文档示例代码中的 `_json(...)` 实际为 `_json_response(handler, ...)`；`DataSourceMissing` 异常不存在，DSH 缺失经 `dsh_api.get_dsh_usage()["found"]` 判断（T2 已按真实接口编写）。
- **类型一致性**：`pct_cost/pct_tokens/cost_available/estimated/request_count_exact` 在 T1 产出、T2 dsh 行补齐、T7 前端消费，命名一致；`detailsCache` 键为 `sourceId|range`，T7 初始化、T8 读写一致。
- **评审修订记录（2026-09-08，两轮评审循环共 9 轮评审、10 项修复）**：
  1. P0：T1 `_seed_remote` 改为按 source 复用账号（原写法每调用插一行账号，T3 测试 `len(accounts)==1` 必败）。
  2. P1：T9 新增 Step 1-2——旧渲染路径（`renderStatsTotal/renderDetail6/chartModel/chartTrend/updateStatsScopeHint` 及其在 `loadDashboard` 回调、`applyCurrency`、可见性/resize 分支的调用点）会向新视图复用的 id（`stats-total-cards/stats-detail6/mr-chart/trend-chart`）写账号口径数据，必须全部拆除；`switchPage` 解除 stats→loadDashboard 绑定；sync 完成回调 stats 页改走 `loadStatsSources`。
  3. P2：codex 详情 `percentage` 由 `None` 改为按 tokens 占比（前端条形不再全 0），T4 测试补断言。
  4. P3：删除未使用的 `SOURCE_I18N` 常量（渠道名统一由后端 `source_name` 返回）；简化 `_remote_source_detail` 的 key_name 冗余逻辑；DSH today 测试种子改动态时间并加 `sources[0]=="opencode"` 强断言。
  5. P2（第 3 轮）：种子时间口径修正——`usage_records.created_at` 为 UTC（SQLite `datetime()` 按 UTC 解析，见 `test_report_api._to_utc_iso` 注释），计划原写的"本地时间字符串"在东八区 16:00 后会掉出 today 窗口；`_seed_remote` 的 `created` 缺省改为当前 UTC ISO（带 Z），同时消除固定日期导致的"7d 窗口随运行日期漂移"问题。
  6. P1（第 4 轮）：`#mr-dim`/`#dsh-dim` 的 `$().addEventListener` 初始化绑定（app.js:2322/2328）在 DOM 移除后会 null 解引用使整 app 初始化崩溃，T9 Step 3 新增显式删除步骤与 grep 验证。
  7. P2（第 4 轮）：T4 zcode 测试三模型 tokens 同为 100，ORDER BY 并列导致 `models[0]=="glm-5"` 断言不稳定，glm-5 种子 tokens 改为 120 消除并列。
  8. P3（第二轮评审循环 R1-R2）：DSH 并入后各渠道 `pct_tokens` 分母不一致（占比之和 >100%，与 totals 口径脱节）→ `_stats_sources_with_dsh` 并入后全量重算，T2 测试补分母断言。
  9. P3（第二轮评审循环 R1-R2）：切 range 时图表面板若处于展开态不刷新 → `loadStatsSources` 完成后检查面板展开态主动重渲。
  10. P3（第二轮评审循环 R1-R2）：死 CSS 未清理 → T10 新增 Step 3，grep 确认零引用后删除 `.zcode-stats/.dsh-stats/.codex-stats/.zcode-missing/.zcode-trend-box` 样式块（保留 `.zcode-chart-empty` 与首页 zcode-quota 类）。

---

**⚠️ 2026-09-09 后记**：本计划已执行（工作区未提交），随后用户因"Key 维度用量聚合丢失"要求回退代码。回退方案见 [20260909-stats-layered-view-rollback.md](20260909-stats-layered-view-rollback.md)。