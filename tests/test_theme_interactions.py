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
    fail_puts_remaining = 0     # 连续失败计数 (评审回归: 复现"首试+重试双失败"让 retried 残留)
    version_delay_sec = 0.0

    def log_message(self, *args):
        pass

    @classmethod
    def reset(cls):
        cls.api_log = []
        cls.fail_next_put = False
        cls.fail_puts_remaining = 0
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
            if type(self).fail_puts_remaining > 0:
                type(self).fail_puts_remaining -= 1
                self._json({"ok": False, "error": "boom"}, 500)
                return
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


def test_each_new_intent_gets_fresh_retry_budget(web_server, browser):
    """评审回归 (20260910): retried 不得跨意图残留 — 每个新意图首试失败都必须重试一次.

    复现条件: 第一轮"首试+重试"双失败后 retried 残留 true;
    第二轮意图首试失败时, 缺陷形态下被静默吞掉 (累计仅 3 次 PUT, 本用例等第 4 次超时).
    注意: fail_next_put(失败一次即恢复)无法复现 — 首轮重试成功会把 retried 重置回 false
    (已用 Node 仿真证实), 所以先在 Step 1a 加 fail_puts_remaining 设施.
    """
    page = browser.new_page()
    page.goto(web_server)
    page.wait_for_selector("#tb-theme")
    page.wait_for_load_state("networkidle")   # 等 init 迁移 PUT 落定, 防其垫高计数器
    time.sleep(0.5)
    _Handler.api_log.clear()
    _Handler.fail_puts_remaining = 2       # 第一轮意图: 首试+重试双失败 -> retried 残留 true
    page.click("#tb-theme")
    _wait_put(page, 2)
    time.sleep(0.3)
    _Handler.fail_next_put = True          # 第二轮意图: 修复后应 toast+重试成功 (累计 4 次 PUT)
    page.click("#tb-theme")
    _wait_put(page, 4)
    assert _puts()[-1] == {"theme": "light"}
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


# ---------------------------------------------------------------------------
# B. 图表主题与视觉行为 (Task 11/12 实现前本组大部分失败)
# ---------------------------------------------------------------------------

_CHART_BUILDERS = """
window.__built = [];
function reg(name, inst) { window.__built.push([name, inst]); return inst; }
reg('cToday', (chartToday([{hour:'00',input:5,output:3}], true), cToday));
reg('cModel', (chartModel([{model:'gpt-5',uncached_input_tokens:10,total_output_tokens:5,total_cost_usd:0.01,request_count:3,hit_rate:50}], true), cModel));
reg('cTrend', (chartTrend([{date:'2026-09-01',total_cost_usd:1,request_count:2,total_input_tokens:3,total_output_tokens:4,total_reasoning_tokens:5}], true), cTrend));
reg('cZcodeTrend', (chartZcodeTrend([{date:'2026-09-01',total_input_tokens:1,total_output_tokens:1,total_reasoning_tokens:1,total_cost_usd:0.5}], true), cZcodeTrend));
reg('cClaudecodeTrend', (chartClaudecodeTrend([{date:'2026-09-01',total_tokens:3,total_cost_usd:0.5}], true), cClaudecodeTrend));
reg('cCodexTrend', (chartCodexTrend([{date:'2026-09-01',total_tokens:3,request_count:2}], true), cCodexTrend));
reg('cOvTrendChart', (chartOvTrend([{daily7:[{date:'2026-09-01',total_cost_usd:1,request_count:1,total_input_tokens:1,total_output_tokens:1,total_reasoning_tokens:1}]}], true), cOvTrendChart));
reg('cStack', (chartReportStack({labels:['2026-09-01'],series:{zcode:[5]},metric:'tokens'}, true), cStack));
reg('cDonut', (chartReportDonut({labels:['2026-09-01'],series:{zcode:[5]},metric:'tokens'}, true), cDonut));
reg('cHourly', (chartReportHourly({labels:[0],series:{zcode:[5]}}, true, 'noDataInRange'), cHourly));
window.__built.length;
"""


def _expected_palette(page):
    return page.evaluate("""() => {
      const cs = getComputedStyle(document.body);
      const v = (n) => cs.getPropertyValue(n).trim();
      return { input: v('--chart-input'), output: v('--chart-output'), extra: v('--chart-extra'),
               tooltipBg: v('--chart-tooltip-bg'), tooltipText: v('--chart-tooltip-text'),
               tooltipBorder: v('--chart-tooltip-border') };
    }""")


