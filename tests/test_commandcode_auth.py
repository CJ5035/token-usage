"""auth.py CommandCode 登录分支单测: URL/标题/账号类型/LoginWatcher 判定与容错.

LoginWatcher 测试用 mock win 对象 (get_current_url / get_cookies), 不建真窗.
"""
from __future__ import annotations

import json
import sys
import time
from http.cookies import SimpleCookie

import pytest

# webview 在测试环境未安装: 注入最小 stub 以满足 app.auth 顶层导入 (同 test_bai_auth.py).
# 各用例用 mock win (get_current_url/get_cookies), 不会触及 webview.windows 真实逻辑.
_webview_stub = type(sys)("webview")
_webview_stub.windows = []
sys.modules.setdefault("webview", _webview_stub)

import app.commandcode_api as cc_api  # noqa: E402
from app import auth  # noqa: E402
from app.auth import (  # noqa: E402
    _ACCOUNT_TYPES,
    _login_window_title,
    build_login_url,
    CC_ACCOUNT_TYPE,
    CC_LOGIN_URL,
)


# ---------------------------------------------------------------------------
# build_login_url / 窗口标题 / 账号类型常量
# ---------------------------------------------------------------------------

def test_build_login_url_commandcode():
    assert build_login_url("commandcode") == "https://commandcode.ai/signin"
    assert CC_LOGIN_URL == "https://commandcode.ai/signin"


def test_build_login_url_bai_opencode_unchanged():
    """既有 opencode/bai 行为不回归."""
    assert build_login_url("bai") == "https://chat.b.ai/login"
    assert build_login_url().startswith("https://auth.opencode.ai/authorize?")


def test_login_window_title_commandcode():
    assert _login_window_title("commandcode") == "GoGauge - Command Code Login"
    assert _login_window_title("bai") == "GoGauge - BAI Login"
    assert _login_window_title("opencode") == "GoGauge - OpenCode Go Login"


def test_account_types_contains_commandcode():
    assert "commandcode" in _ACCOUNT_TYPES
    assert CC_ACCOUNT_TYPE == "commandcode"


def test_watcher_commandcode_account_type_no_fallback():
    """account_type="commandcode" 不回退 "opencode"."""
    w = auth.LoginWatcher(_MockWin("", []), lambda *_a: None,
                          account_type="commandcode")
    assert w.account_type == "commandcode"


# ---------------------------------------------------------------------------
# LoginWatcher CommandCode 分支 (mock win, 不建真窗)
# ---------------------------------------------------------------------------

def _simple_cookie(**pairs) -> SimpleCookie:
    c = SimpleCookie()
    for name, value in pairs.items():
        c[name] = value
    return c


class _MockWin:
    """模拟 pywebview 窗口: 可配置当前 URL 与 cookie 列表."""

    def __init__(self, url, cookies):
        self._url = url
        self._cookies = cookies

    def get_current_url(self):
        return self._url

    def get_cookies(self):
        return list(self._cookies)


def _run_watcher(win, account_type="commandcode"):
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


def test_watcher_commandcode_success(monkeypatch):
    """本域 + 会话 cookie → 成功, 回调 (jar_json, userId, "commandcode")."""
    seen = {}

    def fake_fetch(cookie_header):
        seen["cookie_header"] = cookie_header
        return {"userId": "u-1"}

    monkeypatch.setattr(cc_api, "fetch_subscription", fake_fetch)
    win = _MockWin(
        "https://commandcode.ai/dashboard",
        [_simple_cookie(**{"better-auth.session_token": "tok-1"}),
         _simple_cookie(**{"theme": "dark"})],
    )
    captured = _run_watcher(win, account_type="commandcode")
    assert len(captured) == 1
    cred, hint, atype = captured[0]
    assert atype == "commandcode"
    assert hint == "u-1"  # workspace_hint = userId (dedupe_key)
    # jar 收集页面上全部非空 cookie (不做前缀过滤)
    jar = json.loads(cred)
    assert jar == [
        {"name": "better-auth.session_token", "value": "tok-1"},
        {"name": "theme", "value": "dark"},
    ]
    # jar → cookie 头 (fetch_subscription 的输入)
    assert seen["cookie_header"] == "better-auth.session_token=tok-1; theme=dark"


@pytest.mark.parametrize(
    "session_name",
    ["better-auth.session_token", "app.session_token", "sessionid"],
)
def test_watcher_commandcode_robust_session_names(monkeypatch, session_name):
    """会话 cookie 名未最终确认: 精确名/后缀 "session_token"/名含 "session" 均判定成功."""
    monkeypatch.setattr(cc_api, "fetch_subscription", lambda h: {"userId": "u-1"})
    win = _MockWin(
        "https://commandcode.ai/dashboard",
        [_simple_cookie(**{session_name: "tok"})],
    )
    captured = _run_watcher(win, account_type="commandcode")
    assert len(captured) == 1
    assert captured[0][1] == "u-1"
    assert captured[0][2] == "commandcode"


def test_watcher_commandcode_fetch_raises_falls_back_empty(monkeypatch):
    """fetch_subscription 抛错 → 仍成功, workspace_hint 回退 "" 不去重."""
    def boom(_cookie_header):
        raise RuntimeError("network down")

    monkeypatch.setattr(cc_api, "fetch_subscription", boom)
    win = _MockWin(
        "https://commandcode.ai/dashboard",
        [_simple_cookie(**{"better-auth.session_token": "tok"})],
    )
    captured = _run_watcher(win, account_type="commandcode")
    assert len(captured) == 1
    assert captured[0][1] == ""
    assert captured[0][2] == "commandcode"


def test_watcher_commandcode_fetch_returns_none_falls_back_empty(monkeypatch):
    """fetch_subscription 返回 None → 仍成功, workspace_hint 回退 ""."""
    monkeypatch.setattr(cc_api, "fetch_subscription", lambda h: None)
    win = _MockWin(
        "https://commandcode.ai/dashboard",
        [_simple_cookie(**{"better-auth.session_token": "tok"})],
    )
    captured = _run_watcher(win, account_type="commandcode")
    assert len(captured) == 1
    assert captured[0][1] == ""
    assert captured[0][2] == "commandcode"


def test_watcher_commandcode_off_domain_no_success():
    """URL 不在 commandcode.ai 域 (GitHub OAuth 中间页等) → 不成功."""
    win = _MockWin("https://github.com/login/oauth", [])
    captured = _run_watcher(win, account_type="commandcode")
    assert captured == []


def test_watcher_commandcode_no_session_cookie_no_success():
    """落在 commandcode.ai 域但仅无关 cookie → 不成功."""
    win = _MockWin(
        "https://commandcode.ai/signin",
        [_simple_cookie(**{"theme": "dark"}),
         _simple_cookie(**{"csrf-token": "x"})],
    )
    captured = _run_watcher(win, account_type="commandcode")
    assert captured == []


def test_watcher_commandcode_empty_session_value_no_success():
    """会话 cookie 存在但 value 为空 → 不成功 (继续轮询)."""
    win = _MockWin(
        "https://commandcode.ai/signin",
        [_simple_cookie(**{"better-auth.session_token": ""})],
    )
    captured = _run_watcher(win, account_type="commandcode")
    assert captured == []
