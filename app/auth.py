"""WebView 登录: 加载 opencode.ai / chat.b.ai 授权页, 捕获凭证(cookie/工作区 ID).

原理: pywebview (WebView2) 的 window.get_cookies() 可直接读取 HttpOnly cookie,
登录完成后窗口位于目标域, 从中提取凭证:

- opencode: 窗口位于 opencode.ai 域, 提取 auth cookie; workspace_hint 为 URL 正则抓的 wrk_ id
- bai: 窗口位于 chat.b.ai 域, 提取 __Secure-authjs.session-token (必须非空), 序列化
  3 个 authjs cookie 为 cookie jar JSON (Task 1 build_cookie_header 的输入契约);
  workspace_hint = getUserState 的 userId (作 BAI 去重键, 失败退化为空串)
- commandcode: 窗口位于 commandcode.ai 域, better-auth 会话 cookie 名未最终确认
  (稳健规则判定), 收集全部非空 cookie 为 jar; workspace_hint = subscriptions 的 userId
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from http.cookies import SimpleCookie as SimpleCookieCls
from typing import Callable, Optional
from urllib import request as _urllib_request
from urllib.parse import urlencode

import webview

LOGIN_BASE = "https://auth.opencode.ai/authorize"
LOGIN_CLIENT_ID = "app"
LOGIN_REDIRECT_URI = "https://opencode.ai/auth/callback"
AUTH_COOKIE_NAME = "auth"
COOKIE_POLL_SEC = 1.0
_WORKSPACE_URL_RE = re.compile(r"/workspace/(wrk_[A-Za-z0-9]+)")
_LOG_FILE = os.path.join(tempfile.gettempdir(), "gousage_login.log")

# BAI 登录相关常量 (精确值, 见实施文档 §3.4/G2)
BAI_LOGIN_URL = "https://chat.b.ai/login"
BAI_DOMAIN = "https://chat.b.ai"
BAI_ACCOUNT_TYPE = "bai"
BAI_SESSION_COOKIE = "__Secure-authjs.session-token"
BAI_CSRF_COOKIE = "authjs.csrf-token"
BAI_CALLBACK_COOKIE = "authjs.callback-url"

# BAI tRPC: user.getUserState → userId (认证仅需 cookie)
BAI_TRPC_BASE = "https://chat.b.ai/trpc/lambda"

# CommandCode 登录相关常量 (better-auth 会话 cookie 名未最终确认, 成功判定用稳健规则)
CC_LOGIN_URL = "https://commandcode.ai/signin"
CC_DOMAIN = "https://commandcode.ai"
CC_ACCOUNT_TYPE = "commandcode"

# on_success 共用的工作区提示随实例而定, _extract_bai_session/_build_bai_cookie_jar 不依赖全局
_ACCOUNT_TYPES = ("opencode", "bai", "commandcode")


def _log(msg: str) -> None:
    """同时输出到 stdout 与日志文件 (便于诊断)."""
    print(msg, flush=True)
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


def build_login_url(account_type: str = "opencode") -> str:
    """构造授权登录 URL. account_type="bai"/"commandcode" 返回对应登录页."""
    if account_type == BAI_ACCOUNT_TYPE:
        return BAI_LOGIN_URL
    if account_type == CC_ACCOUNT_TYPE:
        return CC_LOGIN_URL
    params = {
        "client_id": LOGIN_CLIENT_ID,
        "redirect_uri": LOGIN_REDIRECT_URI,
        "response_type": "code",
        "state": uuid.uuid4().hex,
    }
    return f"{LOGIN_BASE}?{urlencode(params)}"


def _cookie_value(cookie, name: str) -> str:
    """从单个 cookie 对象取指定 cookie 名对应的 value (空串表示无).

    兼容两种形态: SimpleCookie 对象 (dict 子类) 与 {"name":..., "value":...} dict.
    """
    if isinstance(cookie, SimpleCookieCls):
        try:
            return cookie[name].value
        except (KeyError, Exception):  # noqa: BLE001
            return ""
    if isinstance(cookie, dict):
        if cookie.get("name") != name:
            return ""
        value = cookie.get("value", "")
        return value if isinstance(value, str) else ""
    return ""


def _cookie_names(cookie) -> list[str]:
    """列出单个 cookie 对象包含的 cookie 名 (兼容 SimpleCookie 与 dict)."""
    if isinstance(cookie, SimpleCookieCls):
        return list(cookie.keys())
    if isinstance(cookie, dict):
        name = cookie.get("name")
        return [name] if isinstance(name, str) else []
    return []


def _extract_bai_session(cookies) -> Optional[str]:
    """从 get_cookies() 返回的 cookie 列表提取 BAI session-token 值.

    三态: session-token 存在且非空 → 返回其值; 仅 csrf/callback-url → None
    (登录前即存在); session-token 为空值 → None.
    """
    for cookie in cookies or []:
        for name in _cookie_names(cookie):
            if name == BAI_SESSION_COOKIE:
                value = _cookie_value(cookie, name)
                if value:
                    return value
    return None


def build_bai_cookie_jar(cookies) -> str:
    """序列化登录窗 cookie 为 cookie jar JSON (Task 1 build_cookie_header 的输入契约).

    从 get_cookies() 返回的 cookie 列表中收集 BAI 的 authjs cookie
    (session-token/csrf/callback-url, 可能带 __Host-/__Secure- 前缀) 为
    [{"name","value"}, ...] 数组的 JSON 串. session-token 缺失或无 value 时返回 ""
    (未成功登录); 无 value 的 csrf/callback 一并忽略.
    """
    jar: list[dict[str, str]] = []
    session_found = False
    for cookie in cookies or []:
        for name in _cookie_names(cookie):
            matched = (
                name == BAI_SESSION_COOKIE
                or name.endswith(BAI_SESSION_COOKIE)
                or name.endswith(BAI_CSRF_COOKIE)
                or name.endswith(BAI_CALLBACK_COOKIE)
            )
            if not matched:
                continue
            value = _cookie_value(cookie, name)
            if not value:
                continue
            if name == BAI_SESSION_COOKIE or name.endswith(BAI_SESSION_COOKIE):
                session_found = True
            jar.append({"name": name, "value": value})
    if not session_found:
        return ""
    return json.dumps(jar, ensure_ascii=False)


def fetch_bai_user_id(cookie_header: str) -> str:
    """调用 BAI user.getUserState 取 userId (认证仅需 cookie).

    失败 (网络/认证/解析) 返回 "" 而不抛异常 — 调用方以此退化为不去重.
    cookie_header 为 build_cookie_header 的输出 (Cookie 头字符串).
    """
    if not cookie_header:
        return ""
    try:
        inner = {"json": {"unplayed": True}}
        query = urlencode({"input": json.dumps(inner, separators=(",", ":"))})
        url = f"{BAI_TRPC_BASE}/user.getUserState?{query}"
        headers = {
            "Cookie": cookie_header,
            "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                           "Gecko/20100101 Firefox/148.0"),
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://chat.b.ai",
            "Referer": "https://chat.b.ai/",
        }
        http_req = _urllib_request.Request(url, headers=headers)
        with _urllib_request.urlopen(http_req, timeout=15.0) as resp:
            if resp.status != 200:
                return ""
            body = resp.read(4 << 20).decode("utf-8", errors="replace")
        data = json.loads(body)
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            uid = data["data"].get("userId")
            return uid if isinstance(uid, str) else ""
        if isinstance(data, dict) and isinstance(data.get("result"), dict):
            # tRPC batched 形态 (兼容)
            inner = data["result"].get("data")
            if isinstance(inner, dict):
                uid = inner.get("userId")
                return uid if isinstance(uid, str) else ""
    except Exception:  # noqa: BLE001 失败不阻塞登录, 退化为不去重
        return ""
    return ""


def _login_window_title(account_type: str) -> str:
    """登录窗标题 (opencode/bai/commandcode 区分)."""
    if account_type == BAI_ACCOUNT_TYPE:
        return "GoGauge - BAI Login"
    if account_type == CC_ACCOUNT_TYPE:
        return "GoGauge - Command Code Login"
    return "GoGauge - OpenCode Go Login"


class LoginWatcher:
    """后台轮询登录窗口, 捕获 auth cookie (opencode) / session-token (bai) / 会话 cookie (commandcode)."""

    def __init__(
        self,
        win,
        on_success: Callable[[str, str, str], None],
        on_cancelled: Optional[Callable[[], None]] = None,
        account_type: str = "opencode",
    ):
        self.win = win
        self.on_success = on_success  # fn(credential, workspace_hint, account_type)
        self.on_cancelled = on_cancelled
        self.account_type = account_type if account_type in _ACCOUNT_TYPES else "opencode"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.done = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="gousage-login")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _window_alive(self) -> bool:
        try:
            return self.win in webview.windows
        except Exception:  # noqa: BLE001
            return False

    def _run(self) -> None:
        _log(f"[login] watcher started (account_type={self.account_type})")
        last_url = ""
        while not self._stop.is_set():
            try:
                url = self.win.get_current_url() or ""
            except Exception as exc:  # noqa: BLE001 窗口未加载完成或已销毁
                if not self._window_alive():
                    _log("[login] window closed, watcher exits")
                    break
                self._stop.wait(1.0)
                continue

            if url != last_url:  # 诊断: 记录完整 URL 轨迹 (含非 chat.b.ai 域)
                _log(f"[login] url -> {url[:200]}")
                last_url = url

            if self.account_type == "bai":
                if self._handle_bai(url):
                    return
            elif self.account_type == CC_ACCOUNT_TYPE:
                if self._handle_commandcode(url):
                    return
            else:
                if self._handle_opencode(url):
                    return

            self._stop.wait(COOKIE_POLL_SEC)
        if not self.done and self.on_cancelled:
            self.on_cancelled()

    def _handle_opencode(self, url: str) -> bool:
        """opencode 成功判定: URL 在 https://opencode.ai 域 + auth cookie 存在非空."""
        if not url.startswith("https://opencode.ai"):
            return False
        try:
            cookies = self.win.get_cookies() or []
            raw_desc = [str(c) for c in cookies]
        except Exception as exc:  # noqa: BLE001
            cookies = []
            raw_desc = [f"<get_cookies ERROR {type(exc).__name__}: {exc}>"]
        _log(f"[login] on opencode.ai, url={url[:120]}, cookies={raw_desc}")

        for cookie in cookies:
            # pywebview 返回 http.cookies.SimpleCookie 对象 (dict 子类!)
            for name in _cookie_names(cookie):
                if name != AUTH_COOKIE_NAME:
                    continue
                value = _cookie_value(cookie, name)
                if not value:
                    continue
                match = _WORKSPACE_URL_RE.search(url)
                workspace_hint = match.group(1) if match else "Default"
                _log(f"[login] SUCCESS: auth cookie captured (len={len(value)}), ws={workspace_hint}")
                self.done = True
                self._stop.set()
                self.on_success(f"auth={value}", workspace_hint, "opencode")
                return True
        return False

    def _handle_commandcode(self, url: str) -> bool:
        """CommandCode 成功判定: URL 在 https://commandcode.ai 域 且存在非空会话 cookie.

        better-auth 会话 cookie 名未最终确认, 按稳健规则判定 (精确名 / 后缀
        "session_token" / 名含 "session"); GitHub OAuth 等登录中间页 (非本域) 不算.
        jar 收集页面上全部非空 cookie (会话 cookie 名不确定, 全量收集最稳);
        workspace_hint = fetch_subscription 的 userId (失败退化为空串不去重).
        """
        if not url.startswith(CC_DOMAIN):
            return False
        try:
            cookies = self.win.get_cookies() or []
            names = [n for c in cookies for n in _cookie_names(c)]
        except Exception as exc:  # noqa: BLE001
            cookies = []
            names = [f"<get_cookies ERROR {type(exc).__name__}: {exc}>"]
        _log(f"[login] on commandcode.ai, url={url[:120]}, cookie_names={names}")

        session_len = 0
        jar_entries: list[dict[str, str]] = []
        for cookie in cookies or []:
            for name in _cookie_names(cookie):
                value = _cookie_value(cookie, name)
                if not value:
                    continue
                jar_entries.append({"name": name, "value": value})
                if (
                    name == "better-auth.session_token"
                    or name.endswith("session_token")
                    or "session" in name.lower()
                ):
                    session_len = len(value)
        if not session_len:
            return False  # 无非空会话 cookie: 继续轮询
        jar = json.dumps(jar_entries, ensure_ascii=False)
        cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in jar_entries)
        # workspace_hint = commandcode userId (作 dedupe_key); 失败退化为空串不去重
        from app.commandcode_api import fetch_subscription
        try:
            subscription = fetch_subscription(cookie_header)
        except Exception:  # noqa: BLE001 失败不阻塞登录, 退化为不去重
            subscription = None
        user_id = ""
        if isinstance(subscription, dict):
            uid = subscription.get("userId")
            if uid is not None:
                user_id = uid if isinstance(uid, str) else str(uid)
        _log(f"[login] CC SUCCESS: session captured (len={session_len}), userId={user_id!r}")
        self.done = True
        self._stop.set()
        self.on_success(jar, user_id, "commandcode")
        return True

    def _handle_bai(self, url: str) -> bool:
        """BAI 成功判定: URL 在 https://chat.b.ai 域 且 session-token 非空.

        仍在 Google OAuth / 登录中间页 (非 chat.b.ai 域) 视为未成功; 仅
        csrf/callback-url 两个 cookie (登录前即存在) 不构成成功.
        """
        if not url.startswith(BAI_DOMAIN):
            return False
        try:
            cookies = self.win.get_cookies() or []
            names = [n for c in cookies for n in _cookie_names(c)]
        except Exception as exc:  # noqa: BLE001
            cookies = []
            names = [f"<get_cookies ERROR {type(exc).__name__}: {exc}>"]
        _log(f"[login] on chat.b.ai, url={url[:120]}, cookie_names={names}")

        session = _extract_bai_session(cookies)
        if not session:
            return False  # 仅 csrf/callback-url 或空 token: 继续轮询
        jar = build_bai_cookie_jar(cookies)
        if not jar:
            return False
        # workspace_hint = BAI userId (作 dedupe_key); getUserState 失败退化为空串不去重
        from app.bai_api import build_cookie_header
        user_id = fetch_bai_user_id(build_cookie_header(jar))
        _log(f"[login] BAI SUCCESS: session captured (len={len(session)}), userId={user_id!r}")
        self.done = True
        self._stop.set()
        self.on_success(jar, user_id, "bai")
        return True
