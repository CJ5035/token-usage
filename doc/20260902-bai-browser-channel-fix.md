# BAI 浏览器通道修复（Cloudflare 403）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** BAI 用量/配额请求改走 WebView2 真实浏览器引擎（隐藏窗口 + JS fetch + 原生 Cookie 注入），绕过 Cloudflare 对 Python urllib 客户端指纹的人机质询；同时细化 403 错误映射（质询 ≠ 认证失败）并修正畸形 UA。

**Architecture:** `bai_api` 抽出可替换的传输层 `_transport`（默认 urllib，行为不变），401/403 分类集中在 `_fetch` 一处并识别 `Cf-Mitigated: challenge`；新增 `bai_channel` 模块：隐藏 pywebview 窗口加载 `https://chat.b.ai/usage`（与登录窗共享同进程 WebView2 cookie 存储），用 `evaluate_js` 结果槽 + 轮询执行同源 `fetch(credentials:'omit')`，经 CoreWebView2 `WebResourceRequested` 原生事件把 DB cookie jar 注入为 `Cookie` 头（多账号隔离），`activate()` 把该通道注册为 `bai_api` 传输层。**server.py 零改动**（`_fetch_bai_quota`/`_sync_bai_account` 调用的 `bai_api.fetch_*` 签名不变）。

**Tech Stack:** Python 3.12.10 / pywebview 6.2.1 (EdgeChromium/WebView2) / pythonnet (clr，已在用) / pytest 8

**Spec:** [doc/20260902-bug-diagnosis-bai-quota-403.md](20260902-bug-diagnosis-bai-quota-403.md)（诊断报告：根因为 Cloudflare 对 urllib TLS 指纹返回 `Cf-Mitigated: challenge` 403，真实 Cookie 有效；执行者需同时阅读）

## Global Constraints

- 解释器：`python`（pyenv-win 3.12.10，不可用时绝对路径 `D:\.pyenv\pyenv-win\versions\3.12.10\python.exe`）；禁止 `py`、`py -3.12`、裸 `pip`
- 代码修改后必须编译通过（`python -m py_compile`）且全量测试通过，才算修改完成
- 禁止自动签入：commit 仅在人工确认后执行（Task 7 之前不得 commit）
- `doc/` 下文档不签入
- `app/server.py`、`app/auth.py`、前端（app/web/）**零改动**
- `app/opencode_api.py` 仅允许改 `USER_AGENT` 字符串一行（opencode 请求链路不能回归）
- pywebview 6.2.1 已核实的事实（计划依据，若实现时发现不符需停下报告）：
  - `window.native` 即 EdgeChrome 实例（winforms.py:195 `self.pywebview_window.native = self`）；每窗口实例另存于 `BrowserView.instances[window.uid]`
  - EdgeChrome 实例上 `.webview` 是 WinForms WebView2 控件，`.webview.CoreWebView2` 在 `CoreWebView2InitializationCompleted` 后可用
  - `window.events.loaded.wait(timeout)` 可等页面加载；pywebview 已全局注册 `AddWebResourceRequestedFilter('*', All)`，`WebResourceRequested` 是 .NET 多播事件，可再 `+=` 自己的 handler
  - `evaluate_js` 内部经 `self.webview.Invoke(...)` 封送到 UI 线程（线程安全）并对结果做一次 `json.loads`；WebView2 `ExecuteScriptAsync` 对 Promise 的返回行为不可依赖 → **采用"结果槽 + Python 轮询"模式，不依赖 Promise 直返**
  - `create_window` 在 `webview.start()` 之前调用会排队、之后调用线程安全（window.py:418-424 非 MainThread 分支）
- 浏览器 JS `fetch` 不能设置 `Cookie`/`User-Agent`（forbidden header）→ Cookie 只能走原生事件注入；`credentials` 必须 `'omit'`（防 WebView2 profile 残留会话混入，保证按账号隔离）
- 通道请求用 `_req_lock` 串行化（配额刷新线程与同步线程可能并发，防止注入的 Cookie 串号）

## Dedupe Tickets

**Ticket 1 — `bai_api` 传输层抽象（改 `_fetch` 内部）**
- Intent signature: 模块级可替换函数 `_transport(url, headers, timeout) -> (status, text, headers)` + `set_transport()`，`_fetch` 改为消费它
- Queries: `grep -n "_fetch\|urlopen" app/bai_api.py`；`grep -rn "_transport\|set_transport" app/ tests/`；`grep -n "BAIAuthError" tests/`
- Top matches: `app/bai_api.py:70`（现有 `_fetch`，唯一 HTTP 出口）；`tests/test_bai_api.py`（现有测试全部 mock 在 `fetch_usage_*` 之上或纯函数，无 `_fetch` 直测冲突）
- Decision: `extend`
- Rationale: 3 个 trpc 端点封装/重试/JSON 解析逻辑全部保留，只在 HTTP 出口处开一个注入口；不新建平行实现

