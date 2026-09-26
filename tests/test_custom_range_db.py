"""自定义日期范围: db 层边界转换与过滤函数窗口测试 (设计文档 doc/20260926 §3/§5)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app import db


@pytest.fixture()
def tmp_crange_db(tmp_path, monkeypatch):
    """独立临时库 (同 tests/test_report_api.py::tmp_report_db 模式)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


# ---------- _parse_local_dt / _custom_bounds_utc ----------

def test_parse_local_dt_formats():
    assert db._parse_local_dt("2026-09-01 08:00:00") == datetime(2026, 9, 1, 8, 0, 0)
    assert db._parse_local_dt("2026-09-01T08:00:05") == datetime(2026, 9, 1, 8, 0, 5)   # T 分隔
    assert db._parse_local_dt("2026-09-01 08:00") == datetime(2026, 9, 1, 8, 0, 0)      # 缺秒补 :00
    assert db._parse_local_dt("garbage") is None
    assert db._parse_local_dt("") is None


def test_custom_bounds_utc_basic_and_invalid():
    b = db._custom_bounds_utc("2026-09-01 08:00:00", "2026-09-20 18:30:00")
    assert b is not None
    start_utc, end_utc = b
    # 不假设本机时区数值: 用标准库往返锚定 (本地 naive -> attach tz -> UTC 串)
    tz = datetime.now().astimezone().tzinfo
    from datetime import timezone
    want = datetime(2026, 9, 1, 8, 0, 0).replace(tzinfo=tz).astimezone(timezone.utc)
    assert start_utc == want.strftime("%Y-%m-%d %H:%M:%S")
    # end - start 的 UTC 秒差等于本地秒差 (转换无损)
    s = datetime.strptime(start_utc, "%Y-%m-%d %H:%M:%S")
    e = datetime.strptime(end_utc, "%Y-%m-%d %H:%M:%S")
    assert (e - s) == timedelta(days=19, hours=10, minutes=30)


def test_custom_bounds_utc_end_empty_is_now():
    b = db._custom_bounds_utc("2026-01-01 00:00:00", "")
    assert b is not None
    _, end_utc = b
    e = datetime.strptime(end_utc, "%Y-%m-%d %H:%M:%S")
    from datetime import timezone
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)  # end=now: 与当前 UTC 时刻同量级 (分钟级容差)
    assert abs((e - now_utc).total_seconds()) < 120


def test_custom_bounds_utc_invalid_cases():
    assert db._custom_bounds_utc(None, "2026-09-20 00:00:00") is None      # 缺 start
    assert db._custom_bounds_utc("bad", "2026-09-20 00:00:00") is None     # start 非法
    assert db._custom_bounds_utc("2026-09-20 00:00:00", "bad") is None     # end 非法
    assert db._custom_bounds_utc("2026-09-20 00:00:01", "2026-09-20 00:00:00") is None  # end < start
    same = db._custom_bounds_utc("2026-09-20 00:00:00", "2026-09-20 00:00:00")          # end == start 合法 (单秒窗口)
    assert same is not None and same[0] == same[1]


# ---------- _report_range_sql 扩展 ----------

def test_report_range_sql_custom_overrides_enum():
    sql, params = db._report_range_sql("7d", "r.created_at",
                                       start="2026-09-01 08:00:00", end="2026-09-20 18:00:00")
    assert sql == "datetime(r.created_at) >= datetime(?) AND datetime(r.created_at) <= datetime(?)"
    assert len(params) == 2


def test_report_range_sql_custom_invalid_falls_back_to_enum():
    sql, params = db._report_range_sql("7d", "r.created_at", start=None, end="2026-09-20 00:00:00")
    # 无 start -> 走枚举逻辑, 与现状一致 (7d 自然日窗口谓词)
    assert sql.startswith("datetime(r.created_at) >= datetime(?) AND datetime(r.created_at) < datetime(?)")
    assert len(params) == 2


def test_report_range_sql_no_args_regression():
    """回归红线: 不传新参时与现状逐字节一致."""
    assert db._report_range_sql("all", "x.started_at") == ("1=1", [])
    sql, params = db._report_range_sql("today", "x.started_at")
    assert ">= datetime(?)" in sql and "< datetime(?)" in sql and len(params) == 2


