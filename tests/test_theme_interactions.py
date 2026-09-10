"""主题交互执行级测试 (20260909 §5): Playwright + Chromium 实跑前端.

设施: ThreadingHTTPServer 伺服真实 app/web; /api/* 全部拦截 — 按前缀返回
非敏感 fixture, 未匹配路径 500 明拒; PUT /api/settings 记录请求体并可控失败/延迟.
不启动真实采集, 不用示例固定数据冒充用户真实运行结果.
缺浏览器时 skip (skip 不算通过, D4 必须实跑).
"""
from __future__ import annotations

import functools
import json
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api", reason="缺 playwright: pip install -r requirements-dev.txt && python -m playwright install chromium")
from playwright.sync_api import sync_playwright  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_WEB = _ROOT / "app" / "web"


def _fixture(path: str):
    p = path.split("?", 1)[0]
    table = {
        "/api/version": {"version": "0-test"},
        "/api/settings": {"sync_interval_sec": 300, "window_days": 60,
                          "auto_sync": True, "show_accounts_panel": False, "theme": None},
        "/api/state": {"logged_in": True, "progress": {"running": False}, "codex": {"running": False}},
        "/api/report/channels": {"rows": []},
        "/api/report/daily": {"labels": [], "series": {}},
        "/api/report/hourly": {"labels": [], "series": {}},
        "/api/report/windows": {"windows": []},
        "/api/accounts/overview": {"accounts": []},
        "/api/zcode/quota": {},
        "/api/dashboard": {"totals": {}},
        "/api/accounts": {"accounts": [], "active_id": None},
    }
    return table.get(p)


class _Handler(SimpleHTTPRequestHandler):
    api_log: list = []          # [(method, path, body_bytes|None)]
    fail_next_put = False
    version_delay_sec = 0.0

    def log_message(self, *args):
        pass

    @classmethod
    def reset(cls):
        cls.api_log = []
        cls.fail_next_put = False
        cls.version_delay_sec = 0.0

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/"):
            if self.path.startswith("/api/version") and type(self).version_delay_sec:
                time.sleep(type(self).version_delay_sec)
            type(self).api_log.append(("GET", self.path, None))
            fx = _fixture(self.path)
            if fx is None:
                self._json({"ok": False, "error": "rejected: " + self.path}, 500)   # 未覆盖 API 明拒
            else:
                self._json(fx)
            return
        super().do_GET()

    def do_PUT(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        type(self).api_log.append(("PUT", self.path, body))
        if self.path.startswith("/api/settings"):
            if type(self).fail_next_put:
                type(self).fail_next_put = False
                self._json({"ok": False, "error": "boom"}, 500)
                return
            self._json(json.loads(body or b"{}"))
            return
        self._json({"ok": False, "error": "rejected"}, 500)


@pytest.fixture
def web_server():
    _Handler.reset()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Handler, directory=str(_WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


def _puts():
    return [json.loads(body) for (m, p, body) in _Handler.api_log if m == "PUT" and p.startswith("/api/settings")]


def _gets():
    return [p for (m, p, _) in _Handler.api_log if m == "GET"]


def _wait_put(page, count, timeout=8000):
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if len(_puts()) >= count:
            return
        time.sleep(0.05)
    raise AssertionError(f"等待 {count} 次 settings PUT 超时, 实际 {len(_puts())}: {_puts()}")


# ---------------------------------------------------------------------------
# A. 持久化链路 (setThemePreference, Task 9 实现前本组失败)
# ---------------------------------------------------------------------------


def test_two_entries_share_one_persistence_path(web_server, browser):
    page = browser.new_page()
    page.goto(web_server)
    page.wait_for_selector("#tb-theme")
    page.click("#tb-theme")                                   # 顶栏入口
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    _wait_put(page, 1)
    assert _puts()[-1] == {"theme": "dark"}
    page.click('.side-item[data-page="settings"]')
    page.click('#set-theme-pills .pill[data-v="light"]')      # 设置页入口
    page.wait_for_function("document.documentElement.dataset.theme === 'light'")
    _wait_put(page, 2)
    assert _puts()[-1] == {"theme": "light"}
    page.close()


def test_rapid_toggle_persists_latest_intent(web_server, browser):
    page = browser.new_page()
    page.goto(web_server)
    page.wait_for_selector("#tb-theme")
    for _ in range(3):                                        # dark→light→dark 快速连点
        page.click("#tb-theme")
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    deadline = time.time() + 8
    while time.time() < deadline and (not _puts() or _puts()[-1] != {"theme": "dark"}):
        time.sleep(0.05)
    assert _puts() and _puts()[-1] == {"theme": "dark"}, f"最终持久化不是最新意图 dark: {_puts()}"
    page.close()


def test_failed_save_toasts_and_retries_once(web_server, browser):
    _Handler.fail_next_put = True
    page = browser.new_page()
    page.goto(web_server)
    page.wait_for_selector("#tb-theme")
    page.click("#tb-theme")
    _wait_put(page, 2)                                        # 首次失败 + 重试一次
    toast = page.wait_for_selector(".toast.err", timeout=8000)
    assert "主题未保存" in toast.inner_text()
    page.wait_for_selector(".toast.err", state="detached", timeout=8000)   # toast 仍按原定时删除
    page.close()


def test_theme_toggle_issues_no_business_requests(web_server, browser):
    page = browser.new_page()
    page.goto(web_server)
    page.wait_for_selector("#tb-theme")
    page.wait_for_load_state("networkidle")
    time.sleep(0.5)                                           # 等 init 各请求落定
    _Handler.api_log.clear()
    page.click("#tb-theme")
    _wait_put(page, 1)
    time.sleep(0.5)
    assert _gets() == [], f"切主题产生了额外业务 GET: {_gets()}"
    page.close()


def test_old_key_migrates_once_when_seed_unset(web_server, browser):
    ctx = browser.new_context()
    ctx.add_init_script("try{localStorage.setItem('gousage-dark','1')}catch(e){}")
    page = ctx.new_page()
    page.goto(web_server)                                     # 静态伺服无 seed 属性 → 按 unset
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")   # bootstrap 旧键即时生效
    _wait_put(page, 1)
    time.sleep(0.5)
    assert _puts() == [{"theme": "dark"}], f"迁移应只保存一次: {_puts()}"
    ctx.close()


def test_version_delay_does_not_reset_theme(web_server, browser):
    _Handler.version_delay_sec = 5.0
    ctx = browser.new_context()
    ctx.add_init_script("try{localStorage.setItem('gousage-dark','1')}catch(e){}")
    page = ctx.new_page()
    page.goto(web_server, wait_until="domcontentloaded")
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'", timeout=2000)
    page.close()
    ctx.close()