**Ticket 2 — 新模块 `app/bai_channel.py`**
- Intent signature: 隐藏 WebView 通道窗口管理 + JS fetch 执行 + 原生 Cookie 注入 + transport 适配注册
- Queries: `grep -rn "channel\|hidden=True" app/*.py`；`grep -n "create_window" app/main.py app/auth.py`；`ls app/`
- Top matches: `app/main.py:470`（登录窗 hidden=True 先例）、`app/main.py:420`（`_patch_webview_popup` 已用 clr/edgechromium 内部 API 先例）
- Decision: `new`
- Rationale: 无既有模块承担"浏览器引擎代理 HTTP"职责；与 `bai_api`（纯协议层，无 webview 依赖，可单测）分层清晰

**Ticket 3 — 新测试文件 `tests/test_bai_channel.py`、`tests/test_opencode_api.py`**
- Intent signature: bai_channel 纯逻辑（JS 构建/结果槽编排/错误映射/注册）单测；opencode_api UA 常量断言
- Queries: `ls tests/`；`grep -rln "bai_channel\|opencode_api" tests/`
- Top matches: 现有 `tests/` 仅 conftest + 5 个文件（test_db_multiuser/test_bai_api/test_bai_auth/test_bai_sync/test_main_settings），均不覆盖
- Decision: `new`
- Rationale: 按被测模块分文件的既有拆分模式；bai_channel 测试用 FakeWindow 鸭子类型，不启动真 GUI

## File Structure

- Modify: `app/bai_api.py` — `_fetch` 重构为消费 `_transport`（默认 urllib 实现，行为不变）+ 403 质询识别 + `USER_AGENT` 修正（:37-39）
- Create: `app/bai_channel.py` — 浏览器通道（窗口管理 / build_fetch_js / fetch_through_window / 原生注入 / activate）
- Modify: `app/main.py` — import；`main()` 中 `db.get_db()` 后 `ensure_window`（有 BAI 账号时）+ `activate()`；`on_login_success` bai 分支 `ensure_window`
- Modify: `app/opencode_api.py:30-33` — 仅 `USER_AGENT` 字符串
- Modify: `tests/test_bai_api.py` — 追加 transport 注入 / 403 分类 / 重试测试
- Create: `tests/test_bai_channel.py`、`tests/test_opencode_api.py`
- 不改动: `app/server.py`、`app/auth.py`、`app/web/*`、`GoGauge.spec`/`build.bat`（无新依赖，pythonnet/clr 已打包）

---

### Task 1: `bai_api` 传输层抽象 + 403 质询错误识别（TDD）

**Files:**
- Modify: `app/bai_api.py:70-101`（`_fetch` 及其上方新增传输层）
- Test: `tests/test_bai_api.py`（文件末尾追加）

**Interfaces:**
- Consumes: 现有 `BAIError`/`BAIAuthError`、`REQUEST_TIMEOUT`/`FETCH_RETRIES`/`RETRY_BACKOFF`/`MAX_BODY_BYTES` 常量
- Produces（Task 3 依赖）:
  - `bai_api.set_transport(fn: Callable[[str, dict[str, str], float], tuple[int, str, dict[str, str]]]) -> None`（幂等注册）
  - 传输层契约：成功返回 `(HTTP状态码, 响应体文本, 响应头dict)`；网络层失败（无法拿到响应）抛 `urllib.error.URLError / TimeoutError / OSError` 由 `_fetch` 重试；**任何拿到响应的情况（含 4xx/5xx）都返回而非抛出**
  - `bai_api._fetch(url, headers, timeout, retries) -> str` 签名与 2xx 行为不变；新增：`403 + Cf-Mitigated: challenge` → `BAIError("站点人机验证拦截 (Cloudflare)...")`（非 AuthError）

- [ ] **Step 1: 写失败测试**（`tests/test_bai_api.py` 末尾追加）