# ---------- _period_where / totals / model_stats (Task 2) ----------

def _seed_records(*created_at_list):
    """usage_records 直插 (列齐全, 同 tests/test_report_api.py::_mkrec 模式)."""
    aid = db.add_account("tok-crange", "ws-crange")
    conn = db.get_db()
    for i, created in enumerate(created_at_list):
        conn.execute(
            "INSERT INTO usage_records (usg_id, created_at, model, provider,"
            " input_tokens, output_tokens, reasoning_tokens, cache_read_tokens,"
            " cache_write_5m_tokens, cache_write_1h_tokens, cost_raw, cost_usd,"
            " key_id, session_id, plan, account_id, synced_at)"
            " VALUES (?, ?, 'm', 'anthropic', 10, 20, 0, 0, 0, 0, 0, 0.5, NULL, NULL, NULL, ?, ?)",
            (f"u{i}", created, aid, created))
    conn.commit()
    return aid


def test_period_where_custom_closed_interval(tmp_crange_db):
    """Review Focus #2: 记录时刻恰等于 start/end 秒端点必须计入 (闭区间).

    造数时区无关: 区间内中点/区间外前后 1 秒都由 _custom_bounds_utc 的
    转换结果推算, 不写死 UTC 时刻."""
    b = db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    fmt = "%Y-%m-%d %H:%M:%S"
    s_dt, e_dt = datetime.strptime(b[0], fmt), datetime.strptime(b[1], fmt)
    iso = lambda dt: dt.strftime(fmt).replace(" ", "T") + "Z"
    mid, before, after = s_dt + (e_dt - s_dt) / 2, s_dt - timedelta(seconds=1), e_dt + timedelta(seconds=1)
    _seed_records(iso(s_dt), iso(mid), iso(e_dt), iso(before), iso(after))
    t = db.totals("all", start="2026-09-20 08:00:00", end="2026-09-20 18:00:00")
    assert t["request_count"] == 3          # 含两个端点, 排除前后各 1 秒
    t_all = db.totals("all")
    assert t_all["request_count"] == 5      # 不传新参与现状一致


def test_model_stats_custom_window(tmp_crange_db):
    b = db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    fmt = "%Y-%m-%d %H:%M:%S"
    _seed_records(b[0].replace(" ", "T") + "Z", "2026-09-21T12:00:00Z")
    rows = db.model_stats("all", start="2026-09-20 08:00:00", end="2026-09-20 18:00:00")
    assert len(rows) == 1 and rows[0]["request_count"] == 1


def test_period_where_custom_invalid_falls_back(tmp_crange_db):
    """Review Focus #1: 非法自定义参数回退枚举档位逻辑 (period=all -> 全量)."""
    _seed_records("2026-09-20T12:00:00Z", "2026-09-01T12:00:00Z")
    t = db.totals("all", start="bad", end=None)
    assert t["request_count"] == 2


# ---------- zcode / claudecode 聚合 (Task 3) ----------

def _seed_zcode(*started_at_list):
    conn = db.get_db()
    for i, ts in enumerate(started_at_list):
        conn.execute(
            "INSERT INTO zcode_usage (id, session_id, started_at, model_id, provider_id,"
            " input_tokens, cache_read_tokens, cache_write_tokens, output_tokens,"
            " reasoning_tokens, cost_raw, synced_at)"
            " VALUES (?, ?, ?, 'zm', 'zp', 10, 0, 0, 20, 0, 0, ?)",
            (f"z{i}", f"zs{i}", ts, ts))
    conn.commit()


def test_zcode_totals_custom_window(tmp_crange_db):
    b = db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    _seed_zcode(b[0].replace(" ", "T") + "Z", "2026-09-21T10:00:00Z")
    t = db.zcode_totals("30d", start="2026-09-20 08:00:00", end="2026-09-20 18:00:00")
    assert t["request_count"] == 1
    assert db.zcode_totals("30d")["request_count"] == 2   # 不传新参回归


def test_zcode_provider_and_model_stats_custom(tmp_crange_db):
    b = db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    _seed_zcode(b[0].replace(" ", "T") + "Z", "2026-09-22T10:00:00Z")
    assert db.zcode_provider_stats("30d", start="2026-09-20 08:00:00",
                                    end="2026-09-20 18:00:00")[0]["request_count"] == 1
    assert db.zcode_model_stats("30d", start="2026-09-20 08:00:00",
                                 end="2026-09-20 18:00:00")[0]["request_count"] == 1


