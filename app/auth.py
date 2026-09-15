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
import time
import uuid
from http.cookies import SimpleCookie as SimpleCookieCls
from typing import Callable, Optional
from urllib import request as _urllib_request
from urllib.parse import urlencode, urlsplit

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
WB_LOGIN_URL = "https://www.workbuddy.cn/profile/plans-usage"
WB_DOMAIN = "https://www.workbuddy.cn"
WB_ACCOUNT_TYPE = "workbuddy"
_WB_PROBE_INTERVAL = 3.0    # 两次窗口内探测的最小间隔 (秒)
_WB_JS_FETCH_TIMEOUT = 8.0  # 窗口内 fetch 的 abort 超时 (秒)
_WB_POLL_TIMEOUT = 10.0     # 等待结果槽写入的总超时 (秒)
_WB_POLL_INTERVAL = 0.2     # 结果槽轮询间隔 (秒)
_WB_LOG_INTERVAL = 5.0      # 探测失败日志节流 (秒)
_WB_MAX_BODY = 1 << 20      # 窗口内响应体截断 (字符)
_ACCOUNT_TYPES = ("opencode", "bai", "commandcode", "workbuddy")


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
    if account_type == WB_ACCOUNT_TYPE:
        return WB_LOGIN_URL
    params = {
        "client_id": LOGIN_CLIENT_ID,
        "redirect_uri": LOGIN_REDIRECT_URI,
        "response_type": "code",
        "state": uuid.uuid4().hex,
    }
    return f"{LOGIN_BASE}?{urlencode(params)}"


