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
    assert "seq !== dshSumSeq || range !== state.statsRange" in js


def test_dsh_chart_and_status_use_cached_range_data():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    for key in ("dshStatusScanning", "dshStatusStale", "dshRefreshError", "dshDiagnostics", "dshKpiAvgTps"):
        assert js.count(key) >= 2
    assert "function chartDshTrend" in js
    assert "function destroyDshTrend" in js
    assert "safeResize(cDshTrend)" in js
    assert "dshUsageLast.range === state.statsRange" in js
    assert "fmtTps(totals.tps)" in js
