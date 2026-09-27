"""自定义日期范围: Playwright 交互回归 (模式照 test_dsh_ui_playwright.py).

托管真实 app/web 静态资源 + 拦截全部 /api/*, 断言面板交互、请求参数形态、
偏好缓存与重启恢复 (doc/20260926 设计 §4, Review Focus #3/#4)。
"""
from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "app/web"


class _QuietStatic(SimpleHTTPRequestHandler):
    def log_message(self, _format, *args):  # pragma: no cover - test fixture noise
        pass


@pytest.fixture(scope="module")
def web_url():
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(_QuietStatic, directory=str(WEB_ROOT))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


class _ApiFixture:
    """记录 dashboard scope=all 的完整 query; 其余端点返回最小可用空态."""

    def __init__(self):
        self.dashboard_queries: list[dict[str, str]] = []

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        path = parsed.path
        if path == "/api/dashboard" and query.get("scope") == "all":
            self.dashboard_queries.append(query)
            route.fulfill(content_type="application/json", body=json.dumps({
                "scope": "all", "range": query.get("range", "today"),
                "totals": {"request_count": 1, "total_tokens": 1, "total_input_tokens": 0,
                           "total_output_tokens": 1, "total_reasoning_tokens": 0,
                           "total_cost_usd": 0, "request_count_exact": True, "cost_available": True},
                "today": {}, "dsh_status": {"found": False},
                "exchange_rate": {"usd_cny": 7, "currency": "CNY"}, "codex": {},
                "workbuddy_local": {"running": False, "error": ""}, "server_time": "2026-09-26 00:00:00",
            }))
            return
        if path == "/api/state":
            route.fulfill(content_type="application/json", body=json.dumps({
                "logged_in": True, "dsh_found": False, "progress": {}, "codex": {},
            }))
            return
        payload = {
            "/api/version": {"version": "fixture"},
            "/api/settings": {"auto_sync": False, "show_accounts_panel": False},
            "/api/zcode/quota": {},
            "/api/zcode/summary": {"db_found": False},
            "/api/claudecode/summary": {"db_found": False},
            "/api/codex/summary": {"db_found": False},
            "/api/workbuddy/summary": {"requests": 0, "credits": 0, "models": [], "daily": []},
            "/api/dsh/usage": {"found": False, "totals": {}, "total": {}, "today": {}},
            "/api/accounts/overview": {"accounts": []},
            "/api/report/channels": {"rows": [], "summary": [], "dsh_status": {}},
            "/api/report/windows": {"today": {}, "yesterday": {}, "7d": {}, "30d": {}, "channels": {},
                                    "compare": {}, "channel_count": 0, "account_count": 0,
                                    "dsh_status": {"found": False, "scanning": False, "stale": False,
                                                   "refresh_error": False, "updated_at": None,
                                                   "retry_after_seconds": 0}},
            "/api/report/daily": {"labels": [], "series": {}, "extra_rows": [], "dsh_status": {}},
        }
        body = payload.get(path, {"ok": True} if path.startswith("/api/") else {})
        route.fulfill(content_type="application/json", body=json.dumps(body))


@pytest.fixture
def browser_page(web_url):
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 840})
        page = context.new_page()
        page.set_default_timeout(5_000)
        fixture = _ApiFixture()
        page.route("**/api/**", fixture.handle)
        try:
            yield page, fixture, web_url
        finally:
            context.close()
            browser.close()


def test_custom_panel_open_close_and_apply(browser_page):
    page, fixture, web_url = browser_page
    page.goto(web_url)
    page.wait_for_selector("#home-pills .pill[data-r='custom']")
    # 场景 1: 面板开合
    page.click("#home-pills .pill[data-r='custom']")
    assert page.locator("#custom-range-panel").is_visible()
    page.keyboard.press("Escape")
    assert page.locator("#custom-range-panel").is_hidden()
    # 场景 2: 应用自定义范围 -> 请求带参 (Review Focus #3 附证), 无 &end
    page.click("#home-pills .pill[data-r='custom']")
    page.fill("#custom-start", "2026-09-20T08:00")
    page.click("#custom-apply")
    assert page.locator("#custom-range-panel").is_hidden()
    page.wait_for_function("() => document.querySelectorAll('#home-pills .pill.active').length === 1")
    pill = page.locator("#home-pills .pill[data-r='custom']")
    assert "active" in (pill.get_attribute("class") or "")
    assert "09-20 08:00~" in pill.inner_text() and "现在" in pill.inner_text()   # end 空: 摘要显式标注 ~现在
    page.wait_for_timeout(300)
    custom_q = [q for q in fixture.dashboard_queries if q.get("range") == "custom"]
    assert custom_q, fixture.dashboard_queries
    assert custom_q[-1]["start"] == "2026-09-20T08:00"
    assert "end" not in custom_q[-1]


def test_custom_clear_restores_default(browser_page):
    page, fixture, web_url = browser_page
    page.goto(web_url)
    page.wait_for_selector("#home-pills .pill[data-r='custom']")
    page.click("#home-pills .pill[data-r='custom']")
    page.fill("#custom-start", "2026-09-20T08:00")
    page.click("#custom-apply")
    page.wait_for_timeout(200)
    # 场景 3: 清除 -> 回默认档 today, 偏好同步
    page.click("#home-pills .pill[data-r='custom']")
    page.click("#custom-clear")
    assert "active" in (page.locator("#home-pills .pill[data-r='today']").get_attribute("class") or "")
    pref = page.evaluate("() => JSON.parse(localStorage.getItem('gousage-home-range'))")
    assert pref["mode"] == "today"
    assert pref["custom"]["start"] == "2026-09-20T08:00"   # 值保留, 便于切回


def test_custom_pref_survives_reload_and_corrupt_falls_back(browser_page):
    page, fixture, web_url = browser_page
    page.goto(web_url)
    page.wait_for_selector("#home-pills .pill[data-r='custom']")
    page.click("#home-pills .pill[data-r='custom']")
    page.fill("#custom-start", "2026-09-20T08:00")
    page.fill("#custom-end", "2026-09-21T09:30")
    page.click("#custom-apply")
    page.wait_for_timeout(200)
    # 场景 4a: 重载完整恢复 (Review Focus #4)
    page.reload()
    page.wait_for_selector("#home-pills .pill[data-r='custom']")
    pill = page.locator("#home-pills .pill[data-r='custom']")
    assert "active" in (pill.get_attribute("class") or "")
    assert "09-20 08:00~09-21 09:30" in pill.inner_text()
    # 场景 4b: 损坏 JSON -> 回默认档不白屏
    page.evaluate("() => localStorage.setItem('gousage-home-range', '{bad')")
    page.reload()
    page.wait_for_selector("#home-pills .pill[data-r='today']")
    assert "active" in (page.locator("#home-pills .pill[data-r='today']").get_attribute("class") or "")
