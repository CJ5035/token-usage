"""POST /api/logout server 层语义 (EVOLUTION-2 Task 4 补缺口): 登出仅清凭证, 本地数据保留.

db 层语义由 test_db_credential_semantics.py / test_db_multiuser.py 覆盖;
本文件补 server 层缺口 (_FakeHandler 直调 _handle_api, 同
test_commandcode_sync.py:262-272 模式), 断言:
- 响应 {"ok": True};
- usage_records 保留, token 清空;
- 配额缓存槽被清理、overview 缓存被失效 (handler 特有副作用, db 层不可覆盖);
- 账号行保留且 GET /api/accounts 仍列出该行 (设置页未登录行可登录/删除的前提).
"""
from __future__ import annotations

import time

import pytest

from app import db, server


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库 + 重置 server 跨线程状态 (同 test_relogin_targeting.tmp_db)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    server._quota_cache.clear()
    server._quota_refreshing.clear()
    server._sync_state.update(
        running=False, mode="", page=0, inserted=0, phase="idle", message="", account=""
    )
    yield tmp_path
    db.close_db()


class _FakeHandler:
    """仅提供 _handle_api 需要的 command (logout/accounts 分支均不读 body)."""

    def __init__(self, command="POST"):
        self.command = command


def _call_api(monkeypatch, handler, path) -> dict:
    """直调 _handle_api, 捕获 _json_response 的 payload 与状态码."""
    captured: dict = {}
    monkeypatch.setattr(
        server, "_json_response",
        lambda h, data, status=200: captured.update({"data": data, "status": status}),
    )
    server._handle_api(handler, path, {})
    return captured


def _rec(usg_id):
    return {
        "usg_id": usg_id, "created_at": "2026-01-01T00:00:00Z", "model": "m", "provider": None,
        "input_tokens": 10, "output_tokens": 20, "reasoning_tokens": 0,
        "cache_read_tokens": 0, "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
        "cost_raw": 0, "cost_usd": 0.5, "key_id": None, "session_id": None, "plan": None,
    }


def test_api_logout_preserves_data_and_clears_token(tmp_db, monkeypatch):
    """POST /api/logout: usage_records 保留、token 清空、配额槽清理、overview 缓存失效."""
    aid = db.add_account("tA", "ws-a")                           # add 默认 switch -> 活跃=a
    db.insert_usage_records([_rec("a1"), _rec("a2")], account_id=aid)
    server._quota_cache[aid] = {"at": time.time(), "data": {"success": True}}   # 预置配额缓存槽
    server._overview_cache["data"] = {"ok": True, "accounts": []}               # 预置 overview 缓存

    resp = _call_api(monkeypatch, _FakeHandler("POST"), "/api/logout")

    assert resp == {"data": {"ok": True}, "status": 200}
    assert next(x for x in db.list_accounts() if x["id"] == aid)["has_token"] is False
    assert db.get_token() == ""                                  # 凭证已清
    assert db.totals(period="all", account_id=aid)["request_count"] == 2  # 数据保留
    assert aid not in server._quota_cache                        # 配额槽被清理 (防残留旧配额)
    assert server._overview_cache["data"] is None                # overview 缓存已失效


def test_api_logout_keeps_row_listed_for_settings_page(tmp_db, monkeypatch):
    """登出后账号行保留且 GET /api/accounts 仍列出 (未登录行可登录/删除的服务端前提)."""
    aid = db.add_account("tA", "ws-a")
    db.insert_usage_records([_rec("a1")], account_id=aid)

    assert _call_api(monkeypatch, _FakeHandler("POST"), "/api/logout")["data"] == {"ok": True}

    resp = _call_api(monkeypatch, _FakeHandler("GET"), "/api/accounts")
    assert resp["status"] == 200
    rows = {x["id"]: x for x in resp["data"]["accounts"]}
    assert aid in rows and rows[aid]["has_token"] is False       # 行在且未登录 -> 可登录/可删除
