"""界面优化五项回归 (20260915, 设计文档 doc/20260915-设计文档-GoGauge界面优化五项.md).

Part A (无浏览器, 直调 db/server):
- SVG MIME (需求1+2): _static_response 对 .svg 强制 image/svg+xml — Windows 注册表
  的 image/svg 会被 WebView2 <img> 拒绝渲染 (标题栏 logo/模型图标全空白);
- skip_welcome (需求3): settings 白名单 round-trip + /api/state 暴露该键;
- 渠道 tab 口径 (需求4/D1): list_channel_summary 排除 token 空账号行.

Part B (Playwright, 静态托管 app/web + API 拦截, 同 test_dsh_ui_playwright 模式):
- 欢迎页"不再提示"勾选 → PUT /api/settings; skip_welcome=true 时启动直达面板;
- stats 顶部远程区块 (D3) 与四个本地区块 (需求5) 无数据自动隐藏 + 空态兜底;
- SVG 图标在 <img> 中真实渲染 (naturalWidth > 0).
"""
from __future__ import annotations

import json
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app import db, server

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "app" / "web"


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库 (同 test_logout_server.tmp_db)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


# ---------------------------------------------------------------------------
# Part A: db / server 层
# ---------------------------------------------------------------------------

def test_static_svg_served_as_standard_mime(tmp_db):
    """静态 svg 响应 Content-Type 必为 image/svg+xml (与注册表值无关)."""
    host, port = server.start_server()
    try:
        base = f"http://{host}:{port}"
        for rel in ("/logo-final.svg", "/icons/glm.svg"):
            with urllib.request.urlopen(base + rel, timeout=5) as resp:
                assert resp.status == 200
                assert resp.headers["Content-Type"] == "image/svg+xml"
    finally:
        server.stop_server()


def test_channel_summary_excludes_logged_out_accounts(tmp_db):
    """D1 口径: token 空账号不产生渠道 tab; 本地渠道固定项不受影响."""
    db.add_account("tok-oc", "ws-oc")   # 默认 switch=True -> 活跃 opencode
    db.add_account("cookie-bai", "bai-u", switch=False, source="bai", dedupe_key="bai-u")
    channels = {c["channel"] for c in db.list_channel_summary()}
    assert {"opencode", "bai", "zcode", "claudecode"} <= channels

    db.clear_account()   # 退出登录活跃 opencode: 行与数据保留, 仅 token 置空
    channels = {c["channel"] for c in db.list_channel_summary()}
    assert "opencode" not in channels      # 无已登录 opencode 账号 = 无账户
    assert "bai" in channels               # 已登录 bai 保持显示 (统一口径)
    assert {"zcode", "claudecode"} <= channels   # 本地渠道固定显示


def test_save_settings_skip_welcome_roundtrip(tmp_db):
    """skip_welcome 白名单 round-trip; 旧库 merge 默认 False."""
    assert db.get_settings()["skip_welcome"] is False
    db.save_settings({"skip_welcome": True})
    assert db.get_settings()["skip_welcome"] is True
    db.save_settings({"skip_welcome": False})
    assert db.get_settings()["skip_welcome"] is False


class _FakeHandler:
    """仅提供 _handle_api 需要的 command (state 分支不读 body)."""

    def __init__(self, command="GET"):
        self.command = command


def _call_api(monkeypatch, handler, path) -> dict:
    captured: dict = {}
    monkeypatch.setattr(
        server, "_json_response",
        lambda h, data, status=200: captured.update({"data": data, "status": status}),
    )
    server._handle_api(handler, path, {})
    return captured


def test_api_state_exposes_skip_welcome(tmp_db, monkeypatch):
    """/api/state 携带 skip_welcome 且跟随 settings 变化 (前端显隐判断走 state)."""
    # 隔离本机 DSH/Codex 目录扫描 (只读但拖慢且环境相关)
    monkeypatch.setattr(server.dsh_api, "get_dsh_summary", lambda r: {"found": False})
    monkeypatch.setattr(server, "_codex_state_snapshot", lambda: {})

    resp = _call_api(monkeypatch, _FakeHandler("GET"), "/api/state")
    assert resp["data"]["skip_welcome"] is False

    db.save_settings({"skip_welcome": True})
    resp = _call_api(monkeypatch, _FakeHandler("GET"), "/api/state")
    assert resp["data"]["skip_welcome"] is True