```python
# ---------------------------------------------------------------------------
# 传输层注入与 403 分类 (Cloudflare 质询 ≠ 认证失败, 见 doc/20260902-bug-diagnosis-bai-quota-403.md)
# ---------------------------------------------------------------------------

import urllib.error

from app.bai_api import BAIAuthError, BAIError


def _t(status, text, headers=None):
    return lambda url, headers_, timeout: (status, text, headers or {})


def test_fetch_2xx_returns_text(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", _t(200, '{"ok":true}'))
    assert bai_api._fetch("https://x", {}) == '{"ok":true}'


def test_fetch_403_challenge_is_not_auth_error(monkeypatch):
    monkeypatch.setattr(
        bai_api, "_transport",
        _t(403, "<html>Just a moment...</html>", {"Cf-Mitigated": "challenge"}),
    )
    with pytest.raises(BAIError) as ei:
        bai_api._fetch("https://x", {})
    assert not isinstance(ei.value, BAIAuthError)
    assert "人机验证" in str(ei.value)


def test_fetch_403_plain_is_auth_error(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", _t(403, "{}", {}))
    with pytest.raises(BAIAuthError):
        bai_api._fetch("https://x", {})


def test_fetch_401_is_auth_error(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", _t(401, "{}", {}))
    with pytest.raises(BAIAuthError):
        bai_api._fetch("https://x", {})


def test_fetch_500_raises_bai_error(monkeypatch):
    monkeypatch.setattr(bai_api, "_transport", _t(500, "", {}))
    with pytest.raises(BAIError, match="HTTP 500"):
        bai_api._fetch("https://x", {})


def test_fetch_retries_network_error_then_success(monkeypatch):
    calls = []

    def flaky(url, headers, timeout):
        calls.append(url)
        if len(calls) == 1:
            raise urllib.error.URLError("conn reset")
        return 200, '{"ok":1}', {}

    monkeypatch.setattr(bai_api, "_transport", flaky)
    monkeypatch.setattr(bai_api.time, "sleep", lambda s: None)
    assert bai_api._fetch("https://x", {}) == '{"ok":1}'
    assert len(calls) == 2


def test_fetch_network_exhausted_raises_bai_error(monkeypatch):
    monkeypatch.setattr(
        bai_api, "_transport",
        lambda url, h, t: (_ for _ in ()).throw(urllib.error.URLError("down")),
    )
    monkeypatch.setattr(bai_api.time, "sleep", lambda s: None)
    with pytest.raises(BAIError, match="网络错误"):
        bai_api._fetch("https://x", {})


def test_trpc_call_passes_cookie_and_uses_transport(monkeypatch):
    seen = {}

    def fake(url, headers, timeout):
        seen["url"] = url
        seen["cookie"] = headers.get("Cookie")
        return 200, json.dumps({"points_balance": 10, "points_expiring": 5}), {}

    monkeypatch.setattr(bai_api, "_transport", fake)
    got = bai_api.fetch_usage_points("a=1; b=2")
    assert got == {"points_balance": 10, "points_expiring": 5}
    assert seen["cookie"] == "a=1; b=2"
    assert "usage.points" in seen["url"]
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_bai_api.py -v -k "transport or challenge or fetch"`
Expected: FAIL，`AttributeError: module 'app.bai_api' has no attribute '_transport'`（或 403 用例断言得到 BAIAuthError 而失败）

- [ ] **Step 3: 实现**（`app/bai_api.py`）

顶部 import 区补：

```python
from collections.abc import Callable
```

`_fetch`（现为 bai_api.py:70-101）整体替换为：

```python
def _resp_header(headers: dict[str, str], name: str) -> str:
    """响应头大小写不敏感取值 (urllib 与浏览器通道的头大小写形态不同)."""
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return ""


def _default_transport(url: str, headers: dict[str, str], timeout: float) -> tuple[int, str, dict[str, str]]:
    """urllib 传输层: 拿到响应(含 4xx/5xx)一律返回, 网络层失败向上抛 (由 _fetch 重试)."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return (
                resp.status,
                resp.read(MAX_BODY_BYTES).decode("utf-8", errors="replace"),
                dict(resp.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(MAX_BODY_BYTES).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 响应体读失败不影响状态码分类
            pass
        return exc.code, body, dict(exc.headers.items()) if exc.headers else {}


_transport: Callable[[str, dict[str, str], float], tuple[int, str, dict[str, str]]] | None = None


def set_transport(
    fn: Callable[[str, dict[str, str], float], tuple[int, str, dict[str, str]]],
) -> None:
    """注册替换传输层 (浏览器通道见 bai_channel.activate); 重复注册以最后一次为准."""
    global _transport
    _transport = fn


def _fetch(
    url: str,
    headers: dict[str, str],
    timeout: float = REQUEST_TIMEOUT,
    retries: int = FETCH_RETRIES,
) -> str:
    """经注册传输层发 GET: 2xx 返回文本, 分类错误, 网络失败按退避重试.

    401/403 分类: 403 且带 ``Cf-Mitigated: challenge`` 为 Cloudflare 人机质询
    (请求未达 BAI 后端, Cookie 有效与否无关, 见诊断报告), 报 BAIError 而非
    BAIAuthError, 避免误导用户重新登录.
    """
    transport = _transport or _default_transport
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            status, text, resp_headers = transport(url, headers, timeout)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)])
            continue
        if status == 401 or status == 403:
            if status == 403 and _resp_header(resp_headers, "Cf-Mitigated").lower() == "challenge":
                raise BAIError("站点人机验证拦截 (Cloudflare)，无法获取 BAI 数据")
            raise BAIAuthError(f"认证失败 (HTTP {status})，请重新登录")
        if status < 200 or status >= 300:
            raise BAIError(f"请求返回 HTTP {status}")
        return text
    if isinstance(last_exc, urllib.error.URLError):
        raise BAIError(f"网络错误: {last_exc.reason}") from last_exc
    raise BAIError(f"网络错误: {last_exc}") from last_exc
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_bai_api.py -v`
Expected: 全部 PASS（既有用例 + 新增 8 个）

- [ ] **Step 5: 编译**

Run: `python -m py_compile app/bai_api.py tests/test_bai_api.py`
Expected: 无输出，退出码 0

---

### Task 2: 修正畸形 UA（bai_api + opencode_api）

**Files:**
- Modify: `app/bai_api.py:37-39`
- Modify: `app/opencode_api.py:30-33`
- Test: `tests/test_bai_api.py`（追加）、`tests/test_opencode_api.py`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `bai_api.USER_AGENT` / `opencode_api.USER_AGENT` 均为合法 Firefox UA（含 `rv:` token）；浏览器通道下该值仅作 urllib 兜底，JS fetch 用真实浏览器 UA

- [ ] **Step 1: 写失败测试**

`tests/test_bai_api.py` 末尾追加：

