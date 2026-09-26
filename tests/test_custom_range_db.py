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
