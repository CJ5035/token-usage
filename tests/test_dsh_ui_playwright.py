"""Executable browser regression coverage for the DSH stats card.

The fixture serves the real ``app/web`` assets and intercepts every API request,
so range/lifecycle assertions exercise the shipped browser code without a login
or local DSH data dependency.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "app" / "web"


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


def _bucket(tokens: int, *, tps: float | None = 10.0) -> dict:
    output = tokens - 200 if tokens >= 200 else tokens
    return {
        "steps": 2 if tokens else 0,
        "input": tokens - output,
        "cache": 0,
        "cache_read": 0,
        "cache_write": 0,
        "output": output,
        "reasoning": 0,
        "tokens": tokens,
        "seconds": output / tps if tps and output else 0.0,
        "tps": tps if output and tps else None,
    }


def _dsh_summary(range_: str, *, scanning: bool = False) -> dict:
    tokens = {"today": 0, "7d": 700, "30d": 3000, "all": 999}.get(range_, 0)
    totals = _bucket(tokens, tps=None if range_ == "all" else 10.0)
    today = date.today().isoformat()
    hourly = [{"hour": hour, **_bucket(0)} for hour in range(24)]
    if tokens:
        hourly[10] = {"hour": 10, **totals}
    return {
        "found": True,
        "range": range_, "totals": totals, "total": totals, "today": _bucket(0),
        "providers": ([{"provider": "fixture-" + "x" * 120, **totals}] if tokens else []),
        "models": ([{"provider": "fixture-" + "x" * 120, "model": "fixture-model-" + "y" * 120, **totals}] if tokens else []),
        "trend": ([{"date": today, **totals}] if tokens else []),
        "hourly": hourly if range_ in {"today", "yesterday"} else [],
        "sessions_count": 2 if tokens else 0,
        "data_since": today if tokens else None,
        "scanning": scanning, "stale": scanning, "refresh_error": False,
        "updated_at": "2026-09-10T12:00:00", "retry_after_seconds": 0,
        "undated": 0, "future": 0, "provisional_steps": 0, "unkeyed_steps": 0,
    }


def _dashboard(local_only: bool = False) -> dict:
    totals = {
        "total_tokens": 1, "total_input_tokens": 0, "total_output_tokens": 1,
        "total_reasoning_tokens": 0, "total_cost_usd": 0, "request_count": 1,
        "cache_hit_tokens": 0, "request_count_exact": True, "cost_available": True,
    }
    payload = {
        "logged_in": True, "account": {"source": "opencode"}, "account_name": "fixture",
        "quota": {"windows": []}, "totals": totals, "today": totals,
        "today_trend": [], "trend": [], "models": [], "sync": {}, "progress": {},
        "codex": {}, "exchange_rate": {"usd_cny": 7, "currency": "CNY"},
    }
    if local_only:
        return {"scope": "all", "range": "today", "totals": totals, "today": totals,
                "dsh_status": {"found": True}, "exchange_rate": {"usd_cny": 7, "currency": "CNY"}}
    return payload


class _ApiFixture:
    def __init__(self):
        self.dsh_calls: list[str] = []
        self.dashboard_ranges: list[str] = []
        self.scanning_ranges: set[str] = set()
        self.fail_ranges: set[str] = set()
        self.held_ranges: set[str] = set()
        self.held_routes: dict[str, list] = {}
        self.local_only = False

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        query = parse_qs(parsed.query)
        path = parsed.path
        if path == "/api/dsh/usage":
            range_ = query.get("range", ["all"])[0]
            self.dsh_calls.append(range_)
            if range_ in self.held_ranges:
                self.held_routes.setdefault(range_, []).append(route)
                return
            if range_ in self.fail_ranges:
                route.fulfill(status=500, content_type="application/json", body='{"error":"fixture failure"}')
                return
            route.fulfill(content_type="application/json", body=json.dumps(
                _dsh_summary(range_, scanning=range_ in self.scanning_ranges)
            ))
            return
        if path == "/api/state":
            route.fulfill(content_type="application/json", body=json.dumps({
                "logged_in": not self.local_only, "dsh_found": self.local_only,
                "progress": {}, "codex": {},
            }))
            return
        if path == "/api/dashboard":
            self.dashboard_ranges.append(query.get("range", ["today"])[0])
            route.fulfill(content_type="application/json", body=json.dumps(_dashboard(self.local_only)))
            return
        payload = {
            "/api/version": {"version": "fixture"},
            "/api/settings": {"auto_sync": False, "show_accounts_panel": False},
            "/api/zcode/quota": {},
            "/api/zcode/summary": {"db_found": False},
            "/api/claudecode/summary": {"db_found": False},
            "/api/codex/summary": {"db_found": False},
            "/api/accounts/overview": {"accounts": []},
            "/api/report/channels": {"rows": [], "summary": [], "dsh_status": {}},
            "/api/report/windows": {"today": {}, "yesterday": {}, "7d": {}, "30d": {}, "channels": {}, "compare": {}, "channel_count": 0, "account_count": 0},
            "/api/report/daily": {"labels": [], "series": {}, "granularity": "day", "unavailable_channels": []},
            "/api/report/hourly": {"buckets": [], "series": {}},
        }.get(path, {})
        route.fulfill(content_type="application/json", body=json.dumps(payload))

    def release(self, range_: str):
        for route in self.held_routes.pop(range_, []):
            route.fulfill(content_type="application/json", body=json.dumps(_dsh_summary(range_)))


def _open_stats(page, url):
    page.goto(url)
    page.locator('.side-item[data-page="stats"]').click()
    page.locator("#dsh-stats").wait_for(state="visible")
    page.locator("#dsh-kpis").wait_for()


def test_dsh_real_page_ranges_race_states_and_tooltip(browser_page):
    page, fixture, url = browser_page
    _open_stats(page, url)

    stats_ranges = page.locator("#stats-pills .pill")
    assert stats_ranges.count() == 4
    for index in range(stats_ranges.count()):
        pill = stats_ranges.nth(index)
        range_ = pill.get_attribute("data-r")
        pill.click()
        page.wait_for_timeout(60)
        assert range_ in fixture.dsh_calls

    home_ranges = page.locator("#home-pills .pill")
    assert home_ranges.count() == 5
    page.locator('.side-item[data-page="home"]').click()
    for index in range(home_ranges.count()):
        pill = home_ranges.nth(index)
        range_ = pill.get_attribute("data-r")
        pill.click()
        page.wait_for_timeout(30)
        assert range_ in fixture.dashboard_ranges

    _open_stats(page, url)
    page.locator('#stats-pills .pill[data-r="today"]').click()
    fixture.held_ranges.add("7d")
    page.locator('#stats-pills .pill[data-r="7d"]').click()
    for _ in range(20):
        if fixture.held_routes.get("7d"):
            break
        page.wait_for_timeout(20)
    assert fixture.held_routes["7d"]
    page.locator('#stats-pills .pill[data-r="30d"]').click()
    page.locator("#dsh-kpis").filter(has_text="3.0k").wait_for()
    assert "3.0k" in page.locator("#dsh-kpis").inner_text()
    fixture.held_ranges.remove("7d")
    fixture.release("7d")
    page.wait_for_timeout(80)
    assert "3.0k" in page.locator("#dsh-kpis").inner_text()

    fixture.scanning_ranges.add("7d")
    page.locator('#stats-pills .pill[data-r="7d"]').click()
    page.locator("#dsh-status").filter(has_text="扫描").wait_for()

    fixture.fail_ranges.add("30d")
    page.locator('#stats-pills .pill[data-r="30d"]').click()
    page.locator("#dsh-error").filter(has_text="刷新失败").wait_for()

    page.locator('#stats-pills .pill[data-r="today"]').click()
    page.locator("#dsh-kpis").filter(has_text="0").wait_for()
    assert "—" in page.locator("#dsh-kpis").inner_text()

    page.locator('#stats-pills .pill[data-r="all"]').click()
    page.locator("#dsh-kpis").filter(has_text="999").wait_for()
    assert "—" in page.locator("#dsh-kpis").inner_text()
    assert "799" in page.locator("#dsh-prov-body").inner_text()
    page.locator("#dsh-trend-chart").scroll_into_view_if_needed()
    tooltip_point = page.evaluate("""() => {
      const canvas = document.querySelector('#dsh-trend-chart');
      const chart = Chart.getChart(canvas);
      const point = chart.getDatasetMeta(1).data[0];
      const rect = canvas.getBoundingClientRect();
      return { x: rect.left + point.x * rect.width / canvas.width,
               y: rect.top + point.y * rect.height / canvas.height };
    }""")
    page.mouse.move(tooltip_point["x"], tooltip_point["y"])
    page.wait_for_timeout(30)
    chart = page.evaluate("""() => {
      const c = Chart.getChart(document.querySelector('#dsh-trend-chart'));
      return c && {
        labels: c.data.labels,
        opacity: c.tooltip.opacity,
        title: c.tooltip.title,
        values: (c.tooltip.dataPoints || []).map((point) => point.formattedValue),
      };
    }""")
    assert chart["labels"] == [date.today().isoformat()[5:]]
    assert chart["opacity"] > 0
    assert chart["title"] == [date.today().isoformat()]
    assert "799" in chart["values"]


def test_dsh_local_mode_theme_language_hidden_lifecycle_and_narrow_layout(browser_page):
    page, fixture, url = browser_page
    fixture.local_only = True
    _open_stats(page, url)
    assert page.locator("#login-overlay").is_hidden()

    fixture.scanning_ranges.add("7d")
    page.locator('#stats-pills .pill[data-r="7d"]').click()
    page.locator("#dsh-status").wait_for(state="visible")
    before_preferences = len(fixture.dsh_calls)
    before_chart = page.evaluate("Chart.getChart(document.querySelector('#dsh-trend-chart')).options.plugins.title.text")
    page.evaluate("applyLang('en'); setThemePreference(true)")
    assert page.locator("#dsh-stats h3").inner_text() == "DSH Local Usage"
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    assert page.evaluate("Chart.getChart(document.querySelector('#dsh-trend-chart')).options.plugins.title.text") != before_chart
    assert len(fixture.dsh_calls) == before_preferences

    fixture.held_ranges.add("7d")
    page.locator('#stats-pills .pill[data-r="all"]').click()
    page.locator('#stats-pills .pill[data-r="7d"]').click()
    for _ in range(20):
        if fixture.held_routes.get("7d"):
            break
        page.wait_for_timeout(20)
    assert fixture.held_routes["7d"]
    before_hide = len(fixture.dsh_calls)
    assert page.evaluate("!!Chart.getChart(document.querySelector('#dsh-trend-chart'))")
    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    page.wait_for_timeout(1700)
    assert len(fixture.dsh_calls) == before_hide
    assert not page.evaluate("!!Chart.getChart(document.querySelector('#dsh-trend-chart'))")
    page.evaluate("""() => {
      Object.defineProperty(document, 'hidden', {configurable: true, get: () => false});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    page.wait_for_timeout(80)
    assert len(fixture.dsh_calls) == before_hide + 1
    fixture.held_ranges.remove("7d")
    fixture.release("7d")
    page.locator("#dsh-kpis").wait_for()
    assert page.evaluate("!!Chart.getChart(document.querySelector('#dsh-trend-chart'))")
    for width, height in ((1280, 840), (900, 700)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(300)
        dimensions = page.evaluate("""() => ({
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: window.innerWidth,
          tableWidth: document.querySelector('#dsh-tables').scrollWidth,
          tableClientWidth: document.querySelector('#dsh-tables').clientWidth,
          overflowX: getComputedStyle(document.querySelector('#dsh-tables')).overflowX,
        })""")
        assert dimensions["documentWidth"] <= dimensions["viewportWidth"], dimensions
        assert dimensions["overflowX"] in {"auto", "scroll"}, dimensions
        if width == 900:
            assert dimensions["tableWidth"] > dimensions["tableClientWidth"], dimensions
            assert page.evaluate("""() => {
              const tables = document.querySelector('#dsh-tables');
              tables.scrollLeft = 80;
              return tables.scrollLeft;
            }""") > 0