```python
def test_user_agent_is_plausible_firefox():
    """UA 必须是合法 Firefox 形态 (含 rv: token); 畸形 UA 会被 bot 评分盯上."""
    assert "rv:" in bai_api.USER_AGENT
    assert bai_api.USER_AGENT.startswith("Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15")
    assert "Gecko/20100101 Firefox/" in bai_api.USER_AGENT
```

新建 `tests/test_opencode_api.py`：

```python
"""opencode_api.py 单测: UA 常量合法性."""
from app import opencode_api


def test_user_agent_is_plausible_firefox():
    """与 bai_api 同步修正: 畸形 UA (缺 rv:) 是 bot 评分信号."""
    assert "rv:" in opencode_api.USER_AGENT
    assert "Gecko/20100101 Firefox/" in opencode_api.USER_AGENT
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_bai_api.py::test_user_agent_is_plausible_firefox tests/test_opencode_api.py -v`
Expected: FAIL（两个断言失败：现值 `(Macintosh; Intel Mac OS X 10_15_7) Gecko/...` 无 `rv:` 且路径段为 `10_15_7`）

- [ ] **Step 3: 实现**（两处常量改为相同值）

```python
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:148.0) Gecko/20100101 Firefox/148.0"
)
```

- [ ] **Step 4: 运行确认通过 + 编译**

Run: `python -m pytest tests/test_bai_api.py tests/test_opencode_api.py -v && python -m py_compile app/bai_api.py app/opencode_api.py tests/test_opencode_api.py`
Expected: 全部 PASS，编译退出码 0

---

### Task 3: `bai_channel` 浏览器通道模块（TDD, FakeWindow）

**Files:**
- Create: `app/bai_channel.py`
- Test: `tests/test_bai_channel.py`（新建）

**Interfaces:**
- Consumes: `bai_api.BAIError`/`set_transport`（Task 1；错误分类统一在 `bai_api._fetch`，通道只透传 `(status, body, headers)`，不消费 `BAIAuthError`）；pywebview `webview.create_window`/`window.events.loaded`/`window.evaluate_js`/`window.native`（运行时）
- Produces（Task 4 依赖）:
  - `ensure_window() -> None`（幂等创建隐藏通道窗口，start 前后调用均安全）
  - `activate() -> None`（幂等把浏览器通道注册为 `bai_api` 传输层）
  - `build_fetch_js(url: str, slot: str, timeout_sec: float) -> str`（纯函数）
  - `fetch_through_window(url: str, cookie: str, timeout: float) -> tuple[int, str, dict[str, str]]`（传输层契约同 Task 1）

- [ ] **Step 1: 写失败测试**（新建 `tests/test_bai_channel.py`）

```python
"""bai_channel.py 单测: JS 构建 / 结果槽编排 / 传输层注册 (FakeWindow, 不启动 GUI)."""
from __future__ import annotations

import itertools
import json

import pytest

from app import bai_api, bai_channel


# --------------------------- FakeWindow ------------------------------------

class _FakeEvents:
    def wait(self, timeout=None):
        return True


class _FakeEdge:
    """win.native: 仅用于被 _attach_cookie_injection 消费 (测试中替换为 no-op)."""

    def __init__(self):
        self.webview = self
        self.CoreWebView2 = object()


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
    """通道模块状态隔离: 屏蔽原生订阅; 重置 slot 序列, 使各用例 slot 恒为 r1
    (用例预期启动值不依赖执行顺序, 支持单独运行单个用例)."""
    monkeypatch.setattr(bai_channel, "_attach_cookie_injection", lambda win: None)
    monkeypatch.setattr(bai_channel, "_window", None)
    monkeypatch.setattr(bai_channel, "_attached", set())
    monkeypatch.setattr(bai_channel, "_slot_seq", itertools.count(1))


# --------------------------- build_fetch_js --------------------------------

def test_build_fetch_js_contains_url_slot_and_omit_credentials():
    js = bai_channel.build_fetch_js("https://chat.b.ai/trpc/lambda/usage.points?input=x", "r7", 30.0)
    assert 'var slot = "r7"' in js
    assert "https://chat.b.ai/trpc/lambda/usage.points?input=x" in js
    assert 'credentials: "omit"' in js  # 禁用 profile cookie, 全靠原生注入
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
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_bai_channel.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'app.bai_channel'`

- [ ] **Step 3: 实现**（新建 `app/bai_channel.py`）

