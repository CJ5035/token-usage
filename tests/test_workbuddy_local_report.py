"""workbuddy 报表聚合口径单测 (关系式断言, 不依赖会漂移的绝对值).

行数据由 conftest 的 wb_row fixture 提供 (tests/ 无 __init__.py, 不可跨文件 import).
"""
from __future__ import annotations

from app import db


def _seed(tmp_db, wb_row):
    """2 会话 / 3 请求: 会话 s1 两条 (子代理归父), s2 一条; m3 未收录定价表.

    行内恒等式由 wb_row 保证: total = input + cache_read + output + reasoning。
    三行合计 total_tokens = 357 + 583 + 110 = 1050。
    """
    db.import_workbuddy_local_usage([
        wb_row("m1", "s1", credit=1.0, cost_raw=1000, available=1,
               input_tokens=200, cache_read_tokens=100, output_tokens=50, reasoning_tokens=7),
        wb_row("m2", "s1", credit=2.0, cost_raw=2000, available=1,
               input_tokens=300, cache_read_tokens=200, output_tokens=80, reasoning_tokens=3),
        wb_row("m3", "s2", credit=0.0, cost_raw=0, available=0,
               input_tokens=100, cache_read_tokens=0, output_tokens=10, reasoning_tokens=0),
    ])


def test_totals_relations(tmp_db, wb_row):
    _seed(tmp_db, wb_row)
    t = db.workbuddy_local_totals("30d")
    assert t["request_count"] == 3
    assert t["session_count"] == 2                                     # 父会话去重
    assert t["cache_write_tokens"] == 0                                # 恒 0
    assert t["total_input_tokens"] == t["cache_hit_tokens"] + t["uncached_input_tokens"]
    assert t["total_input_tokens"] == 200 + 100 + 300 + 200 + 100 + 0  # miss+hit+0 逐行
    assert t["total_output_tokens"] == 50 + 80 + 10
    assert t["total_reasoning_tokens"] == 7 + 3 + 0
    assert t["uncached_input_tokens"] == 200 + 300 + 100
    # R8 恒等式: 前端「总 TOKEN 消耗」= 三键相加, 必须等于 Σ 原生 total_tokens
    assert (t["total_input_tokens"] + t["total_output_tokens"]
            + t["total_reasoning_tokens"]) == 357 + 583 + 110
    assert t["total_tokens"] == 357 + 583 + 110          # R15: 显式键, 与上式等值
    assert round(t["credits"], 2) == 3.0
    assert round(t["total_cost_usd"], 6) == round(3000 / 1e8, 6)
    assert t["unpriced_requests"] == 1
    assert t["local_only"] is True
    assert t["cache_write_available"] is False


def test_hit_rate_uses_prompt_tokens_denominator(tmp_db, wb_row):
    _seed(tmp_db, wb_row)
    t = db.workbuddy_local_totals("30d")
    hit, miss = 300, 600                       # 100+200 / 200+300+100
    # _totals_from_row(db.py:3133) 对 hit_rate 做 round(x, 2), 断言须对齐同一舍入 (R32)
    assert t["hit_rate"] == round(hit / (hit + miss) * 100, 2)


def test_channel_totals_workbuddy_matches_local_totals(tmp_db, wb_row):
    _seed(tmp_db, wb_row)
    assert db.channel_totals("30d", "workbuddy") == db.workbuddy_local_totals("30d")


def test_report_channels_workbuddy_row_from_local(tmp_db, wb_row):
    _seed(tmp_db, wb_row)
    rows = {r["channel"]: r for r in db.report_channels("30d")}
    assert "workbuddy" in rows
    r = rows["workbuddy"]
    assert r["requests"] == 3
    assert r["tokens"] == 357 + 583 + 110      # total_tokens 之和
    assert r["cache_write"] == 0
    assert round(r["credits"], 2) == 3.0
    assert r["estimated"] is True              # 有 USD 估算才算 (R18)
    assert r["cost_available"] is True
    assert r["cost_partial"] is True           # 存在未收录行
    assert r["data_since"] is not None         # R33: 本地行数据起点 = MIN(started_at)


