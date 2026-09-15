"""workbuddy_channel.py 单测: JS 构建(GET/POST) / 结果槽编排 / 重定向分类 / uid 交叉校验 /
传输层注册 (FakeWindow, 不启动 GUI). 模型来自 tests/test_bai_channel.py."""
from __future__ import annotations

import itertools
import json

import pytest

from app import workbuddy_api, workbuddy_channel
from app.workbuddy_api import WorkBuddyAPIError, WorkBuddyAuthError


# --------------------------- FakeWindow ------------------------------------

class _FakeEvents:
    def wait(self, timeout=None):
        return True


class _FakeEdge:
    def __init__(self, core=None):
        self.webview = self
        self.CoreWebView2 = core if core is not None else object()

    def BeginInvoke(self, delegate):  # 未在纯 FakeWindow 路径使用 (直接 patch _ready_window)
        raise NotImplementedError


class FakeWindow:
    def __init__(self, script_results):
        # script_results: evaluate_js 依次返回的值 (None 表示槽未就绪)
        self.results = list(script_results)
        self.calls = []
        self.events = _FakeEvents()
        self.native = _FakeEdge()

    def evaluate_js(self, js):
        self.calls.append(js)
        if "delete window.__gousage" in js:
            return None  # 清理调用不消费排队结果 (支持一次请求内多次 fetch, 如 uid 探测)
        if self.results:
            return self.results.pop(0)
        return None


@pytest.fixture(autouse=True)
def _reset_channel_state(monkeypatch):
    """通道模块状态隔离: 重置窗口 / slot 序列 / 期望 uid / uid 缓存, 使各用例 slot 恒为 r1."""
    monkeypatch.setattr(workbuddy_channel, "_window", None)
    monkeypatch.setattr(workbuddy_channel, "_slot_seq", itertools.count(1))
    monkeypatch.setattr(workbuddy_channel, "_expected_uid", None)
    monkeypatch.setattr(workbuddy_channel, "_uid_cache", (0.0, None))
    monkeypatch.setattr(workbuddy_channel.time, "sleep", lambda s: None)
    yield


# --------------------------- build_fetch_js --------------------------------

def test_build_fetch_js_post_includes_body_and_content_type():
    body = '{"pageSize":50}'
    js = workbuddy_channel.build_fetch_js("/billing/x", "r7", "POST", body, 30.0)
    assert 'var slot = "r7"' in js
    assert 'fetch("/billing/x"' in js
    assert 'method: "POST"' in js
    assert 'credentials: "include"' in js
    assert '"Content-Type": "application/json"' in js
    assert json.dumps(body) in js  # body 安全嵌入为 JS 字符串字面量
    assert "30000" in js  # timeout_sec -> 毫秒
    assert "new URL(r.url).pathname" in js


def test_build_fetch_js_get_has_no_body():
    js = workbuddy_channel.build_fetch_js("/console/accounts", "r1", "GET", "", 30.0)
    assert 'method: "GET"' in js
    # GET 的 fetch options 里不含请求 body (响应对象里的 "body: t.substr" 是回传字段, 不算)
    fetch_opts = js.split("fetch(")[1].split(").then")[0]
    assert "body:" not in fetch_opts
    assert 'credentials: "include"' in js


# --------------------------- fetch_through_window --------------------------

def test_fetch_success_get(monkeypatch):
    win = FakeWindow(["r1", None, {"status": 200, "path": "/billing/x", "ct": "application/json", "body": '{"ok":1}'}])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    status, text, headers = workbuddy_channel.fetch_through_window(
        "https://www.workbuddy.cn/billing/x", {"Cookie": "ignored=1"}, None, 10.0
    )
    assert status == 200
    assert text == '{"ok":1}'
    assert headers == {"Content-Type": "application/json"}
    assert win.calls[0].startswith("(function(){")
    assert 'method: "GET"' in win.calls[0]  # body None → GET
    assert any("delete window.__gousage" in c for c in win.calls)  # 槽已清理


def test_fetch_success_post_uses_body(monkeypatch):
    win = FakeWindow(["r1", {"status": 200, "path": "/billing/x", "ct": "application/json", "body": "{}"}])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    status, text, _ = workbuddy_channel.fetch_through_window(
        "https://www.workbuddy.cn/billing/x", {}, b'{"pageSize":50}', 10.0
    )
    assert status == 200
    assert 'method: "POST"' in win.calls[0]
    assert json.dumps('{"pageSize":50}') in win.calls[0]


def test_fetch_strips_base_url_to_same_origin_path(monkeypatch):
    win = FakeWindow(["r1", {"status": 200, "path": "/billing/x", "ct": "application/json", "body": "{}"}])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    workbuddy_channel.fetch_through_window(
        "https://www.workbuddy.cn/billing/meter/get?a=1", {}, None, 10.0
    )
    assert 'fetch("/billing/meter/get?a=1"' in win.calls[0]  # 去掉 host, 保留 query


def test_fetch_js_abort_maps_to_timeout_error(monkeypatch):
    win = FakeWindow(["r1", {"status": 0, "error": "AbortError: aborted"}])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    with pytest.raises(TimeoutError):
        workbuddy_channel.fetch_through_window("https://www.workbuddy.cn/x", {}, None, 10.0)


def test_fetch_error_maps_to_oserror(monkeypatch):
    win = FakeWindow(["r1", {"status": 0, "error": "TypeError: failed to fetch"}])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    with pytest.raises(OSError):
        workbuddy_channel.fetch_through_window("https://www.workbuddy.cn/x", {}, None, 10.0)


