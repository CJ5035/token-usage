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
    """模拟登录窗口: probe_result 为窗口内 fetch 的最终结果 (dict/None), probe_error 模拟 evaluate_js 异常."""

    def __init__(self, url, cookies, probe_result=None, probe_error=None):
        self.url = url
        self.cookies = cookies
        self.probe_result = probe_result
        self.probe_error = probe_error
        self.probe_calls = []

    def get_current_url(self):
        return self.url

    def get_cookies(self):
        return self.cookies

    def evaluate_js(self, script):
        self.probe_calls.append(script)
        if self.probe_error is not None:
            raise self.probe_error
        if "return slot" in script:  # 起搏脚本: 返回槽名 (与 auth._build_wb_probe_js 产物对应)
            return script.split('var slot = "')[1].split('"')[0]
        return self.probe_result  # 轮询/清理脚本: 返回槽内结果


def cookie(**pairs):
    c = SimpleCookie()
    for name, value in pairs.items():
        c[name] = value
    return c


def test_workbuddy_constants_and_login_url():
    assert "workbuddy" in auth._ACCOUNT_TYPES
    assert auth.build_login_url("workbuddy") == "https://www.workbuddy.cn/profile/plans-usage"
    assert "WorkBuddy" in auth._login_window_title("workbuddy")


@pytest.mark.parametrize(
    "url",
    [
        "https://www.workbuddy.cn/login/",
        "https://www.workbuddy.cn/auth/realms/copilot",
        "https://www.workbuddy.cn.example.org/profile/plans-usage",
        "http://www.workbuddy.cn/profile/plans-usage",
    ],
)
def test_workbuddy_gate_rejects_non_profile_urls(url):
    """非 https / 非本域 / 非 profile 路径一律不探测 (匿名 session 存在也不触发)."""
    seen = []
    win = MockWin(url, [cookie(session="s1")], probe_result={"accounts": [{"uid": "u1"}]})
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(url) is False
    assert win.probe_calls == []
    assert seen == []


def test_workbuddy_probe_success_saves_uid_and_jar():
    seen = []
    win = MockWin(
        "https://www.workbuddy.cn/profile/plans-usage",
        [cookie(session="s1", foo="bar")],
        probe_result={
            "status": 200, "path": "/console/accounts", "ct": "application/json",
            "body": json.dumps({"code": 0, "data": {"accounts": [{"uid": "wb-user-1", "nickname": "骏"}]}}),
        },
    )
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(win.url) is True
    assert watcher.done is True
    assert len(seen) == 1
    credential, user_id, account_type = seen[0]
    assert account_type == "workbuddy"
    assert user_id == "wb-user-1"
    assert {"name": "session", "value": "s1"} in json.loads(credential)


def test_workbuddy_probe_prefers_last_login_account():
    """官网规则: data.accounts[] 中优先取带 lastLogin 的账号 (20260915 诊断 §11.2)."""
    seen = []
    accounts = [
        {"uid": "uid-first", "nickname": "a"},
        {"uid": "uid-lastlogin", "lastLogin": "2026-09-15", "nickname": "b"},
    ]
    win = MockWin(
        "https://www.workbuddy.cn/profile/plans-usage", [],
        probe_result={"status": 200, "path": "/console/accounts", "ct": "application/json",
                      "body": json.dumps({"data": {"accounts": accounts}})},
    )
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(win.url) is True
    assert seen[0][1] == "uid-lastlogin"


def test_workbuddy_probe_uid_coerced_to_str():
    seen = []
    win = MockWin(
        "https://www.workbuddy.cn/profile/plans-usage", [],
        probe_result={"status": 200, "path": "/console/accounts", "ct": "application/json",
                      "body": json.dumps({"data": {"accounts": [{"uid": 12345}]}})},
    )
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(win.url) is True
    assert seen[0][1] == "12345"


def test_workbuddy_probe_missing_uid_keeps_watching():
    """uid 是去重/重登身份键, 取不到不允许落库 (不再容忍空 userId)."""
    seen = []
    win = MockWin(
        "https://www.workbuddy.cn/profile/plans-usage", [cookie(session="s1")],
        probe_result={"status": 200, "path": "/console/accounts", "ct": "application/json",
                      "body": json.dumps({"data": {"accounts": [{"nickname": "n"}]}})},
    )
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(win.url) is False
    assert seen == [] and not watcher.done


@pytest.mark.parametrize(
    "result, expected",
    [
        (None, "probe_inconclusive"),
        ({"status": 0, "error": "AbortError"}, "network_error"),
        ({"status": 200, "path": "/auth/realms/copilot/protocol/openid-connect/auth", "ct": "text/html", "body": "<html>"}, "redirect_to_login"),
        ({"status": 502, "path": "/console/accounts", "ct": "text/html", "body": "<html>"}, "http_502"),
        ({"status": 200, "path": "/console/accounts", "ct": "text/html", "body": "<html>login-pf</html>"}, "non_json_response"),
        ({"status": 200, "path": "/console/accounts", "ct": "application/json", "body": "not-json"}, "non_json_response"),
        ({"status": 200, "path": "/console/accounts", "ct": "application/json", "body": '{"code":0}'}, "empty_accounts"),
        ({"status": 200, "path": "/console/accounts", "ct": "application/json", "body": '{"data":{"accounts":[]}}'}, "empty_accounts"),
    ],
)
def test_workbuddy_classify_probe_reason_codes(result, expected):
    reason, accounts = auth.LoginWatcher._wb_classify_probe(result)
    assert reason == expected
    assert accounts == []


