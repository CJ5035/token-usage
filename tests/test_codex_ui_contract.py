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


def test_data_since_column_uses_real_dsh_ranges():
    """DSH rows expose their actual range data_since; the old today-only label is gone."""
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert 'data-i18n="dataSince"' in html
    assert 'data-i18n-title="dataSinceTip"' in html
    assert 'dataSinceToday' not in js
    assert "r.data_since ||" in js
    assert "renderChannelTable(rows.rows, rows.summary)" in js


def test_codex_summary_renders_only_range_row():
    """20260911 问题2: 今日行 (data.today) 不再渲染, KPI 仅所选范围口径一行;
    DOM 契约保留 #codex-today-kpis (恒隐藏, 见 test_codex_stats_nodes)。

    断言2 必须锚定"显示路径"那一次赋值: 函数内早退分支 (db_found === false) 本就含
    同一句 `todayKpis.hidden = true;`, 仅用 `in body` 无法区分"显示路径置 true"与
    "显示路径整行被删" —— 后者会让 #codex-today-kpis 空着却可见 (hidden 默认 false,
    index.html 未声明 hidden), 故按早退 return 之后的正尾段计数。
    """
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    start = js.index("function renderCodexSummary(")
    body = js[start:js.index("\n}", start)]
    assert "cards(data.today" not in body        # 今日行不再取数渲染
    assert "todayKpis.hidden = false" not in body
    # 早退分支之后即显示路径正尾段, 其中必须恰好有一次 `todayKpis.hidden = true;`
    tail = body[body.index("if (cCodexTrend) { cCodexTrend.destroy(); cCodexTrend = null; }"):]
    assert tail.count("todayKpis.hidden = true;") == 1
