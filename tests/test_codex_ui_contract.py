from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class Nodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.keys = set()
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if "data-i18n" in a:
            self.keys.add(a["data-i18n"])

def test_codex_stats_nodes():
    p = Nodes()
    p.feed((ROOT / "app/web/index.html").read_text(encoding="utf-8"))
    expected = {"codex-stats", "codex-kpis", "codex-today-kpis",
                "codex-prov-head", "codex-prov-body", "codex-model-head",
                "codex-model-body", "codex-trend-chart", "codex-missing", "codex-error"}
    assert expected <= p.ids
    assert "codexStatsTitle" in p.keys


def test_home_has_range_totals_and_codex_color():
    p = Nodes()
    p.feed((ROOT / "app/web/index.html").read_text(encoding="utf-8"))
    assert {"report-range-kpis", "channel-tabs", "report-table"} <= p.ids
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/web/style.css").read_text(encoding="utf-8")
    assert 'codex: "var(--ch-codex)"' in js
    assert "--ch-codex:" in css
