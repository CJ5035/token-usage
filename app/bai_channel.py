"""BAI 浏览器通道: BAI 请求经 WebView2 真实引擎发出, 绕过 Cloudflare 人机质询.

背景 (doc/20260902-bug-diagnosis-bai-quota-403.md): chat.b.ai 的 Cloudflare 对
Python urllib 的 TLS/客户端指纹返回 403 质询页 (Cf-Mitigated: challenge),
真实 Cookie 也无法通过; 浏览器引擎(与登录窗同进程同 cookie 存储)可正常通过.

机制:
- 隐藏窗口加载 https://chat.b.ai/usage (同源页面, fetch 无 CORS 问题)
- Cloudflare 质询在隐藏窗自动通过 (实测 25-38s), 轮询 document.title 等待:
  「请稍候…」/含 moment 为质询页, None 为跳转中, 出现正式标题即就绪
- 账号 cookie 经 CookieManager 写入 profile CookieStore; fetch 用
  credentials:'include' 由浏览器自动携带 profile 全套 cookie (含 cf_clearance).
  WebResourceRequested 原生头注入无法覆盖网络层自动计算的 Cookie (实测 401), 弃用
- 每次请求前重写账号 cookie, 同名覆盖, 实现多账号隔离
- evaluate_js 起搏 fetch, 结果写入 window.__gousage[slot], Python 轮询读取
  (不依赖 ExecuteScriptAsync 对 Promise 的返回行为)
- 请求以 _req_lock 串行化: 配额刷新与用量同步线程并发时防 Cookie 串号
"""
from __future__ import annotations

import itertools
import threading
import time
from typing import Any, Optional

from . import bai_api
from .bai_api import BAIError

CHANNEL_URL = "https://chat.b.ai/usage"
JS_FETCH_TIMEOUT = 30.0  # JS 内 AbortController 超时 (秒)
POLL_INTERVAL = 0.15  # 结果槽轮询间隔 (秒)
POLL_TIMEOUT = 45.0  # 结果槽轮询总超时 (秒)
CHALLENGE_WAIT = 60.0  # 等待 Cloudflare 质询通过的上限 (秒, 实测 25-38s)
INVOKE_TIMEOUT = 10.0  # UI 线程封送上限 (秒)
_READY_TIMEOUT = 30.0  # 等待通道窗口 loaded 超时 (秒)
_MAX_BODY_BYTES = 4 << 20  # 与 bai_api.MAX_BODY_BYTES 口径一致

_win_lock = threading.Lock()
_req_lock = threading.Lock()
_window: Any = None  # pywebview Window (延迟创建, 测试注入 FakeWindow)
_slot_seq = itertools.count(1)


def ensure_window() -> None:
    """创建隐藏通道窗口 (幂等). webview.start() 前后调用均安全 (start 前排队)."""
    global _window
    import webview

    with _win_lock:
        if _window is not None and _window in webview.windows:
            return
        _window = webview.create_window("GoGauge BAI Channel", CHANNEL_URL, hidden=True)


def is_channel_window(win: Any) -> bool:
    """判断 pywebview 窗口是否为 BAI 隐藏通道窗口 (弹窗拦截判定用).

    身份比较随 ensure_window 重建自动一致; win 为 None 时恒为 False
    (测试直调 patched handler 时 self.pywebview_window 取不到).
    """
    return win is not None and win is _window


def _invoke_on_ui(edge: Any, fn: Any) -> Any:
    """在 UI 线程执行 fn 并返回结果 (WebView2 仅允许 UI 线程访问).

    BeginInvoke + AsyncWaitHandle 有界等待: Control.Invoke 的无限阻塞会连同
    GIL 一起冻死解释器 (round 3 实测), 故不得在 worker 上无限等 UI 线程.
    """
    from System import Func, Object  # noqa: F401 泛型委托参数须用 .NET 类型, 内建 object 在 pythonnet 3.x 不被接受

    result: list[Any] = []
    error: list[BaseException] = []

    def _run() -> None:
        try:
            result.append(fn())
        except Exception as exc:  # noqa: BLE001 封送回 worker 后重抛, 不在 UI 线程炸
            error.append(exc)

    ar = edge.webview.BeginInvoke(Func[Object](_run))
    if not ar.AsyncWaitHandle.WaitOne(int(INVOKE_TIMEOUT * 1000)):
        raise BAIError("UI 线程封送超时")
    if error:
        raise error[0]
    return result[0] if result else None