# ---------------------------------------------------------------------------
# Part B: 浏览器层 (Playwright)
# ---------------------------------------------------------------------------

class _QuietStatic(SimpleHTTPRequestHandler):
    """静态托管 app/web; svg 修正为标准 MIME, 与 app/server.py 修复后行为一致."""

    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".svg": "image/svg+xml"}

    def log_message(self, _format, *args):  # pragma: no cover - fixture noise
        pass


@pytest.fixture(scope="module")
def web_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), partial(_QuietStatic, directory=str(WEB_ROOT)))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        thread.join(timeout=5)


class _UiFixture:
    """API 拦截: skip_welcome / accounts_logged_in / 本地渠道 found 可控."""

    def __init__(self, *, skip_welcome=False, accounts_logged_in=0, logged_in=False):
        self.skip_welcome = skip_welcome
        self.accounts_logged_in = accounts_logged_in
        self.logged_in = logged_in
        self.settings_puts: list[dict] = []

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/api/state":
            route.fulfill(content_type="application/json", body=json.dumps({
                "logged_in": self.logged_in, "accounts": [], "accounts_total": 0,
                "accounts_logged_in": self.accounts_logged_in, "skip_welcome": self.skip_welcome,
                "sync": {}, "progress": {}, "datadir": "fixture", "codex": {}, "dsh_found": False,
            }))
            return
        if path == "/api/dashboard":
            totals = {"total_tokens": 0, "total_input_tokens": 0, "total_output_tokens": 0,
                      "total_reasoning_tokens": 0, "total_cost_usd": 0, "request_count": 0,
                      "cache_hit_tokens": 0, "request_count_exact": True, "cost_available": True,
                      "hit_rate": 0, "uncached_input_tokens": 0, "session_count": 0}
            route.fulfill(content_type="application/json", body=json.dumps({
                "scope": "account", "logged_in": self.logged_in, "account": None, "account_name": "",
                "accounts_total": 0, "accounts_logged_in": self.accounts_logged_in,
                "quota": {"windows": []}, "totals": totals, "today": totals,
                "daily": [], "trend": [], "today_trend": [], "models": [],
                "sync": {}, "progress": {}, "range": "7d",
                "exchange_rate": {"usd_cny": 7, "currency": "CNY"}, "codex": {},
            }))
            return
        if path == "/api/settings" and request.method == "PUT":
            self.settings_puts.append(json.loads(request.post_data or "{}"))
            route.fulfill(content_type="application/json", body='{"ok": true}')
            return
        payload = {
            "/api/version": {"version": "fixture"},
            "/api/settings": {"auto_sync": False, "show_accounts_panel": False,
                              "skip_welcome": self.skip_welcome},
            "/api/zcode/quota": {},
            "/api/zcode/summary": {"db_found": False},
            "/api/claudecode/summary": {"db_found": False},
            "/api/codex/summary": {"db_found": False},
            "/api/dsh/usage": {"found": False},
            "/api/accounts": {"accounts": [], "active_id": None},
            "/api/accounts/overview": {"accounts": []},
            "/api/report/channels": {"rows": [], "summary": [], "dsh_status": {}},
        }
        if path in payload:
            route.fulfill(content_type="application/json", body=json.dumps(payload[path]))
            return
        route.fulfill(status=404, content_type="application/json", body='{"error":"fixture 404"}')


