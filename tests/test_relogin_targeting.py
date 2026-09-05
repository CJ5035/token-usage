"""定向重登 (EVOLUTION-2 Task 2): 登录目标 id 全链透传 + /api/relogin 分派 + 串号回归.

- WindowApi.open_login 契约级透传: 回调实参为 (mode, account_id)
  (pending_mode 在 main() 闭包内测试不可达, 闭包行为由串号回归端到端覆盖);
- /api/relogin: 带 id / 不带 id / 空 body 三态分派 (_FakeHandler 直调 _handle_api,
  同 test_commandcode_sync.py:262-272 模式);
- 目标行不存在 / id 非法 -> 400;
- db 层组合串号回归: 定向 save_token(id=B) + set_active_account(B) 后
  B token 更新、A token 不动、活跃 == B.
"""
from __future__ import annotations

import io
import json

import pytest

from app import db, server
from app import main as app_main


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库 + 重置 server 跨线程状态 (同 test_commandcode_sync.tmp_db)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    server._quota_cache.clear()
    server._quota_refreshing.clear()
    server._sync_state.update(
        running=False, mode="", page=0, inserted=0, phase="idle", message="", account=""
    )
    yield tmp_path
    db.close_db()


# ---------------------------------------------------------------------------
# WindowApi.open_login 契约级透传
# ---------------------------------------------------------------------------

def test_windowapi_open_login_passes_target_id():
    """open_login("relogin", id) -> 回调实参为 (mode, id)."""
    api = app_main.WindowApi()
    calls: list[tuple] = []
    api.set_login_callback(lambda mode, account_id: calls.append((mode, account_id)))
    api.open_login("relogin", 7)
    assert calls == [("relogin", 7)]


def test_windowapi_open_login_defaults_and_whitelist():
    """既有不传参调用兼容 (account_id=None); 非法 mode 回退 relogin 但 id 照传."""
    api = app_main.WindowApi()
    calls: list[tuple] = []
    api.set_login_callback(lambda mode, account_id: calls.append((mode, account_id)))
    api.open_login("add")
    api.open_login("nonsense", 3)
    assert calls == [("add", None), ("relogin", 3)]


# ---------------------------------------------------------------------------
# /api/relogin 分派 (_FakeHandler 直调 _handle_api)
# ---------------------------------------------------------------------------

class _FakeHandler:
    command = "POST"

    def __init__(self, body=None):
        if body is None:  # 空 body (Content-Length=0, 欢迎页兜底形态)
            self.headers = {}
            self.rfile = io.BytesIO(b"")
        else:
            data = json.dumps(body).encode("utf-8")
            self.headers = {"Content-Length": str(len(data))}
            self.rfile = io.BytesIO(data)


def _post_relogin(monkeypatch, handler) -> dict:
    """直调 _handle_api, 捕获 _json_response 的 payload 与状态码."""
    captured: dict = {}
    monkeypatch.setattr(
        server, "_json_response",
        lambda h, data, status=200: captured.update({"data": data, "status": status}),
    )
    server._handle_api(handler, "/api/relogin", {})
    return captured


def test_relogin_with_id_dispatches_target(tmp_db, monkeypatch):
    """body {"id": N} -> 回调 ("relogin", N)."""
    aid = db.add_account("tok-a", "ws-a", switch=True)
    calls: list[tuple] = []
    monkeypatch.setattr(server, "_on_open_login",
                        lambda mode, account_id: calls.append((mode, account_id)))
    resp = _post_relogin(monkeypatch, _FakeHandler({"id": aid}))
    assert calls == [("relogin", aid)]
    assert resp == {"data": {"ok": True}, "status": 200}


def test_relogin_without_id_or_empty_body_falls_back_active(tmp_db, monkeypatch):
    """三态分派: 无 body / body={} / {"id": null} -> 一律 ("relogin", None), 不破坏欢迎页兜底."""
    db.add_account("tok-a", "ws-a", switch=True)
    calls: list[tuple] = []
    monkeypatch.setattr(server, "_on_open_login",
                        lambda mode, account_id: calls.append((mode, account_id)))
    for handler in (_FakeHandler(), _FakeHandler({}), _FakeHandler({"id": None})):
        resp = _post_relogin(monkeypatch, handler)
        assert resp["status"] == 200
        assert resp["data"] == {"ok": True}
    assert calls == [("relogin", None), ("relogin", None), ("relogin", None)]


def test_relogin_invalid_or_unknown_id_returns_400(tmp_db, monkeypatch):
    """id 非法 (非整数) / 账号不存在 -> 400 且不触发回调 (中文直出口径)."""
    db.add_account("tok-a", "ws-a", switch=True)
    calls: list[tuple] = []
    monkeypatch.setattr(server, "_on_open_login",
                        lambda mode, account_id: calls.append((mode, account_id)))

    resp = _post_relogin(monkeypatch, _FakeHandler({"id": 99999}))
    assert resp["status"] == 400
    assert resp["data"] == {"ok": False, "error": "账号不存在"}

    resp = _post_relogin(monkeypatch, _FakeHandler({"id": "abc"}))
    assert resp["status"] == 400
    assert resp["data"] == {"ok": False, "error": "无效账号 id"}

    assert calls == []


# ---------------------------------------------------------------------------
# 串号回归 (db 层组合, 模拟 on_login_success relogin 分支的落库顺序)
# ---------------------------------------------------------------------------

def test_targeted_relogin_lands_on_target_row_no_crosstalk(tmp_db):
    """定向重登 B: B token 更新、A token 不动、活跃 == B (显式 set 后为准)."""
    aid_a = db.add_account("tok-a-old", "ws-a", switch=True)
    aid_b = db.add_account("tok-b-old", "ws-b", switch=False)
    db.set_active_account(aid_a)
    assert db.get_active_account_id() == aid_a

    # on_login_success relogin 分支同序: save_token(定向) 成功后同一事务路径切活跃
    db.save_token("tok-b-new", "ws-b-new", account_id=aid_b)
    assert db.set_active_account(aid_b)

    assert db.get_account_credentials(aid_b)[0] == "tok-b-new"
    assert db.get_account_credentials(aid_b)[1] == "ws-b-new"
    assert db.get_account_credentials(aid_a)[0] == "tok-a-old"
    assert db.get_active_account_id() == aid_b
