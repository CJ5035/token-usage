"""WorkBuddy 浏览器通道: WorkBuddy 后台请求经隐藏 WebView2 窗口以浏览器自身已认证
会话发出 (同源 fetch + credentials:'include'), 绕过 urllib cookie 快照回放被 APISIX
网关拒绝 (302→Keycloak / 401) 的问题 (20260915 诊断 §11 / §4.3).

机制 (对照 bai_channel.py, 但有关键差异):
- 隐藏窗口加载 https://www.workbuddy.cn/profile/plans-usage (同源页面, fetch 无 CORS)
- 无 Cloudflare 人机质询: 不轮询 document.title, _ready_window 仅等 loaded + CoreWebView2
- 不写 cookie 快照: 通道依赖窗口自身的登录会话, credentials:'include' 自动携带,
  适配层忽略 headers["Cookie"]
- 支持 GET 与 POST(JSON body); fetch 用 redirect:'follow', 读 new URL(r.url).pathname:
  跟随后落到 /auth/realms/ 视为会话被网关拒绝, 以 (302, Location) 形态上抛交由
  workbuddy_api._redirect_error 分类为 WorkBuddyAuthError
- evaluate_js 起搏 fetch, 结果写 window.__gousage[slot], Python 轮询读取
- 请求以 _req_lock 串行化 (单窗口单会话)
- uid 交叉校验 (§4.2): 单通道窗口只持有一个已认证会话, 多账号时以 set_expected_uid
  设置期望 uid, 请求前探测 /console/accounts 核对, 不匹配则以 (401) 形态上抛
"""
from __future__ import annotations

import itertools
import json
import threading
import time
from typing import Any, Optional

from . import workbuddy_api
from .workbuddy_api import WorkBuddyAPIError

CHANNEL_URL = "https://www.workbuddy.cn/profile/plans-usage"
JS_FETCH_TIMEOUT = 30.0  # JS 内 AbortController 超时 (秒)
POLL_INTERVAL = 0.15  # 结果槽轮询间隔 (秒)
POLL_TIMEOUT = 45.0  # 结果槽轮询总超时 (秒)
INVOKE_TIMEOUT = 10.0  # UI 线程封送上限 (秒)
_READY_TIMEOUT = 30.0  # 等待通道窗口 loaded 超时 (秒)
_MAX_BODY_BYTES = 4 << 20  # 与 workbuddy_api.MAX_BODY_BYTES 口径一致
_UID_TTL = 5.0  # uid 探测缓存有效期 (秒), 避免同步时逐页探测

_win_lock = threading.Lock()
_req_lock = threading.Lock()
_window: Any = None  # pywebview Window (延迟创建, 测试注入 FakeWindow)
_slot_seq = itertools.count(1)

_uid_lock = threading.Lock()
_expected_uid: Optional[str] = None
_uid_cache: tuple[float, Optional[str]] = (0.0, None)  # (探测时刻, 窗口会话 uid)


def set_expected_uid(uid: Optional[str]) -> None:
    """设置通道窗口应服务的账号 uid (多账号防串号). None 关闭校验 (单账号默认)."""
    global _expected_uid, _uid_cache
    with _uid_lock:
        _expected_uid = uid
        _uid_cache = (0.0, None)  # 期望值变更, 作废旧探测缓存


def ensure_window() -> None:
    """创建隐藏通道窗口 (幂等). webview.start() 前后调用均安全 (start 前排队)."""
    global _window
    import webview

    with _win_lock:
        if _window is not None and _window in webview.windows:
            return
        _window = webview.create_window(
            "GoGauge WorkBuddy Channel", CHANNEL_URL, hidden=True
        )


def is_channel_window(win: Any) -> bool:
    """判断 pywebview 窗口是否为 WorkBuddy 隐藏通道窗口 (弹窗拦截判定用).

    身份比较随 ensure_window 重建自动一致; win 为 None 时恒为 False.
    """
    return win is not None and win is _window


def _invoke_on_ui(edge: Any, fn: Any) -> Any:
    """在 UI 线程执行 fn 并返回结果 (WebView2 仅允许 UI 线程访问).

    BeginInvoke + AsyncWaitHandle 有界等待: Control.Invoke 的无限阻塞会连同
    GIL 一起冻死解释器, 故不得在 worker 上无限等 UI 线程 (照抄 bai_channel).
    """
    from System import Func, Object  # noqa: F401 泛型委托参数须用 .NET 类型

    result: list[Any] = []
    error: list[BaseException] = []

    def _run() -> None:
        try:
            result.append(fn())
        except Exception as exc:  # noqa: BLE001 封送回 worker 后重抛, 不在 UI 线程炸
            error.append(exc)

    ar = edge.webview.BeginInvoke(Func[Object](_run))
    if not ar.AsyncWaitHandle.WaitOne(int(INVOKE_TIMEOUT * 1000)):
        raise WorkBuddyAPIError("UI 线程封送超时")
    if error:
        raise error[0]
    return result[0] if result else None


