"""db.py 凭证语义测试 (EVOLUTION-2): 退出登录仅清凭证保留数据 + save_token 定向落库.

三组用例:
1. save_token 定向落库: account_id 指向非活跃行时凭证落目标行, 活跃行不受影响;
   游标重置同样只作用于目标行.
2. clear_account 语义: 仅清凭证, usage_records 保留; 重登 (save_token) 复用原行, 记录仍在.
3. prune 边界: 保留≠永久保留 — clear_account 后数据保留, prune_old_records(window_days)
   仍按窗裁剪过期记录.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库: 重定向 data_dir 并重置模块级连接 (同 test_db_multiuser 夹具)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


def _rec(usg_id, created="2026-01-01T00:00:00Z", model="m", inp=10, outp=20, cost_usd=0.5):
    return {
        "usg_id": usg_id, "created_at": created, "model": model, "provider": None,
        "input_tokens": inp, "output_tokens": outp, "reasoning_tokens": 0,
        "cache_read_tokens": 0, "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
        "cost_raw": 0, "cost_usd": cost_usd, "key_id": None, "session_id": None, "plan": None,
    }


def _now_iso_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# save_token 定向落库 (account_id 可选参数)
# ---------------------------------------------------------------------------


def test_save_token_targeted_lands_on_given_account(tmp_db):
    """save_token(account_id=...) 定向落库: 非活跃行凭证更新, 活跃行不受影响."""
    a = db.add_account("tA", "ws-a")
    b = db.add_account("tB", "ws-b")            # add 默认 switch -> 活跃=b
    db.save_resolved_workspace("wrk-a-resolved", account_id=a)   # 预置定向行的已解析工作区
    conn = db.get_db()
    conn.execute("UPDATE usage_sync_state SET deepest_page_fetched = 9 WHERE account_id = ?", (a,))
    conn.execute("UPDATE usage_sync_state SET deepest_page_fetched = 5 WHERE account_id = ?", (b,))
    conn.commit()

    db.save_token("tA-new", "ws-a2", account_id=a)               # 定向登录 a (非活跃行)

    rows = {r["id"]: r["token"] for r in conn.execute("SELECT id, token FROM accounts")}
    assert rows[a] == "tA-new" and rows[b] == "tB"               # 落目标行, 活跃行不动
    row_a = next(x for x in db.list_accounts() if x["id"] == a)
    assert row_a["workspace_id"] == "ws-a2"
    assert row_a["resolved_workspace_id"] is None                # 重登语义: 已解析工作区复位
    assert db.get_sync_state(a)["deepest_page_fetched"] == -1    # 目标行游标重置
    assert db.get_sync_state(b)["deepest_page_fetched"] == 5     # 活跃行游标不动
    assert db.get_token() == "tB"                                # 活跃凭证仍为 b
    assert db.get_active_account_id() == b                       # 定向落库不切换活跃


# ---------------------------------------------------------------------------
# clear_account 语义: 仅清凭证, 数据保留, 重登复用行
# ---------------------------------------------------------------------------


def test_clear_account_keeps_data_and_relogin_reuses_row(tmp_db):
    """退出登录: token 清空但数据保留; 重登 (save_token) 复用原行, 记录仍在."""
    a = db.add_account("tA", "ws-a")            # add 默认 switch -> 活跃=a
    db.insert_usage_records([_rec("a1"), _rec("a2")], account_id=a)

    db.clear_account()

    row = next(x for x in db.list_accounts() if x["id"] == a)
    assert row["has_token"] is False                             # 凭证清空
    assert db.count_accounts() == 2                              # 账号行保留 (种子 + a)
    assert db.totals(period="all", account_id=a)["request_count"] == 2   # 数据保留

    db.save_token("tA-new", "ws-a")                               # 重登: 全部未登录时活跃仍指向 a

    assert db.count_accounts() == 2                               # 未产生新行 (复用原行)
    assert db.get_active_account_id() == a
    assert db.get_token() == "tA-new"
    assert db.totals(period="all", account_id=a)["request_count"] == 2   # 重登后记录仍在


# ---------------------------------------------------------------------------
# prune 边界: 保留≠永久保留
# ---------------------------------------------------------------------------


def test_clear_account_then_prune_still_trims_by_window(tmp_db):
    """clear_account 后数据保留, prune_old_records(window_days) 仍按窗裁剪过期记录."""
    a = db.add_account("tA", "ws-a")
    db.insert_usage_records([_rec("old", created="2026-01-01T00:00:00Z")], account_id=a)
    db.insert_usage_records([_rec("fresh", created=_now_iso_z())], account_id=a)

    db.clear_account()
    assert db.totals(period="all", account_id=a)["request_count"] == 2   # 登出后数据保留

    deleted = db.prune_old_records(30, account_id=a)

    assert deleted == 1                                           # 窗外旧记录被裁剪
    assert db.totals(period="all", account_id=a)["request_count"] == 1
    records, total = db.usage_records_page(page=1, page_size=10, account_id=a)
    assert total == 1 and records[0]["usg_id"] == "fresh"
