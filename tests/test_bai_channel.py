"""bai_channel.py 单测: JS 构建 / 质询等待 / cookie 同步 / 结果槽编排 / 传输层注册 (FakeWindow, 不启动 GUI)."""
from __future__ import annotations

import itertools
import json

import pytest

from app import bai_api, bai_channel

# fixture 会 patch 模块属性, 收集期保存真函数供质询等待/cookie 同步用例直测
_wait_challenge_ready_fn = bai_channel._wait_challenge_ready
_sync_account_cookies_fn = bai_channel._sync_account_cookies


# --------------------------- FakeWindow ------------------------------------

class _FakeEvents:
    def wait(self, timeout=None):
        return True


class _FakeAsyncResult:
    """模拟 IAsyncResult: AsyncWaitHandle.WaitOne 可控 (封送超时用例返回 False)."""

    def __init__(self, wait_ok):
        self.AsyncWaitHandle = self
        self._wait_ok = wait_ok

    def WaitOne(self, ms):
        return self._wait_ok


class _FakeEdge:
    """win.native: webview.BeginInvoke 模拟 WinForms Control.BeginInvoke (及时执行委托)."""

    def __init__(self, core=None, wait_ok=True):
        self.webview = self
        self.CoreWebView2 = core if core is not None else object()
        self._wait_ok = wait_ok

    def BeginInvoke(self, delegate):
        if self._wait_ok:
            delegate()  # 模拟 UI 线程及时执行
        return _FakeAsyncResult(self._wait_ok)


class _FakeCookie:
    def __init__(self, name, value):
        self.Name = name
        self.Value = value
        self.IsSecure = False


class _FakeCookieManager:
    """CoreWebView2.CookieManager: 记录 CreateCookie/AddOrUpdateCookie 调用."""

    def __init__(self):
        self.created = []
        self.added = []

    def CreateCookie(self, name, value, domain, path):
        self.created.append((name, value, domain, path))
        return _FakeCookie(name, value)

    def AddOrUpdateCookie(self, cookie):
        self.added.append(cookie)


class _FakeCoreWebView2:
    """仅提供 CookieManager (round 4: 会话 cookie 写 profile, 不再走头注入)."""

    def __init__(self, cookie_manager):
        self.CookieManager = cookie_manager


class FakeWindow:
    def __init__(self, script_results):
        # script_results: evaluate_js 依次返回的值 (None 表示槽未就绪)
        self.results = list(script_results)
        self.calls = []
        self.events = _FakeEvents()
        self.native = _FakeEdge()

    def evaluate_js(self, js):
        self.calls.append(js)
        if self.results:
            return self.results.pop(0)
        return None


@pytest.fixture(autouse=True)
def _reset_channel_state(monkeypatch):
    """通道模块状态隔离: 屏蔽质询等待与账号 cookie 同步; 重置 slot 序列, 使各用例 slot 恒为 r1
    (用例预期启动值不依赖执行顺序, 支持单独运行单个用例). yield 记录被同步的 cookie 头."""
    monkeypatch.setattr(bai_channel, "_wait_challenge_ready", lambda win, timeout: None)
    synced: list[str] = []
    monkeypatch.setattr(
        bai_channel, "_sync_account_cookies", lambda edge, cookie: synced.append(cookie)
    )
    monkeypatch.setattr(bai_channel, "_window", None)
    monkeypatch.setattr(bai_channel, "_slot_seq", itertools.count(1))
    yield synced


# --------------------------- build_fetch_js --------------------------------

def test_build_fetch_js_contains_url_slot_and_include_credentials():
    js = bai_channel.build_fetch_js("https://chat.b.ai/trpc/lambda/usage.points?input=x", "r7", 30.0)
    assert 'var slot = "r7"' in js
    assert "https://chat.b.ai/trpc/lambda/usage.points?input=x" in js
    assert 'credentials: "include"' in js  # 浏览器自动携带 profile 全套 cookie (含 cf_clearance)
    assert "30000" in js  # timeout_sec -> 毫秒