def test_all_scope_aggregates_include_workbuddy(tmp_db, wb_row):
    """R36: 全渠道聚合与 zcode/claudecode/codex 同构并入 workbuddy."""
    _seed(tmp_db, wb_row)
    rt = db.report_totals("30d")
    assert rt["request_count"] == 3            # 其余来源空, 全部来自 workbuddy
    assert rt["total_tokens"] == 357 + 583 + 110
    assert rt["total_cost_usd"] == round(3000 / 1e8, 6)
    w = db.report_windows()
    assert w["30d"]["requests"] == 3
    assert w["channels"]["workbuddy"]["last_sync_at"] is not None   # 渠道归并循环含 wb


def test_report_channels_workbuddy_falls_back_to_remote(tmp_db, wb_row, local_iso):
    """无本地数据时不回归: workbuddy 行仍可由远程 workbuddy_usage 提供 (仅 credits)."""
    conn = db.get_db()
    conn.execute(
        "INSERT INTO accounts (id,name,source,created_at,updated_at)"
        " VALUES (9,'wb','workbuddy','2026-09-16T00:00:00Z','2026-09-16T00:00:00Z')")
    conn.execute(
        "INSERT INTO workbuddy_usage (account_id,request_id,request_time,model,client,credit,synced_at)"
        " VALUES (9,'r1',?,'m','WorkBuddy',1.5,?)", (local_iso(), local_iso()))
    conn.commit()
    r = {x["channel"]: x for x in db.report_channels("30d")}["workbuddy"]
    assert r["requests"] == 1
    assert r["credits"] == 1.5
    assert r["cost"] is None
    assert r["estimated"] is False              # R18: 无 USD 估算 → 不挂估算徽章


def test_local_est_channels_contains_workbuddy():
    assert "workbuddy" in db._LOCAL_EST_CHANNELS


def test_hourly_daily_and_trend_reconcile(tmp_db, wb_row):
    _seed(tmp_db, wb_row)
    for channel in (None, "workbuddy"):
        h = db.report_hourly("today", channel)
        assert sum(h["series"]["workbuddy"]) == 1050
        assert sum(b["total_tokens"] for b in h["buckets"]) == 1050
        assert sum(b["requests"] for b in h["buckets"]) == 3
    daily = db.report_daily("today", "workbuddy", "tokens")
    assert sum(daily["series"]["workbuddy"]) == 1050
    trend = db.channel_trend("today", "workbuddy")
    assert len(trend) == 24
    assert sum(r["input"] + r["output"] for r in trend) == 1050
    assert sum(r["total_input_tokens"] + r["total_output_tokens"]
               + r["total_reasoning_tokens"] for r in trend) == 1050
    assert len([r for r in db.list_channel_summary() if r["channel"] == "workbuddy"]) == 1


def test_unknown_cost_is_not_free(tmp_db, wb_row):
    db.import_workbuddy_local_usage([wb_row(available=0, cost_raw=0, credit=None)])
    t = db.workbuddy_local_totals("today")
    assert t["total_cost_usd"] is None and not t["cost_available"] and t["cost_partial"]
    assert t["credits"] is None
    w = db.report_windows("workbuddy")["today"]
    assert w["cost"] is None and not w["cost_available"] and w["cost_partial"]
    r = db.report_totals("today")
    assert r["total_cost_usd"] is None and "workbuddy" in r["cost_unavailable_channels"]
    daily = db.report_daily("today", "workbuddy", "cost")
    assert "workbuddy" not in daily["series"]
    assert "workbuddy" in daily["unavailable_channels"]


def test_partial_cost_and_real_zero_price(tmp_db, wb_row):
    db.import_workbuddy_local_usage([wb_row(available=1, cost_raw=0)])
    zero = db.workbuddy_local_totals("today")
    assert zero["total_cost_usd"] == 0 and zero["cost_available"] and not zero["cost_partial"]
    db.import_workbuddy_local_usage([wb_row("unknown", available=0, cost_raw=0)])
    w = db.report_windows("workbuddy")["today"]
    assert w["cost"] == 0 and w["cost_available"] and w["cost_partial"]
    assert "workbuddy" in db.report_daily("today", None, "cost")["unavailable_channels"]