def _ready_window(timeout: float) -> Any:
    """返回就绪的通道窗口: 已加载 + CoreWebView2 可用 (无 Cloudflare 质询等待)."""
    global _window
    if _window is None:
        ensure_window()
    win = _window
    if win is None:
        raise WorkBuddyAPIError("WorkBuddy 通道窗口不可用")
    if not win.events.loaded.wait(timeout):
        raise WorkBuddyAPIError("WorkBuddy 通道页面加载超时")
    edge = getattr(win, "native", None)
    core = _invoke_on_ui(edge, lambda: getattr(edge.webview, "CoreWebView2", None))
    if core is None:
        raise WorkBuddyAPIError("WorkBuddy 通道未就绪 (CoreWebView2 未初始化)")
    return win


def _to_same_origin_path(url: str) -> str:
    """把绝对 URL 转为同源相对路径 (含 query). workbuddy_api 恒以 BASE_URL + path 调用.

    去掉 https://www.workbuddy.cn 前缀; 已是相对路径则原样返回. 保证 fetch 同源.
    """
    prefix = workbuddy_api.BASE_URL  # "https://www.workbuddy.cn"
    if url.startswith(prefix):
        path = url[len(prefix):]
    else:
        path = url
    if not path.startswith("/"):
        path = "/" + path
    return path


def build_fetch_js(url: str, slot: str, method: str, body: str, timeout_sec: float) -> str:
    """构造起搏 fetch 的 JS: 结果写 window.__gousage[slot], 立即返回 slot.

    url 为同源相对路径 (以 / 开头); credentials:'include' 自动携带窗口会话 cookie.
    redirect 默认 follow, 读 new URL(r.url).pathname 供 Python 侧分类 302→登录页.
    method=="POST" 时带 JSON body 与 Content-Type; GET 时不带 body.
    (照抄 auth.py:_build_wb_probe_js 的证实同源 fetch 模式, 增加 POST 分支.)
    """
    timeout_ms = int(timeout_sec * 1000)
    is_post = method == "POST"
    body_json = json.dumps(body)  # 把 body 字符串安全嵌入为 JS 字符串字面量
    opts = (
        f'method: "{method}", '
        'credentials: "include", '
    )
    if is_post:
        opts += (
            'headers: { "Content-Type": "application/json", '
            '"Accept": "application/json, text/plain, */*" }, '
            f"body: {body_json}, "
        )
    else:
        opts += 'headers: { "Accept": "application/json, text/plain, */*" }, '
    opts += "signal: ctrl.signal"
    return (
        "(function(){"
        f'var slot = "{slot}";'
        "window.__gousage = window.__gousage || {};"
        "window.__gousage[slot] = null;"
        "var ctrl = new AbortController();"
        f"setTimeout(function(){{ ctrl.abort(); }}, {timeout_ms});"
        # url 仅来自 workbuddy_api 模块常量端点路径 (非用户输入) 且已剥离为同源 path,
        # 故直接内插安全; 若未来传入外部可控 URL, 须改用 json.dumps 包裹 (同 body).
        f'fetch("{url}", {{{opts}}}).then(function(r){{'
        'var path = "";'
        "try { path = new URL(r.url).pathname; } catch (e) {}"
        'var ct = r.headers.get("content-type") || "";'
        "return r.text().then(function(t){"
        f"return {{ status: r.status, path: path, ct: ct, body: t.substr(0, {_MAX_BODY_BYTES}) }};"
        "});"
        "}).catch(function(e){"
        "return { status: 0, error: String(e) };"
        "}).then(function(v){"
        "window.__gousage[slot] = v;"
        "});"
        "return slot;"
        "})()"
    )