# --------------------------- fetch_through_window --------------------------

def test_fetch_success_flow(monkeypatch):
    win = FakeWindow(["r1", None, {"status": 200, "cf": "", "body": '{"points_balance":3}'}])
    monkeypatch.setattr(bai_channel, "_ready_window", lambda timeout: win)
    monkeypatch.setattr(bai_channel.time, "sleep", lambda s: None)
    status, text, headers = bai_channel.fetch_through_window("https://u", "a=1", 30.0)
    assert (status, text, headers) == (200, '{"points_balance":3}', {})
    assert win.calls[0].startswith("(function(){")  # 首个调用是启动 JS
    assert any("delete window.__gousage" in c for c in win.calls)  # 槽已清理


def test_fetch_polls_until_result(monkeypatch):
    win = FakeWindow(["r1", None, None, {"status": 200, "cf": "", "body": "ok"}])
    monkeypatch.setattr(bai_channel, "_ready_window", lambda timeout: win)
    monkeypatch.setattr(bai_channel.time, "sleep", lambda s: None)
    status, text, _ = bai_channel.fetch_through_window("https://u", "", 30.0)
    assert (status, text) == (200, "ok")


def test_fetch_timeout_raises_timeout_error(monkeypatch):
    win = FakeWindow(["r1"] + [None] * 500)
    monkeypatch.setattr(bai_channel, "_ready_window", lambda timeout: win)
    monkeypatch.setattr(bai_channel.time, "sleep", lambda s: None)
    monkeypatch.setattr(bai_channel, "POLL_TIMEOUT", 0.2)
    with pytest.raises(TimeoutError):
        bai_channel.fetch_through_window("https://u", "", 30.0)


def test_fetch_js_abort_maps_to_timeout_error(monkeypatch):
    win = FakeWindow(["r1", {"status": 0, "error": "AbortError"}])
    monkeypatch.setattr(bai_channel, "_ready_window", lambda timeout: win)
    with pytest.raises(TimeoutError):
        bai_channel.fetch_through_window("https://u", "", 30.0)


def test_fetch_http_error_maps_to_timeout_for_retry(monkeypatch):
    """status==0 非 abort 的 JS 异常 → OSError (bai_api._fetch 会重试)."""
    win = FakeWindow(["r1", {"status": 0, "error": "TypeError: failed to fetch"}])
    monkeypatch.setattr(bai_channel, "_ready_window", lambda timeout: win)
    with pytest.raises(OSError):
        bai_channel.fetch_through_window("https://u", "", 30.0)


def test_fetch_challenge_header_passthrough(monkeypatch):
    win = FakeWindow(["r1", {"status": 403, "cf": "challenge", "body": "<html/>"}])
    monkeypatch.setattr(bai_channel, "_ready_window", lambda timeout: win)
    status, _, headers = bai_channel.fetch_through_window("https://u", "", 30.0)
    assert status == 403
    assert headers.get("Cf-Mitigated") == "challenge"


def test_start_js_failure_raises_bai_error(monkeypatch):
    win = FakeWindow([None])  # 启动 JS 未返回 slot id → 执行失败
    monkeypatch.setattr(bai_channel, "_ready_window", lambda timeout: win)
    with pytest.raises(bai_api.BAIError, match="通道"):
        bai_channel.fetch_through_window("https://u", "", 30.0)


# --------------------------- _wait_challenge_ready -------------------------

def test_wait_challenge_ready_polls_until_ready(monkeypatch):
    # title 序列: 质询中文页 → None (跳转中) → 空串 → 质询英文页 → 就绪标题
    win = FakeWindow(["请稍候…", None, "", "Just a moment...", "BAI"])
    sleeps = []
    monkeypatch.setattr(bai_channel.time, "sleep", lambda s: sleeps.append(s))
    _wait_challenge_ready_fn(win, 60.0)
    assert win.results == []  # 消费到就绪标题才返回
    assert sleeps == [1.0] * 4