```python
"""BAI 浏览器通道: BAI 请求经 WebView2 真实引擎发出, 绕过 Cloudflare 人机质询.

背景 (doc/20260902-bug-diagnosis-bai-quota-403.md): chat.b.ai 的 Cloudflare 对
Python urllib 的 TLS/客户端指纹返回 403 质询页 (Cf-Mitigated: challenge),
真实 Cookie 也无法通过; 浏览器引擎(与登录窗同进程同 cookie 存储)可正常通过.

机制:
- 隐藏窗口加载 https://chat.b.ai/usage (同源页面, fetch 无 CORS 问题)
- evaluate_js 起搏 fetch, 结果写入 window.__gousage[slot], Python 轮询读取
  (不依赖 ExecuteScriptAsync 对 Promise 的返回行为)
- Cookie 不能由 JS 设置 (forbidden header), 经 CoreWebView2
  WebResourceRequested 原生事件把账号 cookie jar 注入为请求头;
  fetch 用 credentials:'omit' 防 profile 残留会话串号 (多账号隔离)
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
TRPC_PREFIX = "https://chat.b.ai/trpc/lambda/"
JS_FETCH_TIMEOUT = 30.0  # JS 内 AbortController 超时 (秒)
POLL_INTERVAL = 0.15  # 结果槽轮询间隔 (秒)
POLL_TIMEOUT = 45.0  # 结果槽轮询总超时 (秒)
_READY_TIMEOUT = 30.0  # 等待通道窗口 loaded 超时 (秒)
_MAX_BODY_BYTES = 4 << 20  # 与 bai_api.MAX_BODY_BYTES 口径一致

_win_lock = threading.Lock()
_req_lock = threading.Lock()
_attach_lock = threading.Lock()  # 事件订阅幂等守卫 (防配额/同步线程并发首次请求重复订阅)
_window: Any = None  # pywebview Window (延迟创建, 测试注入 FakeWindow)
_pending_cookie = ""  # 当前在途请求的 Cookie 头 (原生 handler 读取)
_slot_seq = itertools.count(1)
_handler_ref: Any = None  # 持有 .NET 委托强引用, 防被 GC 后事件失效
_attached: set[int] = set()  # 已注入事件的窗口 (按 id 去重)


def ensure_window() -> None:
    """创建隐藏通道窗口 (幂等). webview.start() 前后调用均安全 (start 前排队)."""
    global _window
    import webview

    with _win_lock:
        if _window is not None and _window in webview.windows:
            return
        _window = webview.create_window("GoGauge BAI Channel", CHANNEL_URL, hidden=True)


def _attach_cookie_injection(win: Any) -> None:
    """在 CoreWebView2 上挂原生请求事件, 对 trpc 请求注入 Cookie 头 (幂等).

    pywebview 已全局 AddWebResourceRequestedFilter('*', All), 事件多播可直接
    叠加 handler; 订阅经 webview.Invoke 封送到 UI 线程 (与 pywebview 自身做法一致).
    """
    with _attach_lock:  # 检查与订阅同临界区: 防配额/同步线程并发首次请求重复订阅
        if id(win) in _attached:
            return
        from System import Func
        from Microsoft.Web.WebView2.Core import (
            CoreWebView2WebResourceRequestedEventHandler,
        )

        edge = win.native
        core = edge.webview.CoreWebView2

        def _subscribe() -> None:
            core.WebResourceRequested += CoreWebView2WebResourceRequestedEventHandler(
                _on_resource_request
            )

        edge.webview.Invoke(Func[object](_subscribe))
        global _handler_ref
        _handler_ref = _on_resource_request  # 委托被事件持有, 这里再保一层引用
        _attached.add(id(win))


def _on_resource_request(sender: Any, args: Any) -> None:
    """原生请求拦截: 仅对 trpc 请求覆写 Cookie 头 (JS 侧 credentials:'omit')."""
    uri = str(args.Request.Uri)
    if uri.startswith(TRPC_PREFIX) and _pending_cookie:
        args.Request.Headers.SetHeader("Cookie", _pending_cookie)


def _ready_window(timeout: float) -> Any:
    """返回就绪的通道窗口: 已加载 + CoreWebView2 可用 + 注入事件已挂."""
    global _window
    if _window is None:
        ensure_window()
    win = _window
    if win is None:
        raise BAIError("浏览器通道窗口不可用")
    if not win.events.loaded.wait(timeout):
        raise BAIError("浏览器通道页面加载超时")
    edge = getattr(win, "native", None)
    core = getattr(getattr(edge, "webview", None), "CoreWebView2", None)
    if core is None:
        raise BAIError("浏览器通道未就绪 (CoreWebView2 未初始化)")
    _attach_cookie_injection(win)
    return win


def build_fetch_js(url: str, slot: str, timeout_sec: float) -> str:
    """构造起搏 fetch 的 JS: 结果写 window.__gousage[slot], 立即返回 slot."""
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
        'credentials: "omit", '
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
    with _req_lock:
        global _pending_cookie
        _pending_cookie = cookie or ""
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
            _pending_cookie = ""

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
```