def _build_wb_probe_js(slot: str) -> str:
    """构造登录窗口内探测 /console/accounts 的 JS (bai_channel.build_fetch_js 同款槽模式).

    异步 fetch 结果写 window.__gousage[slot] 后立即返回 slot, 规避 evaluate_js 对
    Promise 返回值的平台差异; status/path/ct/body 全部带回, 分类在 Python 侧完成
    (便于单测). credentials:'include' 使浏览器自动携带全套会话 Cookie 与同域
    Keycloak 静默链, 与页面自身请求完全同链路 (20260915 诊断 §11.5).
    """
    return (
        "(function(){"
        f'var slot = "{slot}";'
        'window.__gousage = window.__gousage || {};'
        'window.__gousage[slot] = null;'
        "var ctrl = new AbortController();"
        f"setTimeout(function(){{ ctrl.abort(); }}, {int(_WB_JS_FETCH_TIMEOUT * 1000)});"
        'fetch("/console/accounts", {'
        'method: "GET", '
        'credentials: "include", '
        'headers: { "Accept": "application/json, text/plain, */*" }, '
        "signal: ctrl.signal"
        "}).then(function(r){"
        'var path = "";'
        'try { path = new URL(r.url).pathname; } catch (e) {}'
        'var ct = r.headers.get("content-type") || "";'
        "return r.text().then(function(t){"
        f"return {{ status: r.status, path: path, ct: ct, body: t.substr(0, {_WB_MAX_BODY}) }};"
        "});"
        "}).catch(function(e){"
        "return { status: 0, error: String(e) };"
        "}).then(function(v){"
        "window.__gousage[slot] = v;"
        "});"
        "return slot;"
        "})()"
    )


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
    if account_type == WB_ACCOUNT_TYPE:
        return "GoGauge - WorkBuddy Login"
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
        self._start_lock = threading.Lock()
        self._wb_next_probe_at = 0.0
        self._wb_last_failure_log_at = float("-inf")
        self._wb_probe_seq = 0

    def start(self) -> None:
        with self._start_lock:
            if self.done or self._stop.is_set():
                return
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, daemon=True, name="gousage-login")
            self._thread.start()

    def stop(self) -> None:
        with self._start_lock:
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
                if self.account_type == WB_ACCOUNT_TYPE:
                    p = urlsplit(url)
                    _log(f"[login] url -> {p.scheme}://{p.netloc}{p.path}")
                else:
                    _log(f"[login] url -> {url[:200]}")
                last_url = url

            if self.account_type == "bai":
                if self._handle_bai(url):
                    return
            elif self.account_type == CC_ACCOUNT_TYPE:
                if self._handle_commandcode(url):
                    return
            elif self.account_type == WB_ACCOUNT_TYPE:
                if self._handle_workbuddy(url):
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

    def _handle_workbuddy(self, url: str) -> bool:
        """WorkBuddy success: same-site profile URL + 登录窗口内 /console/accounts 校验成功.

        站点鉴权为同源 Cookie + 同域 Keycloak 静默链 (doc/Bug诊断报告/
        bug-diagnosis-WorkBuddy网页登录后未回填账号-20260915.md §11): 匿名访客
        也存在 7 天 session Cookie, "有 session"不是登录证据; Python 重放 Cookie
        快照会被网关 302 到登录页, 故借用窗口自身链路探测; 身份取
        body.data.accounts[].uid (优先 lastLogin), 而非 data.userId.
        """
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.workbuddy.cn"
            or not (parsed.path == "/profile" or parsed.path.startswith("/profile/"))
        ):
            return False
        if self.done or self._stop.is_set():
            return False
        now = time.monotonic()
        if now < self._wb_next_probe_at:
            return False
        self._wb_next_probe_at = now + _WB_PROBE_INTERVAL

        result = self._wb_probe_accounts()
        reason, accounts = self._wb_classify_probe(result)
        if reason:
            self._wb_log_probe_failure(now, reason)
            return False

        picked = next((a for a in accounts if isinstance(a, dict) and a.get("lastLogin")), accounts[0])
        value = picked.get("uid") if isinstance(picked, dict) else None
        user_id = "" if value is None else (value if isinstance(value, str) else str(value))
        if not user_id:
            self._wb_log_probe_failure(now, "missing_uid")
            return False

        try:
            cookies = self.win.get_cookies() or []
        except Exception:  # noqa: BLE001 窗口已销毁等
            self._wb_log_probe_failure(now, "get_cookies_error")
            return False
        jar_entries: list[dict[str, str]] = []
        for cookie in cookies:
            for name in _cookie_names(cookie):
                value = _cookie_value(cookie, name)
                if not value:
                    continue
                jar_entries.append({"name": name, "value": value})
        jar = json.dumps(jar_entries, ensure_ascii=False)

        with self._start_lock:
            if self._stop.is_set() or self.done:
                return False
            self.done = True
            self._stop.set()
            self.on_success(jar, user_id, WB_ACCOUNT_TYPE)
        nickname = ""
        if isinstance(picked, dict):
            nickname = picked.get("enterpriseUserName") or picked.get("nickname") or ""
        _log(f"[login] WorkBuddy SUCCESS: uid={user_id!r}, nickname={nickname!r}, jar_cookies={len(jar_entries)}")
        return True

    def _wb_probe_accounts(self) -> dict | None:
        """登录窗口内起搏一次 /console/accounts 探测并轮询结果. 超时/异常/中途停止返回 None."""
        self._wb_probe_seq += 1
        slot = f"wb{self._wb_probe_seq}"  # 每次探测独占槽位, 迟到的旧响应不会覆盖新探测
        try:
            started = self.win.evaluate_js(_build_wb_probe_js(slot))
            if started != slot:
                return None
            deadline = time.monotonic() + _WB_POLL_TIMEOUT
            while time.monotonic() < deadline:
                if self._stop.is_set():
                    return None
                res = self.win.evaluate_js(f'window.__gousage["{slot}"]')
                if isinstance(res, dict):
                    return res
                time.sleep(_WB_POLL_INTERVAL)
            return None
        except Exception:  # noqa: BLE001 窗口未就绪/已销毁
            return None
        finally:
            try:
                self.win.evaluate_js(f'delete window.__gousage["{slot}"]')
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _wb_classify_probe(result: dict | None) -> tuple[str, list]:
        """探测结果分类. 返回 (失败原因码, 账号列表); 原因码为空串表示拿到非空账号列表.

        原因码与 20260915 诊断 §11.5 对齐: probe_inconclusive / network_error /
        redirect_to_login / http_<n> / non_json_response / empty_accounts.
        """
        if result is None:
            return "probe_inconclusive", []
        if result.get("status") == 0:
            return "network_error", []
        path = str(result.get("path") or "")
        if path.startswith("/auth/realms/"):
            return "redirect_to_login", []
        status = result.get("status")
        if not isinstance(status, int) or status < 200 or status >= 300:
            return f"http_{status}", []
        if "json" not in str(result.get("ct") or ""):
            return "non_json_response", []
        try:
            body = json.loads(result.get("body") or "")
        except ValueError:
            return "non_json_response", []
        data = body.get("data") if isinstance(body, dict) else None
        accounts = data.get("accounts") if isinstance(data, dict) else None
        if not isinstance(accounts, list) or not accounts:
            return "empty_accounts", []
        return "", accounts

    def _wb_log_probe_failure(self, now: float, reason: str) -> None:
        """节流输出探测失败原因 (脱敏: cookie 只带名字与值长度, 不带值; 兼作 §11.6 会话形态观察点)."""
        if now - self._wb_last_failure_log_at < _WB_LOG_INTERVAL:
            return
        try:
            cookies = self.win.get_cookies() or []
            names = [f"{n}({len(_cookie_value(c, n))})" for c in cookies for n in _cookie_names(c)]
        except Exception:  # noqa: BLE001
            names = ["<get_cookies ERROR>"]
        _log(f"[login] WorkBuddy probe failed: {reason}, cookies={names}")
        self._wb_last_failure_log_at = now