# --------------------------- _sync_account_cookies -------------------------

def test_sync_account_cookies_writes_profile():
    pytest.importorskip("clr")  # 真实 System.Func 委托 (pythonnet), 无 .NET 运行时环境则跳过
    import clr  # noqa: F401 初始化 .NET 运行时, 使 `from System import ...` 可用

    cm = _FakeCookieManager()
    edge = _FakeEdge(_FakeCoreWebView2(cm))
    _sync_account_cookies_fn(
        edge,
        "authjs.session-token=eyJhbGciOi.eyJ9.sig; authjs.csrf-token=t0|k1; "
        "authjs.callback-url=https%3A%2F%2Fchat.b.ai",
    )
    assert [c.Name for c in cm.added] == [
        "authjs.session-token",
        "authjs.csrf-token",
        "authjs.callback-url",
    ]
    assert all(c.IsSecure for c in cm.added)  # Secure cookie
    assert all(
        domain == "chat.b.ai" and path == "/" for _, _, domain, path in cm.created
    )
    # 无引号/空白污染 (name 已 strip, 值原样落库)
    assert all(c.Name == c.Name.strip() and '"' not in c.Name for c in cm.added)
    assert all('"' not in c.Value for c in cm.added)


# --------------------------- _invoke_on_ui 封送 ----------------------------

def test_invoke_on_ui_passthrough_and_error():
    edge = _FakeEdge()
    # 结果透传: fn 返回值经 BeginInvoke 封送后原样返回
    assert bai_channel._invoke_on_ui(edge, lambda: "ok") == "ok"
    # 异常传播: fn 抛出的异常不被封送层吞掉

    def _boom():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        bai_channel._invoke_on_ui(edge, _boom)


def test_invoke_on_ui_timeout():
    pytest.importorskip("clr")  # 真实 System.Func 委托 (pythonnet), 无 .NET 运行时环境则跳过
    import clr  # noqa: F401 初始化 .NET 运行时, 使 `from System import ...` 可用

    edge = _FakeEdge(wait_ok=False)  # UI 线程未在时限内完成 → WaitOne False
    with pytest.raises(bai_api.BAIError, match="封送超时"):
        bai_channel._invoke_on_ui(edge, lambda: "x")


def test_invoke_on_ui_reraises_error():
    """fn 在 UI 线程侧抛的异常经 error 槽封送回 worker 后原样重抛 (BeginInvoke 不经 EndInvoke)."""
    pytest.importorskip("clr")
    import clr  # noqa: F401

    edge = _FakeEdge()

    def _boom():
        raise ValueError("rerun")

    with pytest.raises(ValueError, match="rerun"):
        bai_channel._invoke_on_ui(edge, _boom)


# --------------------------- activate / transport 注册 ---------------------

def test_activate_registers_transport(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", None)
    bai_channel.activate()
    assert bai_api._transport is not None
    # 注册的适配层把 headers["Cookie"] 传给 fetch_through_window
    seen = {}
    monkeypatch.setattr(
        bai_channel, "fetch_through_window",
        lambda url, cookie, timeout: seen.update(url=url, cookie=cookie) or (200, "{}", {}),
    )
    status, text, _ = bai_api._transport("https://u", {"Cookie": "k=v"}, 5.0)
    assert (status, text) == (200, "{}")
    assert seen == {"url": "https://u", "cookie": "k=v"}


# --------------------------- is_channel_window ------------------------------

def test_is_channel_window(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(bai_channel, "_window", sentinel)
    assert bai_channel.is_channel_window(sentinel) is True      # 通道窗口本身
    assert bai_channel.is_channel_window(object()) is False     # 其他窗口
    assert bai_channel.is_channel_window(None) is False         # self=None 直调兜底
    monkeypatch.setattr(bai_channel, "_window", None)           # 通道未创建
    assert bai_channel.is_channel_window(object()) is False