def test_workbuddy_anonymous_session_not_treated_as_login():
    """回归 (20260915 诊断 §11.1): 匿名 session Cookie(276字符)存在≠已登录, 探测被拒不得回填."""
    seen = []
    win = MockWin(
        "https://www.workbuddy.cn/profile/plans-usage",
        [cookie(session="a" * 276)],
        probe_result={"status": 200, "path": "/auth/realms/copilot/protocol/openid-connect/auth",
                      "ct": "text/html", "body": "<html>login-pf</html>"},
    )
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(win.url) is False
    assert seen == [] and not watcher.done and not watcher._stop.is_set()


def test_workbuddy_probe_throttled_and_recovers(monkeypatch):
    current_time = 1000.0
    monkeypatch.setattr("time.monotonic", lambda: current_time)
    seen = []
    win = MockWin(
        "https://www.workbuddy.cn/profile/plans-usage", [cookie(session="s1")],
        probe_result={"status": 200, "path": "/auth/realms/x", "ct": "text/html", "body": "<html>"},
    )
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(win.url) is False
    current_time += 1.0  # 3s 节流窗口内: 不再起搏新探测
    assert watcher._handle_workbuddy(win.url) is False
    started = [s for s in win.probe_calls if "return slot" in s]
    assert len(started) == 1
    current_time += 3.0  # 节流过期: 下一次探测成功
    win.probe_result = {"status": 200, "path": "/console/accounts", "ct": "application/json",
                        "body": json.dumps({"data": {"accounts": [{"uid": "u1"}]}})}
    assert watcher._handle_workbuddy(win.url) is True
    assert seen[0][1:] == ("u1", "workbuddy")


def test_workbuddy_evaluate_js_error_keeps_watching():
    seen = []
    win = MockWin("https://www.workbuddy.cn/profile/plans-usage", [cookie(session="s1")], probe_error=RuntimeError("no script"))
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(win.url) is False
    assert seen == [] and not watcher.done


def test_workbuddy_probe_timeout_keeps_watching(monkeypatch):
    monkeypatch.setattr(auth, "_WB_POLL_TIMEOUT", 0.2)  # 缩短真实等待
    monkeypatch.setattr("time.sleep", lambda *_: None)
    seen = []
    win = MockWin("https://www.workbuddy.cn/profile/plans-usage", [cookie(session="s1")], probe_result=None)
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    assert watcher._handle_workbuddy(win.url) is False
    assert seen == [] and not watcher.done


def test_workbuddy_stop_before_success_no_callback():
    seen = []
    win = MockWin(
        "https://www.workbuddy.cn/profile/plans-usage", [cookie(session="s1")],
        probe_result={"status": 200, "path": "/console/accounts", "ct": "application/json",
                      "body": json.dumps({"data": {"accounts": [{"uid": "u1"}]}})},
    )
    watcher = auth.LoginWatcher(win, lambda *x: seen.append(x), account_type="workbuddy")
    watcher.stop()
    assert watcher._handle_workbuddy(win.url) is False
    assert seen == [] and watcher.done is False


def test_watcher_start_idempotent_after_done():
    win = MockWin("https://www.workbuddy.cn/profile/plans-usage", [])
    watcher = auth.LoginWatcher(win, lambda *args: None, account_type="workbuddy")
    watcher.done = True
    watcher.start()
    assert watcher._thread is None


def test_watcher_start_idempotent_after_stop():
    win = MockWin("https://www.workbuddy.cn/profile/plans-usage", [])
    watcher = auth.LoginWatcher(win, lambda *args: None, account_type="workbuddy")
    watcher.stop()
    watcher.start()
    assert watcher._thread is None
    assert watcher._stop.is_set()


def test_concurrent_start_spawns_single_thread(monkeypatch):
    import threading
    created = []
    real_thread = threading.Thread
    def mock_thread(*args, **kwargs):
        t = real_thread(*args, **kwargs)
        created.append(t)
        return t
    monkeypatch.setattr("threading.Thread", mock_thread)
    win = MockWin("https://www.workbuddy.cn/profile/plans-usage", [])
    watcher = auth.LoginWatcher(win, lambda *args: None, account_type="workbuddy")
    t1 = real_thread(target=watcher.start)
    t2 = real_thread(target=watcher.start)
    t1.start(); t2.start()
    t1.join(); t2.join()
    watcher_threads = [t for t in created if getattr(t, "name", "") == "gousage-login"]
    assert len(watcher_threads) == 1
    watcher.stop()




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
