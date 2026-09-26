"""自定义范围: 前端源码契约 (DOM/i18n/缓存/helper 存在性), 模式照 test_dsh_ui_contract.py."""
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
HTML = (ROOT / "app/web/index.html").read_text(encoding="utf-8")


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        node = dict(attrs)
        if "id" in node:
            self.ids.add(node["id"])


def test_custom_range_dom_contract():
    nodes = _Ids()
    nodes.feed(HTML)
    assert {"custom-range-panel", "custom-start", "custom-end",
            "custom-apply", "custom-clear"} <= nodes.ids
    assert HTML.count('data-r="custom"') == 2          # 两页各一个自定义 pill
    assert 'type="datetime-local"' in HTML and 'step="1"' in HTML


def test_custom_range_i18n_both_langs():
    for key in ("customRange", "rangeStart", "rangeEnd", "rangeApply",
                "rangeClear", "endEmptyMeansNow", "rangeInvalid"):
        assert f"{key}:" in JS                            # zh 与 en 字典内各出现 >=2 次
        assert JS.count(f"{key}:") >= 2


def test_custom_range_state_and_helpers_exist():
    assert "rangeCustom:" in JS and "statsCustom:" in JS
    for fn in ("function rangeQuery(", "function saveRangePref(",
               "function restoreRangePref(", "function customRangeSummary(",
               "function syncRangePills("):
        assert fn in JS
    assert "gousage-home-range" in JS and "gousage-stats-range" in JS


def test_restore_pref_tolerates_corrupt_storage():
    """Review Focus #4: 恢复逻辑必须 try/catch + mode 校验 + start 可解析校验."""
    frag = JS.split("function restoreRangePref")[1][:2200]
    assert "JSON.parse" in frag and "catch" in frag and '"custom"' in frag and "mode" in frag


# ---------- rangeQuery 调用点与 DSH 键 (Task 10) ----------

def test_range_query_helper_and_call_sites():
    body = JS.split("function rangeQuery(")[1].split("\n}")[0]
    assert "encodeURIComponent" in body and '"custom"' in body
    # 10 处调用点全部改走 rangeQuery (不再手拼 ?range=${...})
    assert JS.count("rangeQuery(") >= 11          # 定义 1 + 调用 10
    for stale in ("`/api/report/channel-overview?range=${range}",
                  "`/api/dashboard?range=${range}`",
                  "`/api/zcode/summary?range=${state.statsRange}`",
                  "`/api/claudecode/summary?range=${state.statsRange}`"):
        assert stale not in JS                    # 旧拼串必须清零


def test_dsh_custom_range_cache_key():
    """Review Focus #3: DSH 请求去重键与缓存判等必须并入 start/end."""
    assert "dshRangeKey" in JS
    assert JS.count("dshUsageLast.range ===") == 0
    assert "dshUsageLast.key" in JS