def _seed_cc(*started_at_list):
    conn = db.get_db()
    for i, ts in enumerate(started_at_list):
        conn.execute(
            "INSERT INTO claudecode_usage (dedupe_key, session_id, started_at, model, channel,"
            " input_tokens, cache_read_tokens, cache_write_tokens, output_tokens,"
            " cost_raw, total_tokens, synced_at)"
            " VALUES (?, ?, ?, 'cm', 'cp', 10, 0, 0, 20, 0, 30, ?)",
            (f"ck{i}", f"cs{i}", ts, ts))
    conn.commit()


def test_claudecode_totals_custom_window(tmp_crange_db):
    b = db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    _seed_cc(b[0].replace(" ", "T") + "Z", "2026-09-21T10:00:00Z")
    t = db.claudecode_totals("30d", start="2026-09-20 08:00:00", end="2026-09-20 18:00:00")
    assert t["request_count"] == 1
    assert db.claudecode_channel_stats("30d", start="2026-09-20 08:00:00",
                                       end="2026-09-20 18:00:00")[0]["request_count"] == 1
    assert db.claudecode_model_stats("30d", start="2026-09-20 08:00:00",
                                     end="2026-09-20 18:00:00")[0]["request_count"] == 1


# ---------- 自然日体系: workbuddy / codex / report_totals / channel_totals (Task 4) ----------

def test_workbuddy_summary_custom_window(tmp_crange_db):
    """远端 workbuddy_usage 表 (request_time 为本地时间串)."""
    conn = db.get_db()
    aid = db.add_account("tok-wb", "ws-wb")
    for i, ts in enumerate(["2026-09-20 10:00:00", "2026-09-21 10:00:00"]):
        conn.execute(
            "INSERT INTO workbuddy_usage (account_id, request_id, request_time, model,"
            " client, credit, synced_at) VALUES (?, ?, ?, 'wm', 'cli', 1.5, ?)",
            (aid, f"r{i}", ts, ts))
    conn.commit()
    s = db.workbuddy_summary("7d", start="2026-09-20 00:00:00", end="2026-09-20 23:59:59")
    assert s["requests"] == 1
    assert db.workbuddy_summary("7d")["requests"] == 2    # 不传新参回归


def test_codex_totals_custom_window(tmp_codex_db, codex_row):
    b = db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    in_iso = b[0].replace(" ", "T") + "Z"
    rows = [codex_row(started_at=in_iso), codex_row("s:2", started_at="2026-09-21T10:00:00Z")]
    assert db.import_codex_usage(rows) == 2
    t = db.codex_totals("30d", start="2026-09-20 08:00:00", end="2026-09-20 18:00:00")
    assert t["request_count"] == 1
    assert db.codex_totals("30d")["request_count"] == 2


def test_report_totals_custom_window(tmp_crange_db):
    aid = db.add_account("tok-oc2", "ws-oc2")
    conn = db.get_db()
    b = db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    for usg, created in (("ru1", b[0].replace(" ", "T") + "Z"), ("ru2", "2026-09-19T10:00:00Z")):
        conn.execute(
            "INSERT INTO usage_records (usg_id, created_at, model, provider,"
            " input_tokens, output_tokens, reasoning_tokens, cache_read_tokens,"
            " cache_write_5m_tokens, cache_write_1h_tokens, cost_raw, cost_usd,"
            " key_id, session_id, plan, account_id, synced_at)"
            " VALUES (?, ?, 'm', 'anthropic', 10, 20, 0, 0, 0, 0, 0, 0.5, NULL, NULL, NULL, ?, ?)",
            (usg, created, aid, created))
    conn.commit()
    t = db.report_totals("7d", start="2026-09-20 08:00:00", end="2026-09-20 18:00:00")
    assert t["request_count"] == 1


def test_channel_totals_custom_window(tmp_crange_db):
    b = db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    _seed_zcode(b[0].replace(" ", "T") + "Z", "2026-09-22T10:00:00Z")
    t = db.channel_totals("7d", "zcode", start="2026-09-20 08:00:00", end="2026-09-20 18:00:00")
    assert t["request_count"] == 1
