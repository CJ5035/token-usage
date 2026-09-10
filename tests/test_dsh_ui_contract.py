from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _Nodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        node = dict(attrs)
        if "id" in node:
            self.ids.add(node["id"])


def test_dsh_range_ui_contract():
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    nodes = _Nodes()
    nodes.feed(html)

    assert {"dsh-kpis", "dsh-status", "dsh-error", "dsh-trend-chart", "dsh-trend-empty"} <= nodes.ids
    assert "dsh-dim" not in html
    for stale in ("dshDim", "dsh-today-note", "dataSinceToday"):
        assert stale not in js
    assert '"/api/dsh/usage?range=" + encodeURIComponent(range)' in js
    assert "if (range !== state.statsRange || !dshStatsVisible()) return;" in js


def test_dsh_chart_and_status_use_cached_range_data():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    for key in ("dshStatusScanning", "dshStatusStale", "dshRefreshError", "dshDiagnostics", "dshKpiAvgTps"):
        assert js.count(key) >= 2
    assert "function chartDshTrend" in js
    assert "function destroyDshTrend" in js
    assert "safeResize(cDshTrend)" in js
    assert "dshUsageLast.range === state.statsRange" in js
    assert "fmtTps(totals.tps)" in js


def test_dsh_refresh_scheduler_and_transport_error_contract():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    for marker in (
        "let dshTransportError = null;",
        "let dshRefreshTimer = null;",
        "function scheduleDshRefresh(data)",
        "function cancelDshRefresh()",
        "function renderDshTransportError()",
        "for (const controller of dshRequestControllers.values()) controller.abort();",
        "data.refresh_error",
        "data.scanning",
        "renderDshError(data);",
        "else if (dshTransportError && dshTransportError.range === state.statsRange) renderDshTransportError();",
    ):
        assert marker in js
    assert "box.hidden = false;" in js
    assert "if (state.page === \"stats\" && page !== \"stats\") { destroyDshTrend(); cancelDshRefresh(); }" in js


def test_hanging_dsh_request_times_out_and_allows_same_range_retry():
    """The DSH-specific AbortController retains the 20s API timeout guarantee."""
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert "const DSH_REQUEST_TIMEOUT_MS = 20_000;" in js
    assert "const timeoutId = setTimeout(() => { timedOut = true; controller.abort(); }, DSH_REQUEST_TIMEOUT_MS);" in js
    assert "controller.signal.aborted && !timedOut" in js
    assert "clearTimeout(timeoutId);" in js
    assert "const dshRequestControllers = new Map();" in js
    assert "dshRequestControllers.has(range)" in js


def test_dsh_unknown_home_values_and_data_since_are_safe():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert 'isDsh ? dshUnavailableCell("dshRequestsUnavailable")' in js
    assert 'isDsh ? dshUnavailableCell("dshCostUnavailable")' in js
    assert "escapeHtml(r.data_since ||" in js
