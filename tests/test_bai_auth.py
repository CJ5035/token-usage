"""auth.py BAI 登录分支单测: session-token 三态 / cookie 双形态 / URL / LoginWatcher 判定.

LoginWatcher 测试用 mock win 对象 (get_current_url / get_cookies), 不建真窗.
"""
from __future__ import annotations

import json
import sys
import time
from http.cookies import SimpleCookie

import pytest

# webview 在测试环境未安装: 注入最小 stub 以满足 app.auth 顶层导入.
# 各用例用 mock win (get_current_url/get_cookies), 不会触及 webview.windows 真实逻辑.
_webview_stub = type(sys)("webview")
_webview_stub.windows = []
sys.modules.setdefault("webview", _webview_stub)

from app import auth  # noqa: E402
from app.auth import (  # noqa: E402
    _extract_bai_session,
    _login_window_title,
    build_bai_cookie_jar,
    build_login_url,
)


# ---------------------------------------------------------------------------
# _extract_bai_session 三态
# ---------------------------------------------------------------------------

def _simple_cookie(**pairs) -> SimpleCookie:
    c = SimpleCookie()
    for name, value in pairs.items():
        c[name] = value
    return c


def test_extract_session_populated_dict_form():
    cookies = [
        {"name": "__Secure-authjs.session-token", "value": "tok-123"},
        {"name": "__Host-authjs.csrf-token", "value": "csrf"},
        {"name": "authjs.callback-url", "value": "https://chat.b.ai/login"},
    ]
    assert _extract_bai_session(cookies) == "tok-123"


def test_extract_session_populated_simple_cookie_form():
    cookies = [
        _simple_cookie(**{"__Secure-authjs.session-token": "tok-456"}),
        _simple_cookie(**{"__Host-authjs.csrf-token": "csrf"}),
    ]
    assert _extract_bai_session(cookies) == "tok-456"


def test_extract_session_only_csrf_and_callback():
    """仅 csrf/callback 两个 cookie (登录前即存在) → None."""
    cookies = [
        _simple_cookie(**{"__Host-authjs.csrf-token": "csrf"}),
        _simple_cookie(**{"authjs.callback-url": "https://chat.b.ai/login"}),
    ]
    assert _extract_bai_session(cookies) is None


def test_extract_session_empty_value():
    """session-token 存在但为空值 → None."""
    cookies = [
        {"name": "__Secure-authjs.session-token", "value": ""},
        {"name": "__Host-authjs.csrf-token", "value": "csrf"},
    ]
    assert _extract_bai_session(cookies) is None


def test_extract_session_empty_list():
    assert _extract_bai_session([]) is None
    assert _extract_bai_session(None) is None


# ---------------------------------------------------------------------------
# build_bai_cookie_jar (cookie jar JSON 契约, Task 1 build_cookie_header 可解析)
# ---------------------------------------------------------------------------

def test_build_jar_contains_all_authjs_cookies():
    cookies = [
        _simple_cookie(**{"__Secure-authjs.session-token": "tok"}),
        _simple_cookie(**{"__Host-authjs.csrf-token": "csrf"}),
        _simple_cookie(**{"authjs.callback-url": "https://chat.b.ai/login"}),
        _simple_cookie(**{"prefers-color-scheme": "dark"}),
    ]
    jar = json.loads(build_bai_cookie_jar(cookies))
    assert jar == [
        {"name": "__Secure-authjs.session-token", "value": "tok"},
        {"name": "__Host-authjs.csrf-token", "value": "csrf"},
        {"name": "authjs.callback-url", "value": "https://chat.b.ai/login"},
    ]


def test_build_jar_without_session_returns_empty():
    cookies = [
        _simple_cookie(**{"__Host-authjs.csrf-token": "csrf"}),
        _simple_cookie(**{"authjs.callback-url": "https://chat.b.ai/login"}),
    ]
    assert build_bai_cookie_jar(cookies) == ""


def test_build_jar_dict_form():
    cookies = [
        {"name": "__Secure-authjs.session-token", "value": "tok"},
        {"name": "__Host-authjs.csrf-token", "value": "csrf"},
    ]
    jar = json.loads(build_bai_cookie_jar(cookies))
    assert jar == [
        {"name": "__Secure-authjs.session-token", "value": "tok"},
        {"name": "__Host-authjs.csrf-token", "value": "csrf"},
    ]


def test_build_jar_roundtrips_build_cookie_header():
    """jar 能被 Task 1 的 build_cookie_header 解析成 Cookie 头."""
    from app.bai_api import build_cookie_header
    cookies = [
        _simple_cookie(**{"__Secure-authjs.session-token": "tok"}),
        _simple_cookie(**{"__Host-authjs.csrf-token": "csrf"}),
    ]
    header = build_cookie_header(build_bai_cookie_jar(cookies))
    assert "__Secure-authjs.session-token=tok" in header
    assert "__Host-authjs.csrf-token=csrf" in header


# ---------------------------------------------------------------------------
# build_login_url / 标题
# ---------------------------------------------------------------------------

def test_build_login_url_default_is_opencode():
    url = build_login_url()
    assert url.startswith("https://auth.opencode.ai/authorize?")


def test_build_login_url_bai():
    assert build_login_url("bai") == "https://chat.b.ai/login"


def test_login_window_title():
    assert _login_window_title("bai") == "GoGauge - BAI Login"
    assert _login_window_title("opencode") == "GoGauge - OpenCode Go Login"


