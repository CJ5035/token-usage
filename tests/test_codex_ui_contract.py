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


def test_copy_and_local_entry_contract():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    p = Nodes()
    p.feed(html)
    assert {"introText", "welcomeDesc", "pageFoot"} <= p.keys
    assert "function canUseLocalCodex(" in js
    for path in ("README.md", "README_en.md"):
        assert "GOUSAGE_CODEX_HOME" in (ROOT / path).read_text(encoding="utf-8")


def test_data_since_column_copy_clarified():
    """「数据自」歧义修复: 列头改「数据起点」并带 data-i18n-title tooltip (诊断 doc/bug-diagnosis-today-trend-20260907.md)."""
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert 'data-i18n="dataSince"' in html
    assert 'data-i18n-title="dataSinceTip">数据起点</th>' in html
    assert 'dataSince: "数据起点"' in js
    assert 'dataSince: "Data start"' in js
    assert 'dataSinceTip: "该渠道本地最早记录日期（历史覆盖起点），不随上方时间范围变化；「仅今日」表示该渠道无历史数据"' in js
    assert 'dataSinceTip: "Earliest local record date of this channel (history coverage start), unaffected by the range selector; \'Today only\' means the channel has no history yet"' in js
    assert 'unusedChannelsHint: "本范围无用量渠道：{chs}"' in js
    assert 'unusedChannelsHint: "No usage in this range: {chs}"' in js
    assert "renderChannelTable(rows.rows, rows.summary)" in js
