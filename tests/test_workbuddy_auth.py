from __future__ import annotations

import json
import io
import sys
from http.cookies import SimpleCookie

import pytest

_webview_stub = type(sys)("webview")
_webview_stub.windows = []
sys.modules.setdefault("webview", _webview_stub)

from app import auth
from app import main
from app import server


class MockWin:
    def __init__(self, url, cookies):
        self.url = url
        self.cookies = cookies

    def get_current_url(self):
        return self.url

    def get_cookies(self):
        return self.cookies


def cookie(**pairs):
    c = SimpleCookie()
    for name, value in pairs.items():
        c[name] = value
    return c


def test_workbuddy_constants_and_login_url():
    assert "workbuddy" in auth._ACCOUNT_TYPES
    assert auth.build_login_url("workbuddy") == "https://www.workbuddy.cn/profile/plans-usage"
    assert "WorkBuddy" in auth._login_window_title("workbuddy")


def test_workbuddy_without_session_keeps_watching(monkeypatch):
    seen = []
    watcher = auth.LoginWatcher(MockWin("https://www.workbuddy.cn/auth/realms/copilot", [cookie(foo="bar")]), lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy("https://www.workbuddy.cn/auth/realms/copilot") is False
    assert seen == []


def test_workbuddy_session_succeeds_even_when_accounts_lookup_fails(monkeypatch):
    seen = []
    monkeypatch.setattr(auth, "WorkBuddyAPI", lambda _jar: (_ for _ in ()).throw(RuntimeError("offline")))
    watcher = auth.LoginWatcher(
        MockWin("https://www.workbuddy.cn/profile/plans-usage", [cookie(session="s1", tgw_l7_route="r1"), cookie(empty="")]),
        lambda *x: seen.append(x), account_type="workbuddy",
    )
    assert watcher._handle_workbuddy("https://www.workbuddy.cn/profile/plans-usage") is True
    assert seen[0][1:] == ("", "workbuddy")
    jar = json.loads(seen[0][0])
    assert {x["name"] for x in jar} == {"session", "tgw_l7_route"}


def test_workbuddy_accounts_user_id_is_best_effort_dedupe(monkeypatch):
    seen = []
    class FakeApi:
        def __init__(self, jar):
            self.jar = jar
        def fetch_accounts(self):
            return {"userId": "wb-user-1"}
    monkeypatch.setattr(auth, "WorkBuddyAPI", FakeApi)
    watcher = auth.LoginWatcher(MockWin("https://www.workbuddy.cn/profile/plans-usage", [cookie(session="s1", foo="bar")]), lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(watcher.win.url) is True
    assert seen[0][1:] == ("wb-user-1", "workbuddy")


def test_main_login_modes_include_workbuddy():
    seen = []
    api = main.WindowApi()
    api.set_login_callback(lambda mode, account_id: seen.append((mode, account_id)))
    api.open_login("add_workbuddy")
    assert seen == [("add_workbuddy", None)]


class AddHandler:
    command = "POST"

    def __init__(self, body):
        raw = json.dumps(body).encode()
        self.headers = {"Content-Length": str(len(raw))}
        self.rfile = io.BytesIO(raw)


def test_accounts_add_maps_workbuddy_source(monkeypatch):
    seen = []
    captured = {}
    monkeypatch.setattr(server, "_on_open_login", lambda mode, *args: seen.append((mode, args)))
    monkeypatch.setattr(server, "_json_response", lambda _h, data, status=200: captured.update(data=data, status=status))
    server._handle_api(AddHandler({"source": "workbuddy"}), "/api/accounts/add", {})
    assert seen == [("add_workbuddy", ())]
    assert captured == {"data": {"ok": True, "opened": True}, "status": 200}
