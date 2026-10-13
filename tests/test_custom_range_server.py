"""自定义范围: server 解析 helper 与端点透传测试 (设计文档 §5)."""
from __future__ import annotations

import pytest

from app import server


def _q(range_, start=None, end=None):
    q = {"range": [range_]}
    if start is not None:
        q["start"] = [start]
    if end is not None:
        q["end"] = [end]
    return q


def test_custom_range_from_query_matrix():
    # 合法: start + end / start + 空 end / T 分隔 / 缺秒
    assert server._custom_range_from_query(_q("custom", "2026-09-20 08:00:00", "2026-09-20 18:00:00")) \
        == ("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    assert server._custom_range_from_query(_q("custom", "2026-09-20 08:00:00", "")) \
        == ("2026-09-20 08:00:00", "")
    assert server._custom_range_from_query(_q("custom", "2026-09-20T08:00:05")) \
        == ("2026-09-20T08:00:05", "")
    assert server._custom_range_from_query(_q("custom", "2026-09-20 08:00")) \
        == ("2026-09-20 08:00", "")
    # 非法: 缺 start / start 不可解析 / end<start / 非 custom range 一律 (None, None)
    for bad in (
        _q("custom"),
        _q("custom", start=None, end="2026-09-20 00:00:00"),
        _q("custom", "garbage"),
        _q("custom", "2026-09-20 00:00:01", "2026-09-20 00:00:00"),
        _q("7d", "2026-09-20 00:00:00", "2026-09-21 00:00:00"),
    ):
        assert server._custom_range_from_query(bad) == (None, None)


# ---------- payload 组装函数 (Task 7) ----------

@pytest.fixture()
def tmp_server_db(tmp_path, monkeypatch):
    from app import db as _db
    monkeypatch.setattr(_db, "data_dir", lambda: str(tmp_path))
    _db._DB = None
    yield _db
    _db.close_db()


def test_dashboard_all_payload_custom(tmp_server_db, monkeypatch):
    aid = tmp_server_db.add_account("tok-a", "ws-a")
    conn = tmp_server_db.get_db()
    b = tmp_server_db._custom_bounds_utc("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    for usg, created in (("du1", b[0].replace(" ", "T") + "Z"), ("du2", "2026-09-10T10:00:00Z")):
        conn.execute(
            "INSERT INTO usage_records (usg_id, created_at, model, provider,"
            " input_tokens, output_tokens, reasoning_tokens, cache_read_tokens,"
            " cache_write_5m_tokens, cache_write_1h_tokens, cost_raw, cost_usd,"
            " key_id, session_id, plan, account_id, synced_at)"
            " VALUES (?, ?, 'm', 'anthropic', 10, 20, 0, 0, 0, 0, 0, 0.5, NULL, NULL, NULL, ?, ?)",
            (usg, created, aid, created))
    conn.commit()
    monkeypatch.setattr(server.dsh_api, "get_dsh_summaries",
                        lambda *a, **k: {r: {"found": False} for r in a})
    p = server._dashboard_all_payload("custom", "2026-09-20 08:00:00", "2026-09-20 18:00:00")
    assert p["range"] == "custom"
    assert p["totals"]["request_count"] == 1


def test_dashboard_all_payload_custom_invalid_falls_back_today(tmp_server_db, monkeypatch):
    """Review Focus #1: 非法 custom 回退白名单默认 today, 不 500."""
    monkeypatch.setattr(server.dsh_api, "get_dsh_summaries",
                        lambda *a, **k: {r: {"found": False} for r in a})
    p = server._dashboard_all_payload("custom", None, None)
    assert p["range"] == "today"


def test_zcode_summary_payload_custom(tmp_server_db, monkeypatch):
    import pathlib
    monkeypatch.setattr(server.zcode_api, "ZCODE_DB", pathlib.Path("X:/nonexistent"))
    p = server._zcode_summary_payload("custom", "2026-09-20 08:00:00", "2026-09-20 18:00:00")
    assert p["db_found"] is False and p["range"] == "custom"