def _run_fetch(win: Any, path: str, method: str, body: str) -> dict[str, Any]:
    """锁内起搏 fetch 并轮询结果槽, 返回原始结果 dict; 超时抛 TimeoutError.

    调用方须持有 _req_lock (单窗口串行化).
    """
    slot = f"r{next(_slot_seq)}"
    res: Optional[Any] = None
    try:
        started = win.evaluate_js(build_fetch_js(path, slot, method, body, JS_FETCH_TIMEOUT))
        if started != slot:
            raise WorkBuddyAPIError("WorkBuddy 通道执行失败 (JS 未启动)")
        deadline = time.monotonic() + POLL_TIMEOUT
        while time.monotonic() < deadline:
            res = win.evaluate_js(f'window.__gousage["{slot}"]')
            if res is not None:
                break
            time.sleep(POLL_INTERVAL)
        else:
            raise TimeoutError("WorkBuddy 通道响应超时")
    finally:
        try:
            win.evaluate_js(f'delete window.__gousage["{slot}"]')
        except Exception:  # noqa: BLE001 清理失败不影响主流程
            pass
    if not isinstance(res, dict):
        raise WorkBuddyAPIError("WorkBuddy 通道返回异常")
    return res


def _probe_window_uid(win: Any) -> Optional[str]:
    """探测通道窗口当前会话的账号 uid (GET /console/accounts), 带 _UID_TTL 缓存.

    解析规则与 auth.py 一致: data.accounts[] 取首个含 lastLogin 者, 否则取第一个,
    读其 uid. 探测不成功 (网络/重定向/非 JSON/空账号) 返回 None.
    """
    global _uid_cache
    now = time.monotonic()
    with _uid_lock:
        ts, cached = _uid_cache
        if now - ts < _UID_TTL:
            return cached
    res = _run_fetch(win, "/console/accounts", "GET", "")
    uid = _parse_probe_uid(res)
    with _uid_lock:
        _uid_cache = (time.monotonic(), uid)
    return uid


def _parse_probe_uid(res: dict[str, Any]) -> Optional[str]:
    """从 /console/accounts 探测结果 dict 解析会话 uid (解析规则同 auth.py)."""
    if res.get("status") == 0:
        return None
    path = str(res.get("path") or "")
    if path.startswith("/auth/realms/"):
        return None
    try:
        body = json.loads(res.get("body") or "")
    except (TypeError, ValueError):
        return None
    data = body.get("data") if isinstance(body, dict) else None
    accounts = data.get("accounts") if isinstance(data, dict) else None
    if not isinstance(accounts, list) or not accounts:
        return None
    picked = next((a for a in accounts if isinstance(a, dict) and a.get("lastLogin")), accounts[0])
    uid = picked.get("uid") if isinstance(picked, dict) else None
    return uid if isinstance(uid, str) else None


def fetch_through_window(
    url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> tuple[int, str, dict[str, str]]:
    """经隐藏窗口发同源请求 (匹配 workbuddy_api.Transport 4 参签名).

    返回 (status, body, headers); 网络失败抛 TimeoutError/OSError (供 _request 重试).
    忽略 headers["Cookie"]: 依赖窗口自身会话. body 非 None → POST, 否则 GET.
    落到 /auth/realms/ 的重定向以 (302, Location) 形态回传交 workbuddy_api 分类.
    """
    win = _ready_window(_READY_TIMEOUT)
    method = "POST" if body is not None else "GET"
    body_str = ""
    if body is not None:
        body_str = body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else str(body)
    path = _to_same_origin_path(url)

    with _req_lock:
        # uid 交叉校验: 期望 uid 已设置时, 核对窗口会话 uid 是否一致 (§4.2 防串号)
        expected = _expected_uid
        if expected is not None:
            win_uid = _probe_window_uid(win)
            if win_uid is not None and win_uid != expected:
                return 401, "", {}  # 交由 workbuddy_api → WorkBuddyAuthError, 触发该账号重登
        res = _run_fetch(win, path, method, body_str)

    if res.get("status") == 0:
        err = str(res.get("error") or "fetch failed")
        if "abort" in err.lower():
            raise TimeoutError(err)
        raise OSError(err)
    res_path = str(res.get("path") or "")
    if res_path.startswith("/auth/realms/"):
        # 跟随 302 后落到 Keycloak: 以 (302, Location) 形态上抛, workbuddy_api._redirect_error 分类
        return 302, "", {"Location": res_path}
    status = int(res.get("status") or 0)
    return status, str(res.get("body") or ""), {"Content-Type": str(res.get("ct") or "")}


def activate() -> None:
    """把浏览器通道注册为 workbuddy_api 传输层 (幂等, main() 启动时调用一次)."""

    def _adaptor(
        url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, str, dict[str, str]]:
        return fetch_through_window(url, headers, body, timeout)

    workbuddy_api.set_transport(_adaptor)