def _wait_challenge_ready(win: Any, timeout: float) -> None:
    """轮询 document.title 等待 Cloudflare 质询通过 (隐藏窗自动放行, 实测 25-38s).

    title 为 None 表示跳转中; 含「请稍候」或 "moment" (不分大小写) 为质询页.
    超时不抛错直接返回: 质询未过时请求会 403, 由上层人机验证拦截文案兜底.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        title = win.evaluate_js("document.title")
        if title:
            text = str(title)
            if "请稍候" not in text and "moment" not in text.lower():
                return
        time.sleep(1.0)


def _sync_account_cookies(edge: Any, cookie: str) -> None:
    """把账号 authjs cookie 写入 WebView2 profile CookieStore (UI 线程).

    浏览器只在 credentials:'include' 时自动携带 profile cookie (含
    Cloudflare 的 cf_clearance), 头注入无法覆盖它 (实测), 故会话 cookie
    必须落入 CookieStore. 每次请求前同步, 覆盖同名旧值, 实现多账号隔离.
    """
    def _write() -> str:
        cm = edge.webview.CoreWebView2.CookieManager
        count = 0
        for part in (cookie or "").split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, _, value = part.partition("=")
            c = cm.CreateCookie(name.strip(), value, "chat.b.ai", "/")
            c.IsSecure = True
            cm.AddOrUpdateCookie(c)
            count += 1
        return f"{count}"

    _invoke_on_ui(edge, _write)


def _ready_window(timeout: float) -> Any:
    """返回就绪的通道窗口: 已加载 + CoreWebView2 可用."""
    global _window
    if _window is None:
        ensure_window()
    win = _window
    if win is None:
        raise BAIError("浏览器通道窗口不可用")
    if not win.events.loaded.wait(timeout):
        raise BAIError("浏览器通道页面加载超时")
    edge = getattr(win, "native", None)
    core = _invoke_on_ui(edge, lambda: getattr(edge.webview, "CoreWebView2", None))
    if core is None:
        raise BAIError("浏览器通道未就绪 (CoreWebView2 未初始化)")
    return win


def build_fetch_js(url: str, slot: str, timeout_sec: float) -> str:
    """构造起搏 fetch 的 JS: 结果写 window.__gousage[slot], 立即返回 slot.

    credentials:'include' 使浏览器自动携带 profile 全套 cookie (含 Cloudflare
    的 cf_clearance), 账号会话 cookie 已由 _sync_account_cookies 落库.
    """
    timeout_ms = int(timeout_sec * 1000)
    return (
        "(function(){"
        f'var slot = "{slot}";'
        'window.__gousage = window.__gousage || {};'
        "window.__gousage[slot] = null;"
        "var ctrl = new AbortController();"
        f"setTimeout(function(){{ ctrl.abort(); }}, {timeout_ms});"
        f'fetch("{url}", {{'
        'method: "GET", '
        'credentials: "include", '
        'headers: { "Accept": "application/json, text/plain, */*" }, '
        "signal: ctrl.signal"
        "}).then(function(r){"
        'var cf = r.headers.get("cf-mitigated") || "";'
        "return r.text().then(function(t){"
        "return { status: r.status, cf: cf, body: t.substr(0, "
        f"{_MAX_BODY_BYTES}" ") };"
        "});"
        "}).catch(function(e){"
        "return { status: 0, error: String(e) };"
        "}).then(function(v){"
        "window.__gousage[slot] = v;"
        "});"
        "return slot;"
        "})()"
    )


def fetch_through_window(
    url: str, cookie: str, timeout: float
) -> tuple[int, str, dict[str, str]]:
    """经隐藏窗口发同源 GET. 返回 (status, body, headers); 网络失败抛 OSError/TimeoutError.

    传输层契约与 bai_api._default_transport 一致 (见 bai_api.set_transport).
    timeout 参数仅为满足契约签名; 通道自身超时由 JS abort (JS_FETCH_TIMEOUT)
    与结果槽轮询 (POLL_TIMEOUT) 控制.
    """
    win = _ready_window(_READY_TIMEOUT)
    _wait_challenge_ready(win, CHALLENGE_WAIT)
    edge = getattr(win, "native", None)
    with _req_lock:
        # 锁内同步账号 cookie: CookieStore 共享, 锁外同步会在等锁期间被他账号覆盖而串号
        _sync_account_cookies(edge, cookie)
        slot = f"r{next(_slot_seq)}"
        res: Optional[dict[str, Any]] = None
        try:
            started = win.evaluate_js(build_fetch_js(url, slot, JS_FETCH_TIMEOUT))
            if started != slot:
                raise BAIError("浏览器通道执行失败 (JS 未启动)")
            deadline = time.monotonic() + POLL_TIMEOUT
            while time.monotonic() < deadline:
                res = win.evaluate_js(f'window.__gousage["{slot}"]')
                if res is not None:
                    break
                time.sleep(POLL_INTERVAL)
            else:
                raise TimeoutError("浏览器通道响应超时")
        finally:
            try:
                win.evaluate_js(f'delete window.__gousage["{slot}"]')
            except Exception:  # noqa: BLE001 清理失败不影响主流程
                pass

    if not isinstance(res, dict):
        raise BAIError("浏览器通道返回异常")
    if res.get("status") == 0:
        err = str(res.get("error") or "fetch failed")
        if "abort" in err.lower():
            raise TimeoutError(err)
        raise OSError(err)
    status = int(res.get("status") or 0)
    headers = {"Cf-Mitigated": str(res.get("cf"))} if res.get("cf") else {}
    return status, str(res.get("body") or ""), headers


def activate() -> None:
    """把浏览器通道注册为 bai_api 传输层 (幂等, main() 启动时调用一次)."""

    def _adaptor(
        url: str, headers: dict[str, str], timeout: float
    ) -> tuple[int, str, dict[str, str]]:
        return fetch_through_window(url, headers.get("Cookie", ""), timeout)

    bai_api.set_transport(_adaptor)