@pytest.fixture
def ui_browser_page(web_url):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    # 兼容既有 session 级 sync_playwright (test_theme_interactions): 其 dispatcher
    # greenlet 随 session fixture 挂起时线程 running-loop 标志残留, 会让本处
    # sync_playwright 误判 "在 loop 内" 拒绝启动 (全量运行 ERROR, 单文件不复现).
    # 该标志同时是其 session teardown 恢复泵送所必需, 故用完必须原样恢复.
    import asyncio

    leaked = None
    try:
        leaked = asyncio.get_running_loop()
        asyncio.events._set_running_loop(None)
    except RuntimeError:
        pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            context = browser.new_context(viewport={"width": 1280, "height": 840})
            page = context.new_page()
            page.set_default_timeout(5_000)
            try:
                yield page, web_url
            finally:
                context.close()
                browser.close()
    finally:
        if leaked is not None:
            asyncio.events._set_running_loop(leaked)   # 原样恢复, 供其 session teardown 泵送


def _open(page, web_url, fixture):
    page.route("**/api/**", fixture.handle)
    page.goto(web_url + "/")


def test_welcome_skip_checkbox_persists_setting(ui_browser_page):
    """欢迎页勾选"不再提示"→ PUT skip_welcome:true + toast 反馈."""
    page, web_url = ui_browser_page
    fixture = _UiFixture()   # 未登录/无本地数据/未跳过 -> 欢迎页显示
    _open(page, web_url, fixture)

    page.wait_for_selector("#login-overlay", state="visible")   # checkState 异步, 等显示

    page.check("#login-skip")
    # 静态托管无 theme seed 时 init 迁移会 PUT {"theme":"light"} (既有行为), 只断言本用例的 skip PUT
    skip_puts = [p for p in fixture.settings_puts if "skip_welcome" in p]
    assert skip_puts == [{"skip_welcome": True}]
    assert page.locator("#login-overlay").is_visible()   # 当前次仍停留欢迎页


def test_welcome_skipped_on_startup(ui_browser_page):
    """skip_welcome=true 时启动直达面板 (无欢迎页遮罩)."""
    page, web_url = ui_browser_page
    fixture = _UiFixture(skip_welcome=True)
    _open(page, web_url, fixture)

    page.wait_for_selector("#login-overlay", state="hidden")
    assert not page.locator("#login-overlay").is_visible()


def test_stats_sections_auto_hidden_without_any_usage(ui_browser_page):
    """无远程账号(D3)且四本地渠道未检测到: 顶部远程区块与本地区块全隐藏, 空态可见."""
    page, web_url = ui_browser_page
    fixture = _UiFixture(skip_welcome=True, accounts_logged_in=0)
    _open(page, web_url, fixture)

    page.locator('.side-item[data-page="stats"]').click()
    page.wait_for_selector("#stats-empty", state="visible")

    assert page.locator("#stats-total-cards").is_hidden()
    assert page.locator("#stats-detail6").is_hidden()
    assert page.locator(".card.detail6").is_hidden()
    assert page.locator("#mr-chart").is_hidden()
    assert page.locator("#trend-chart").is_hidden()
    for box_id in ("#zcode-stats", "#dsh-stats", "#claudecode-stats", "#codex-stats"):
        assert page.locator(box_id).is_hidden(), box_id
    assert page.locator("#stats-empty").is_visible()
    assert page.locator("#stats-empty").inner_text().strip() != ""


def test_stats_remote_sections_visible_with_logged_in_accounts(ui_browser_page):
    """有已登录远程账号: 顶部远程区块恢复显示 (D3 反向, 防隐藏后无法恢复)."""
    page, web_url = ui_browser_page
    fixture = _UiFixture(skip_welcome=True, accounts_logged_in=1, logged_in=True)
    _open(page, web_url, fixture)

    page.locator('.side-item[data-page="stats"]').click()
    page.wait_for_selector("#stats-total-cards", state="visible")
    assert page.locator(".card.detail6").is_visible()
    assert page.locator("#stats-empty").is_hidden()


def test_svg_images_render_in_img_context(ui_browser_page):
    """SVG 图标在 <img> 中真实渲染 (MIME 正确时 naturalWidth > 0)."""
    page, web_url = ui_browser_page
    fixture = _UiFixture(skip_welcome=True)
    _open(page, web_url, fixture)

    page.wait_for_selector(".tb-logo")
    width = page.evaluate("() => document.querySelector('.tb-logo').naturalWidth")
    assert width > 0