实现备注（执行者注意）：
- `_pending_cookie` 的写入都在 `_req_lock` 内；原生 handler 在 UI 线程只读，GIL 保证原子读。
- `url` 直接内插进 JS 字符串：URL 由 `_trpc_url` 生成（urlencode 过），含双引号概率为零；不加转义是当前契约下的简化。
- 注入按 URI 前缀匹配，隐藏页自身（LobeChat 页面 JS）发起的 trpc 请求也会命中并带上注入的 Cookie——同账号下无害（仅影响隐藏页内的渲染数据），属预期行为，非缺陷。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_bai_channel.py -v`
Expected: 全部 PASS（9 个用例）

- [ ] **Step 5: 编译**

Run: `python -m py_compile app/bai_channel.py tests/test_bai_channel.py`
Expected: 无输出，退出码 0

---

### Task 4: `main.py` 接线（通道窗口创建 + transport 注册）

**Files:**
- Modify: `app/main.py`（import 区 + `main()` 内 `db.get_db()` 之后 + `on_login_success` bai 分支）

**Interfaces:**
- Consumes: `bai_channel.ensure_window()`、`bai_channel.activate()`（Task 3）
- Produces: 无新接口（运行时接线，行为由 Task 6 手动验收覆盖；`on_login_success` 为闭包内函数，不做单测）

- [ ] **Step 1: 修改 `app/main.py`**

import 区（与 `from . import ...` 既有行并列）：

```python
from . import bai_channel
```

`main()` 内 `db.get_db()`（440 行）之后、`server.start_server()` 之前插入：

```python
    # BAI 浏览器通道: 有 BAI 账号时预建隐藏通道窗口 (start 前创建, 随 start 初始化);
    # transport 注册始终执行 (无 BAI 账号时不会被触达, 不产生额外请求)
    try:
        _has_bai = db.get_db().execute(
            "SELECT 1 FROM accounts WHERE source = 'bai' LIMIT 1"
        ).fetchone()
    except Exception:  # noqa: BLE001 查询失败按无 BAI 账号处理
        _has_bai = None
    if _has_bai:
        bai_channel.ensure_window()
    bai_channel.activate()
```

`on_login_success` 的 bai 分支（现 517-521 行）内、`db.add_account(...)` 成功后追加一行：

```python
            if account_type == "bai":
                db.add_account(
                    credential, workspace_hint,
                    switch=True, source="bai", dedupe_key=workspace_hint,
                )
                bai_channel.ensure_window()  # 新增 BAI 账号 → 确保通道窗口已建 (start 后创建, 线程安全)