# ---------------------------------------------------------------------------
# fetch_bai_user_id 失败回退 (成功路径依赖真网, 单测只验失败/空号放宽)
# ---------------------------------------------------------------------------

def test_fetch_bai_user_id_empty_header(monkeypatch):
    assert auth.fetch_bai_user_id("") == ""


def test_fetch_bai_user_id_network_failure_returns_empty(monkeypatch):
    """凭证无效/网络异常 → 返回 "" 不抛异常, 登录不阻塞."""
    import urllib.error

    def boom(url, **kw):
        raise urllib.error.URLError("boom")

    monkeypatch.setattr(auth._urllib_request, "urlopen", boom)
    assert auth.fetch_bai_user_id("__Secure-authjs.session-token=x") == ""


# ---------------------------------------------------------------------------
# LoginWatcher BAI 分支 (mock win, 不建真窗)
# ---------------------------------------------------------------------------

class _MockWin:
    """模拟 pywebview 窗口: 可配置当前 URL 与 cookie 列表."""

    def __init__(self, url, cookies):
        self._url = url
        self._cookies = cookies

    def get_current_url(self):
        return self._url

    def get_cookies(self):
        return list(self._cookies)


def _run_watcher(win, account_type="bai"):
    """启动 watcher 并等待其判定 (成功/停止/超时), 返回回调捕获参数列表."""
    captured: list[tuple] = []

    def on_success(credential, hint, atype):
        captured.append((credential, hint, atype))

    w = auth.LoginWatcher(win, on_success, account_type=account_type)
    w.start()
    # 最多等 2s 让轮询完成判断; watcher 成功时 self._stop 已置位线程退出
    deadline = time.time() + 2.0
    while time.time() < deadline and not w.done:
        time.sleep(0.02)
    w.stop()
    return captured


def test_watcher_bai_success_on_chat_domain(monkeypatch):
    """URL 在 chat.b.ai 域 + session-token 非空 → 成功, 回调 (jar, userId, "bai")."""
    monkeypatch.setattr(auth, "fetch_bai_user_id", lambda h: "usr_1")
    win = _MockWin(
        "https://chat.b.ai/usage",
        [_simple_cookie(**{"__Secure-authjs.session-token": "tok"}),
         _simple_cookie(**{"__Host-authjs.csrf-token": "csrf"})],
    )
    captured = _run_watcher(win, account_type="bai")
    assert len(captured) == 1
    cred, hint, atype = captured[0]
    assert atype == "bai"
    assert hint == "usr_1"  # workspace_hint = userId (dedupe_key)
    jar = json.loads(cred)
    assert any(c["name"] == "__Secure-authjs.session-token" for c in jar)


def test_watcher_bai_userid_failure_falls_back_empty(monkeypatch):
    """getUserState 失败 → userId="" 回退 (credential 仍为 jar), 不加锁不阻塞."""
    monkeypatch.setattr(auth, "fetch_bai_user_id", lambda h: "")
    win = _MockWin(
        "https://chat.b.ai/usage",
        [_simple_cookie(**{"__Secure-authjs.session-token": "tok"})],
    )
    captured = _run_watcher(win, account_type="bai")
    assert len(captured) == 1
    assert captured[0][1] == ""       # dedupe_key 回退为空串
    assert captured[0][2] == "bai"


def test_watcher_bai_not_on_domain_no_success():
    """URL 不在 chat.b.ai 域 (Google 中间页等) → 不成功."""
    win = _MockWin("https://accounts.google.com/o/oauth2", [])
    captured = _run_watcher(win, account_type="bai")
    assert captured == []


def test_watcher_bai_only_csrf_no_success():
    """落在 chat.b.ai 域但仅 csrf/callback 两 cookie → 不成功."""
    win = _MockWin(
        "https://chat.b.ai/login",
        [_simple_cookie(**{"__Host-authjs.csrf-token": "csrf"}),
         _simple_cookie(**{"authjs.callback-url": "https://chat.b.ai/login"})],
    )
    captured = _run_watcher(win, account_type="bai")
    assert captured == []


def test_watcher_bai_empty_session_value_no_success():
    """落在 chat.b.ai 域但 session-token 为空值 → 不成功."""
    win = _MockWin(
        "https://chat.b.ai/login",
        [_simple_cookie(**{"__Secure-authjs.session-token": ""})],
    )
    captured = _run_watcher(win, account_type="bai")
    assert captured == []


# ---------------------------------------------------------------------------
# LoginWatcher opencode 分支默认参数兼容 (回归)
# ---------------------------------------------------------------------------

def test_watcher_opencode_default_param_passthrough(monkeypatch):
    """默认 account_type="opencode" → 走 opencode 成功判定 (auth cookie + URL 域)."""
    import app.auth as auth_mod

    called = {}
    monkeypatch.setattr(auth_mod, "_log", lambda _m: None)

    class Win:
        def get_current_url(self):
            return "https://opencode.ai/usage"

        def get_cookies(self):
            return [_simple_cookie(**{"auth": "secret"})]

    cap = {}

    def on_success(c, h, atype):
        cap["c"] = c
        cap["h"] = h
        cap["atype"] = atype

    w = auth.LoginWatcher(Win(), on_success)
    w.start()
    deadline = time.time() + 2.0
    while time.time() < deadline and not w.done:
        time.sleep(0.02)
    w.stop()
    assert cap.get("atype") == "opencode"
    assert cap.get("c") == "auth=secret"


def test_cls_importable():
    """auth 模块干净导入 (单测导入不依赖真窗)."""
    assert hasattr(auth, "LoginWatcher") and hasattr(auth, "build_login_url")