def test_fetch_poll_timeout_raises(monkeypatch):
    win = FakeWindow(["r1"] + [None] * 500)
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    monkeypatch.setattr(workbuddy_channel, "POLL_TIMEOUT", 0.2)
    with pytest.raises(TimeoutError):
        workbuddy_channel.fetch_through_window("https://www.workbuddy.cn/x", {}, None, 10.0)


def test_fetch_start_js_failure_raises(monkeypatch):
    win = FakeWindow([None])  # 启动 JS 未返回 slot → 执行失败
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    with pytest.raises(WorkBuddyAPIError, match="通道"):
        workbuddy_channel.fetch_through_window("https://www.workbuddy.cn/x", {}, None, 10.0)


def test_fetch_bad_return_raises(monkeypatch):
    win = FakeWindow(["r1", "not-a-dict"])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    with pytest.raises(WorkBuddyAPIError):
        workbuddy_channel.fetch_through_window("https://www.workbuddy.cn/x", {}, None, 10.0)


# --------------------------- redirect classification ----------------------

def test_fetch_redirect_to_auth_returns_302_location(monkeypatch):
    win = FakeWindow(["r1", {"status": 200, "path": "/auth/realms/copilot/protocol/openid-connect/auth", "ct": "text/html", "body": "<html/>"}])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    status, text, headers = workbuddy_channel.fetch_through_window(
        "https://www.workbuddy.cn/billing/x", {}, None, 10.0
    )
    assert status == 302
    assert text == ""
    assert headers == {"Location": "/auth/realms/copilot/protocol/openid-connect/auth"}


def test_redirect_end_to_end_raises_auth_error(monkeypatch):
    """将 302,Location 形态喂给真实 WorkBuddyAPI → WorkBuddyAuthError (强端到端证明)."""
    win = FakeWindow(["r1", {"status": 200, "path": "/auth/realms/copilot/x", "ct": "text/html", "body": "<html/>"}])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)

    def _adaptor(url, headers, body, timeout):
        return workbuddy_channel.fetch_through_window(url, headers, body, timeout)

    api = workbuddy_api.WorkBuddyAPI("[]", transport=_adaptor)
    with pytest.raises(WorkBuddyAuthError):
        api.fetch_resource_summary()


# --------------------------- is_channel_window ------------------------------

def test_is_channel_window(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(workbuddy_channel, "_window", sentinel)
    assert workbuddy_channel.is_channel_window(sentinel) is True
    assert workbuddy_channel.is_channel_window(object()) is False
    assert workbuddy_channel.is_channel_window(None) is False
    monkeypatch.setattr(workbuddy_channel, "_window", None)
    assert workbuddy_channel.is_channel_window(object()) is False


# --------------------------- activate / transport 注册 ---------------------

def test_activate_registers_transport(monkeypatch):
    monkeypatch.setattr(workbuddy_api, "_transport", None)
    try:
        workbuddy_channel.activate()
        assert workbuddy_api._transport is not None
        seen = {}
        monkeypatch.setattr(
            workbuddy_channel, "fetch_through_window",
            lambda url, headers, body, timeout: seen.update(url=url, body=body) or (200, "{}", {}),
        )
        status, text, _ = workbuddy_api._transport("https://u", {"Cookie": "k=v"}, b"x", 5.0)
        assert (status, text) == (200, "{}")
        assert seen == {"url": "https://u", "body": b"x"}
    finally:
        workbuddy_api._transport = None  # 避免泄漏到 test_workbuddy_api


# --------------------------- uid 交叉校验 ----------------------------------

def _accounts_body(uid, last_login=True):
    return json.dumps({"data": {"accounts": [{"uid": uid, "lastLogin": last_login}]}})


def test_uid_guard_mismatch_returns_401(monkeypatch):
    # 第一次 fetch 为 /console/accounts 探测 (uid u2), 期望 u1 → 401, 不发第二次请求
    win = FakeWindow([
        "r1", {"status": 200, "path": "/console/accounts", "ct": "application/json", "body": _accounts_body("u2")},
    ])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    workbuddy_channel.set_expected_uid("u1")
    try:
        status, text, headers = workbuddy_channel.fetch_through_window(
            "https://www.workbuddy.cn/billing/x", {}, None, 10.0
        )
        assert status == 401
        assert text == ""
    finally:
        workbuddy_channel.set_expected_uid(None)


def test_uid_guard_match_proceeds(monkeypatch):
    # 探测 uid u1 == 期望 → 继续发实际请求 (第二组结果)
    win = FakeWindow([
        "r1", {"status": 200, "path": "/console/accounts", "ct": "application/json", "body": _accounts_body("u1")},
        "r2", {"status": 200, "path": "/billing/x", "ct": "application/json", "body": '{"ok":1}'},
    ])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    workbuddy_channel.set_expected_uid("u1")
    try:
        status, text, _ = workbuddy_channel.fetch_through_window(
            "https://www.workbuddy.cn/billing/x", {}, None, 10.0
        )
        assert status == 200
        assert text == '{"ok":1}'
    finally:
        workbuddy_channel.set_expected_uid(None)


def test_uid_guard_disabled_when_no_expected(monkeypatch):
    # 未设期望 uid → 不探测, 直接发请求 (单账号默认无副作用)
    win = FakeWindow(["r1", {"status": 200, "path": "/billing/x", "ct": "application/json", "body": "{}"}])
    monkeypatch.setattr(workbuddy_channel, "_ready_window", lambda timeout: win)
    status, _, _ = workbuddy_channel.fetch_through_window(
        "https://www.workbuddy.cn/billing/x", {}, None, 10.0
    )
    assert status == 200
    assert 'fetch("/console/accounts"' not in win.calls[0]  # 无探测调用