```

- [ ] **Step 2: 编译 + 全量回归**

Run: `python -m py_compile app/main.py && python -m pytest tests/ -q`
Expected: 编译退出码 0；全部测试通过（既有 + Task 1-3 新增，0 failed）

- [ ] **Step 3: 冒烟 import 检查**（webview/clr 延迟导入不被测试触发）

Run: `python -c "from app import bai_channel; bai_channel.activate(); import app.bai_api as b; assert b._transport is not None; print('ok')"`
Expected: 输出 `ok`（不创建窗口、不发请求、不拉起 GUI）

---

### Task 5: 全量编译与测试门禁

- [ ] **Step 1: 全模块编译**

Run: `python -m py_compile app/bai_api.py app/bai_channel.py app/main.py app/opencode_api.py app/server.py tests/test_bai_api.py tests/test_bai_channel.py tests/test_opencode_api.py`
Expected: 退出码 0

- [ ] **Step 2: 全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全部通过（6 个测试文件，0 failed）

---

### Task 6: 打包与手动验收（需用户参与）

**Files:**
- 产物: `dist\GoGauge.exe`（build.bat，PyInstaller 参数不变：`--collect-submodules webview --hidden-import clr/pythonnet` 已覆盖本改动，无新依赖）

- [ ] **Step 1: 打包**

Run: `build.bat`（或其内部 pyinstaller 命令）
Expected: `dist\GoGauge.exe` 生成

- [ ] **Step 2: 部署到运行目录**

复制 `dist\GoGauge.exe` → `D:\绿色版\GoGauge\`（沿用现有数据目录 `data\gousage.db`，User 2 的 BAI cookie jar 已在库中）。

- [ ] **Step 3: 验收（全部满足才通过）**

1. 启动后**不再出现**「配额获取失败：认证失败 (HTTP 403)」横幅；BAI 账号配额卡显示「余额 X 积分」
2. 点右上角刷新 → 同步完成后 `D:\绿色版\GoGauge\data\gousage.db` 出现 `provider='bai'` 的 `usage_records` 行；使用记录页可见数据
3. opencode 账号（Default）配额三窗口（5h/weekly/monthly）与既有 1.8 万条用量统计**无回归**
4. （若可测）添加第二个 BAI 账号 → 账户总览页两账号积分/用量独立正确（Cookie 注入隔离生效）
5. （可选负路径）断网启动 → 错误文案为网络类错误而非「请重新登录」

- [ ] **Step 4: 回滚预案（仅验收失败时）**

```bash
git checkout -- app/bai_api.py app/main.py app/opencode_api.py tests/test_bai_api.py
```
并删除 `app/bai_channel.py`、`tests/test_bai_channel.py`、`tests/test_opencode_api.py`（均为本次新增），回诊断报告评估方案 B（curl_cffi）。

---

### Task 7: 签入（人工确认后执行）

- [ ] **Step 1: 人工确认后 commit**（仅代码文件，doc/ 不签入）

```bash
git add app/bai_api.py app/bai_channel.py app/main.py app/opencode_api.py tests/test_bai_api.py tests/test_bai_channel.py tests/test_opencode_api.py
git commit -m "fix: BAI 请求改走 WebView2 浏览器通道绕过 Cloudflare 质询 + 403 错误分类细化 + UA 修正"
```

---

## Self-Review

1. **Spec coverage**（对照诊断报告「总结与建议」）：方案 A（浏览器引擎通道）→ Task 3+4；附带项错误映射细化（403+challenge → 人机验证文案，401/纯 403 → 重新登录）→ Task 1；UA 修正两处 → Task 2；server.py 零改动约束 → 全局 Constraints + Task 3（`bai_api.fetch_*` 签名不变）；多账号隔离（诊断边缘情况）→ `_req_lock` 串行 + 原生 Cookie 注入 + `credentials:'omit'`；验收标准对应诊断中的失败现象 → Task 6。无遗漏。
2. **Placeholder scan**：所有步骤含实际代码/命令/预期输出；JS、传输层、测试代码均为完整可落地版本；无 TBD/TODO。
3. **Type consistency**：传输层契约 `(status: int, text: str, headers: dict[str,str])`、网络失败抛 `URLError/TimeoutError/OSError` 在 Task 1（定义）、Task 3（消费/实现）、`test_fetch_challenge_header_passthrough` ↔ `bai_api._fetch` 的 `Cf-Mitigated` 读取之间一致；`set_transport`/`_transport` 名称在 Task 1 定义与 Task 3 `activate()`、测试中一致；`ensure_window`/`activate` 在 Task 3 定义与 Task 4 调用一致。

## 修订记录

- **2026-09-02 v2（/goal review 第 1 轮，发现 5 项）**：
  - D1 轮询超时改为 `deadline = time.monotonic() + POLL_TIMEOUT`（原 `max(POLL_TIMEOUT, timeout)` 会使超时测试真实空转约 30 秒）；`fetch_through_window` 的 `timeout` 参数注明仅为契约签名
  - D2 Task 3 Step 4 用例数 10 → 9（实际数量）
  - D3 `bai_channel` 删除未使用的 `BAIAuthError` 导入及相应备注
  - D4 `_attach_cookie_injection` 的幂等检查与订阅移入同一 `_attach_lock` 临界区（原写法并发下仍可能重复订阅）
  - D5 `test_fetch_success_flow` 补 `time.sleep` 补丁（消除真实 0.15s 等待）
- **2026-09-02 v3（/goal review 第 3 轮，发现 1 项）**：
  - Task 3 Interfaces 的 Consumes 移除 `BAIAuthError`（与 D3 修复后的实际导入保持一致），并注明错误分类统一在 `bai_api._fetch`
  - 实现备注补充：隐藏页自身发起的 trpc 请求同样命中注入前缀，同账号下无害属预期行为
- **2026-09-02 v4（/goal review 第 4 轮，发现 1 项）**：
  - `test_fetch_success_flow` 断言 `win.calls[1]` → `win.calls[0]`（`calls[0]` 才是启动 JS，原断言按代码对演必然失败）
- **2026-09-02 v5（/goal review 第二轮循环 第 1 轮，发现 1 项）**：
  - D6 测试顺序依赖：`_slot_seq` 为模块级计数器，原用例硬编码 `r2`~`r7` 递增启动值，单独运行任一用例会因 slot 恒从 `r1` 开始而假阳性失败。修复：autouse fixture 重命名 `_reset_channel_state` 并重置 `_slot_seq`，各用例启动值统一 `r1`，与执行顺序解耦
- **2026-09-02 v6（用户验收发现"同步中永久卡死"，无头复现实锤）**：
  - **缺陷**：WebView2 的 WinForms 封装对 `WebView2.CoreWebView2` 属性强制 UI 线程亲和——工作线程访问抛 `InvalidOperationException: CoreWebView2 can only be accessed from the UI thread`（实测堆栈见 `.superpowers/sdd/20260902-bai-browser-channel-fix/diag_hang.log`）。`bai_channel._ready_window` 的 `getattr(edge.webview, "CoreWebView2", None)` 与 `_attach_cookie_injection` 的 `core = edge.webview.CoreWebView2` 均在工作线程直接访问 → 通道在真实 GUI 必然失败。FakeWindow 单测无法暴露线程亲和性，属计划"已核实 pywebview 事实"遗漏项。
  - **修复**：所有 `CoreWebView2` 访问必须经 `Control.Invoke(Func[object](...))` 封送 UI 线程：①新增 `_invoke_on_ui(edge, fn)`；②`_ready_window` 经其取 core 判就绪；③`_attach_cookie_injection` 把 `core = edge.webview.CoreWebView2` 移入 `_subscribe`（本就经 Invoke 在 UI 线程执行）。
  - 其余通道交互复核：`evaluate_js`（内部已 Invoke）、`events.loaded.wait`（纯 Python Event）、`WebResourceRequested` 回调（UI 线程触发）均无需改动。
- **2026-09-02 v7（无头验证第二轮发现，两处实测修正）**：
  - **v6 补充修正**：pythonnet 3.1.0 下 `Func[object]` 泛型委托不可用（`TypeError: type(s) expected`），必须 `from System import Object` 用 `Func[Object]`（pywebview 同款）；`CoreWebView2WebResourceRequestedEventHandler` 委托类型在该程序集中不存在（`dir()` 枚举为空），事件挂接改用 pywebview 同款 **`core.WebResourceRequested += <Python 函数>` 直接挂接**；`_handler_ref` 防护随之删除。
  - **新缺陷（Cloudflare 凭证不全）**：`credentials:'omit'` 使浏览器不带任何 cookie，原生注入仅含 DB jar 的 3 个 authjs 会话 cookie；Cloudflare 还要求设备级 `cf_clearance`/`__cf_bm`（存在于 WebView2 profile cookie store，隐藏窗加载过质询后获得）。缺它们即使真实浏览器引擎也被质询（实测 403 + Cf-Mitigated: challenge）。
  - **修复**：①新增 `_profile_cloudflare_cookies(edge)`——经 `_invoke_on_ui` 在 UI 线程调 `CookieManager.GetCookiesAsync("https://chat.b.ai/")`，工作线程 `Task.Wait(10000)` 有界等待，过滤 `cf_`/`__cf_bm` 前缀；②`fetch_through_window` 在起搏 fetch 前轮询等待 `cf_clearance` 出现（最长 15s，未出现也继续尝试，由既有 403→"人机验证拦截"文案兜底），把 profile cf cookie 与账号 jar 合并为注入 Cookie 头——cf 系为设备级（与账号无关），authjs 仍按账号 jar 隔离。
- **2026-09-02 v8（无头实验链最终定案，实测 200 拿到真实积分数据）**：
  - **实验结论（diag_hang.log 全程留痕）**：①Cloudflare 质询在隐藏窗会**自动通过但耗时约 25-38s**（`document.title` 从「请稍候…」→ None（跳转）→ 'BAI'），此前一切 403 challenge 都发生在质询完成前；②`WebResourceRequested` 的 `SetHeader("Cookie")` **覆盖不了** `credentials:'include'` 时网络层自动计算的 Cookie（Exp D：注入 authjs 仍 401）——头注入路线废弃；③**正确配方**：质询等待（标题轮询）+ 把账号 authjs cookie 经 `CookieManager.CreateCookie/AddOrUpdateCookie`（UI 线程，IsSecure=True，domain=`chat.b.ai`，path=`/`）**写入 profile CookieStore** + `credentials:'include'`（浏览器自动携带 profile 全套 cookie：cf_clearance/__cf_bm + 账号 authjs）→ 实测 **HTTP 200 + points_balance=300000**。
  - **代码改造（bai_channel.py 重构）**：删除 `_on_resource_request`/`_attach_cookie_injection`/`_pending_cookie`/`_attach_lock`/`_attached`/`_profile_cloudflare_cookies`/`CF_COOKIE_WAIT`；新增 `_wait_challenge_ready(win, timeout)`（标题轮询，CHALLENGE_WAIT=60s 封顶，超时放行由 403 分类兜底）与 `_sync_account_cookies(edge, cookie)`（解析 Cookie 头 → CookieManager 写入 profile，单次 `_invoke_on_ui`）；`build_fetch_js` 改 `credentials:'include'`；`_invoke_on_ui` 加固为 `BeginInvoke`+`AsyncWaitHandle.WaitOne(10s)`（有界、防 GIL 级冻结，超时抛 BAIError）。
  - **时序预期**：应用启动后首次 BAI 请求含质询等待约 25-40s（cf_clearance 入 profile 后，后续请求即时）；同步界面"同步中"持续约 1 分钟属预期。
  - **v8.1 补充（scoped 重审后定稿）**：`_invoke_on_ui` 采用 error 槽模式（`_run` 内自捕异常，WaitOne 成功后原样重抛——`BeginInvoke` 不会自动重抛）；`_sync_account_cookies` 调用必须位于 `with _req_lock:` 临界区**内**（锁外同步存在他账号覆盖 CookieStore 的串号窗口）。
- **2026-09-02 v9（用户验收二轮：通道已通但「余额 0 积分 / 0 条记录」）**：
  - **现象**：Points 卡正常渲染（无 403 横幅，证明通道与 Cookie 全部生效），但余额显示 0、用量 0 条。
  - **根因**：tRPC GET 响应是信封结构 `{"result":{"data":{"json":<实际数据>}}}`（无头实测原始体：`{"result":{"data":{"json":{"points_balance":300000,...}}}}`），`_fetch_json` 原样返回顶层，而 `fetch_usage_points`/`fetch_usage_records` 及 server 同步循环都在顶层 `.get("points_balance")/.get("data")` → 取到 None → 积分显示 0、记录页按空页终止。设计文档 §2.3 的字段名按 devtools 解包后对象记录，实现层漏了解包。
  - **修复**：`_fetch_json` 在 tRPC error 检查**之后**沿 `result → data → json` 链解包（任一环缺失即停，解包结果非 dict 则回退原数据），三个端点与同步循环零改动受益。
  - **注意**：tRPC 错误信封是顶层 `{"error":{...}}`（401 实测形态），error 检查必须先于解包。
  - **v9.1 补充（端到端验证发现 usage.records 入参 400）**：实测（probe.log）`{"pageSize":N}` OK（N=5/100 均可，`{}` 默认 20 条）；`cursor:null` 与 `cursor:""` 均被服务端 zod 校验拒绝（HTTP 400）。修复：`fetch_usage_records` 在 cursor=None 时**省略 cursor 键**；响应键 `data/has_more/next_cursor/page/pageSize` 实测与 server 同步循环读取吻合，`next_cursor` 为不透明字符串可直接回传翻页。端到端实测：`fetch_usage_points` 经真实浏览器通道返回 `points_balance=300000`。