def test_ten_charts_use_theme_palette_and_tooltip(web_server, browser):
    ctx = browser.new_context()
    ctx.add_init_script("try{localStorage.setItem('gousage-dark','1')}catch(e){}")
    page = ctx.new_page()
    page.goto(web_server)
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    page.wait_for_load_state("networkidle")   # 等 init/loadReportAll 落定, 防迟到空数据重绘销毁已建实例
    exp = _expected_palette(page)
    assert page.evaluate(_CHART_BUILDERS) == 10
    report = page.evaluate("""() => window.__built.map(([name, c]) => ({
      name,
      firstBg: Array.isArray(c.data.datasets[0].backgroundColor) ? c.data.datasets[0].backgroundColor[0] : (c.data.datasets[0].backgroundColor || c.data.datasets[0].borderColor || null),
      tooltipBg: c.options.plugins.tooltip && c.options.plugins.tooltip.backgroundColor || null,
      tooltipText: c.options.plugins.tooltip && c.options.plugins.tooltip.bodyColor || null,
      anim: c.options.animation === undefined ? 'default' : c.options.animation,
      callbacksKept: !!(c.options.plugins.tooltip && c.options.plugins.tooltip.callbacks),
    }))""")
    by_name = {r["name"]: r for r in report}
    # 指标色: chartToday 首系列 = --chart-input
    assert by_name["cToday"]["firstBg"] == exp["input"]
    # 模型环第六色 = --chart-extra ( palette[5] )
    model_palette = page.evaluate("cModel.data.datasets[0].backgroundColor")
    assert model_palette[5] == exp["extra"]
    # 十图 tooltip 底色/文字色全部来自变量 (保留既有 callbacks 的图不得丢)
    with_callbacks = {"cModel", "cTrend", "cZcodeTrend", "cClaudecodeTrend", "cCodexTrend", "cOvTrendChart"}
    for name, r in by_name.items():
        assert r["tooltipBg"] == exp["tooltipBg"], f"{name} tooltip 底色未走主题变量"
        assert r["tooltipText"] == exp["tooltipText"], f"{name} tooltip 文字色未走主题变量"
        assert r["anim"] is False, f"{name} noAnim 被破坏"
        if name in with_callbacks:
            assert r["callbacksKept"], f"{name} 丢失了既有 tooltip callbacks"
    ctx.close()


def test_hidden_page_chart_uses_current_theme(web_server, browser):
    ctx = browser.new_context()
    ctx.add_init_script("try{localStorage.setItem('gousage-dark','1')}catch(e){}")
    page = ctx.new_page()
    page.goto(web_server)
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    page.wait_for_load_state("networkidle")   # 先等首页加载链落定
    page.evaluate("switchPage('stats')")
    exp = _expected_palette(page)
    # 单次 evaluate 原子完成建图+读色, 防 switchPage 触发的异步 loadDashboard 穿插覆盖 cTrend
    first = page.evaluate("""() => {
      chartTrend([{date:'2026-09-01',total_cost_usd:1,request_count:2,total_input_tokens:3,total_output_tokens:4,total_reasoning_tokens:5}], true);
      return cTrend.data.datasets[0].borderColor;
    }""")
    assert first == exp["input"], "进入隐藏页后绘制的图表未按当前主题取色"
    ctx.close()


def test_icons_swap_in_place_on_theme_toggle(web_server, browser):
    page = browser.new_page()
    page.goto(web_server)
    page.wait_for_selector("#tb-theme")
    page.evaluate("""() => {
      const body = document.getElementById('records-body');
      body.innerHTML = '<img alt="gpt" src="icons/gpt.svg">';
    }""")
    expected_dark = page.evaluate("themedName('gpt', true)")
    page.click("#tb-theme")
    page.wait_for_function("document.documentElement.dataset.theme === 'dark'")
    src = page.get_attribute("#records-body img", "src")
    assert expected_dark in src, f"图标未原地换成深色变体: {src}"
    page.close()


def test_reduced_motion_toast_still_removed(web_server, browser):
    ctx = browser.new_context(reduced_motion="reduce")
    page = ctx.new_page()
    page.goto(web_server)
    page.wait_for_selector("#tb-theme")
    page.evaluate("toast('probe', 'err')")
    page.wait_for_selector(".toast.err", state="detached", timeout=6000)   # 定时删除不依赖动画
    ctx.close()


def test_sparkline_uses_css_var_not_snapshot(web_server, browser):
    page = browser.new_page()
    page.goto(web_server)
    page.wait_for_selector("#tb-theme")
    svg = page.evaluate("sparklineSvg([1, 3, 2], 'var(--account-1)')")
    assert 'style="stroke:var(--account-1)"' in svg, "sparkline 未用 CSS var (缓存一次性颜色快照)"
    assert 'style="fill:var(--account-1)"' in svg
    page.close()
