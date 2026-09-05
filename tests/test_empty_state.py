"""EVOLUTION-7 空态策略统一回归测试 (doc/20260906-evolution-plan-7.md §1.4).

测试模式沿用项目先例: test_theme_rerender / test_dark_theme 的源码静态断言
(前端无 DOM 自动化设施) + test_report_api 的 server 层 dsh mock 手法.

5 组断言:
1. 空守卫源码断言: 6 个图函数 (stack/donut/hourly/chartTrend/chartOvTrend/chartToday)
   各自含「无非零数据点」守卫 + setChartEmpty 调用 + 非空路径 emptyEl.hidden = true;
   chartModel 单独锚定 (!models.length 分支, 判定不升级为已知取舍);
2. i18n 契约断言: 4 新键在 I18N.zh 与 I18N.en 同时存在; index.html 7 个 *-empty
   占位 div 均显式 hidden + stats-scope-hint (复用 .scope-hint 类);
3. renderWindows 断言: today.tokens === 0 分支片段返回 noUsageToday 且不含涨跌箭头 ↑;
   cmpExcludesDsh 出现在 notes.push 行且该行含 includes_dsh_today === true 条件;
4. server 字段断言 (动态): dsh 今日 tokens>0 时 _report_windows_response 返回
   compare.includes_dsh_today is True; 全零 False; 未 found 键缺省;
5. 回归锚: style.css 无新增类; renderStatsTotal/renderWindows 函数签名未变;
   :root 渠道配色变量未被本迭代改动.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import db, dsh_api, server

_WEB = Path(__file__).resolve().parents[1] / "app" / "web"
_APP_JS = _WEB / "app.js"
_HTML = _WEB / "index.html"
_CSS = _WEB / "style.css"


def _src() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _extract_fn(src: str, name: str) -> str:
    """提取顶层函数源码: 从 `function NAME(` 到首个行首 `}` (本仓统一格式)."""
    start = src.index(f"function {name}(")
    end = src.index("\n}", start)
    return src[start:end + 2]


def _strip_comments(code: str) -> str:
    """去掉 // 行注释, 避免注释里的字样 (如 new Chart) 干扰位置断言."""
    return "\n".join(line.split("//")[0] for line in code.splitlines())


# ---------------------------------------------------------------------------
# 1. 空守卫源码断言 (6 图函数统一口径 + chartModel 单独锚定)
# ---------------------------------------------------------------------------


def test_chart_report_stack_empty_guard():
    body = _strip_comments(_extract_fn(_src(), "chartReportStack"))
    assert 'if (!d || !Object.values(d.series).some((arr) => arr.some((v) => v > 0))) {' in body
    assert 'setChartEmpty("report-stack", "report-stack-empty", "noDataInRange");' in body
    assert 'if (emptyEl) emptyEl.hidden = true;' in body   # 非空路径隐藏占位


def test_chart_report_donut_empty_guard_before_new_chart():
    """donut 空守卫必须在 new Chart 之前 return (centerText 为实例级插件)."""
    body = _strip_comments(_extract_fn(_src(), "chartReportDonut"))
    assert "const grand = totals.reduce((a, b) => a + b, 0);" in body
    assert "if (grand === 0) {" in body
    assert body.index("setChartEmpty(") < body.index("new Chart(")
    assert 'setChartEmpty("report-donut", "report-donut-empty", "noDataInRange");' in body
    assert 'if (emptyEl) emptyEl.hidden = true;' in body


def test_chart_report_hourly_empty_guard_and_empty_key_param():
    body = _strip_comments(_extract_fn(_src(), "chartReportHourly"))
    assert re.search(r"function chartReportHourly\(d, noAnim, emptyKey\)", body)  # 备注13: 不丢 noAnim 位置
    assert 'if (!d || !Object.values(d.series).some((arr) => arr.some((v) => v > 0))) {' in body
    assert 'setChartEmpty("report-hourly", "report-hourly-empty", emptyKey || "noDataInRange");' in body
    assert 'if (emptyEl) emptyEl.hidden = true;' in body


def test_chart_today_empty_guard():
    body = _strip_comments(_extract_fn(_src(), "chartToday"))
    assert 'if (!trend || !trend.length || !trend.some((d) => (d.input || 0) + (d.output || 0) > 0)) {' in body
    assert 'setChartEmpty("today-chart", "today-empty", "noUsageToday");' in body   # 单渠道标题固定今日
    assert 'if (emptyEl) emptyEl.hidden = true;' in body


def test_chart_trend_empty_guard():
    body = _strip_comments(_extract_fn(_src(), "chartTrend"))
    assert ('if (!trend || !trend.length || !trend.some((d) => (d.total_input_tokens || 0)'
            ' + (d.total_output_tokens || 0) + (d.total_reasoning_tokens || 0) > 0)) {' in body)
    assert 'setChartEmpty("trend-chart", "trend-empty", "noDataInRange");' in body
    assert 'if (emptyEl) emptyEl.hidden = true;' in body


def test_chart_ov_trend_empty_guard():
    body = _strip_comments(_extract_fn(_src(), "chartOvTrend"))
    assert ('if (!dated.length || !dated.some((a) => a.daily7.some((d) => (d.total_cost_usd || 0) > 0'
            ' || (d.request_count || 0) > 0 || (d.total_input_tokens || 0) + (d.total_output_tokens || 0)'
            ' + (d.total_reasoning_tokens || 0) > 0))) {' in body)
    assert 'setChartEmpty("ov-trend-chart", "ov-trend-empty", "noDataInRange");' in body
    assert 'if (emptyEl) emptyEl.hidden = true;' in body


def test_chart_model_empty_branch_anchored_separately():
    """chartModel 判定不升级 (models 非空但全 0 仍建空环为已知取舍), 仅锚定既有
    !models.length 分支内追加占位 + 保留 mr-list 清空 (计划备注10)."""
    body = _extract_fn(_src(), "chartModel")
    assert ('if (!models || !models.length) { setChartEmpty("mr-chart", "mr-empty", "noDataInRange");'
            ' cModel = null; $("mr-list").innerHTML = ""; return; }' in body)
    assert 'if (emptyEl) emptyEl.hidden = true;' in body


def test_hourly_empty_key_passed_by_call_sites_range_aware():
    """emptyKey 档位联动由调用点显式传参 (架构师 R2 轮: 图函数不读全局 state.range)."""
    src = _src()
    load = _strip_comments(_extract_fn(src, "loadReportAll"))
    assert 'chartReportHourly(hourly, undefined, range === "today" ? "noUsageToday" : "noDataInRange");' in load
    rerender = _strip_comments(_extract_fn(src, "rerenderCharts"))
    assert ('chartReportHourly(reportHourlyCache.data, true, reportHourlyCache.range === "today"'
            ' ? "noUsageToday" : "noDataInRange");' in rerender)


# ---------------------------------------------------------------------------
# 2. i18n 契约断言 (4 键双语 + index.html 占位与 hint)
# ---------------------------------------------------------------------------

_I18N_KEYS = ("noUsageToday", "noDataInRange", "cmpExcludesDsh", "statsScopeHint")


def _i18n_block(lang: str) -> str:
    src = _src()
    if lang == "zh":
        return src[src.index("zh: {"):src.index("\n  en: {")]
    start = src.index("\n  en: {")
    return src[start:src.index("\n};", start)]


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_i18n_four_new_keys_in_both_langs(lang):
    block = _i18n_block(lang)
    for key in _I18N_KEYS:
        assert re.search(rf"\b{key}\s*:", block), f"I18N.{lang} 缺少键: {key}"


def test_index_html_seven_empty_placeholders_hidden():
    html = _HTML.read_text(encoding="utf-8")
    for eid in ("report-stack-empty", "report-donut-empty", "report-hourly-empty",
                "today-empty", "mr-empty", "trend-empty", "ov-trend-empty"):
        assert re.search(rf'id="{eid}" hidden', html), f"index.html 缺少空态占位 div: {eid}"


def test_index_html_stats_scope_hint_div():
    """统计页口径 hint 复用既有 .scope-hint 类 + 初始 hidden (防闪现, 备注八)."""
    html = _HTML.read_text(encoding="utf-8")
    assert '<div class="scope-hint" id="stats-scope-hint" hidden>' in html


# ---------------------------------------------------------------------------
# 3. renderWindows 零用量文案 + DSH 口径标注
# ---------------------------------------------------------------------------


def test_render_windows_zero_usage_branch_no_arrow():
    """锚定 today.tokens === 0 分支片段本身 (勿全函数体反向匹配: 既有 cmp 箭头行本就含 ↑)."""
    body = _extract_fn(_src(), "renderWindows")
    frag = body[body.index("w.today.tokens === 0"):body.index("w.compare.pct == null")]
    assert 't("noUsageToday")' in frag
    assert "↑" not in frag   # 零用量不渲染涨跌箭头


def test_render_windows_dsh_note_on_notes_push_line():
    body = _extract_fn(_src(), "renderWindows")
    assert ('if (w.compare.pct != null && w.compare.includes_dsh_today === true)'
            ' notes.push(t("cmpExcludesDsh"));' in body)   # wb-since 通栏标注行


# ---------------------------------------------------------------------------
# 4. server 字段断言 (动态): _report_windows_response 的 compare.includes_dsh_today
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_report_db(tmp_path, monkeypatch):
    """独立临时库: 重定向 data_dir 并重置模块级连接 (与 test_report_api.tmp_report_db 同型)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


def _seed_channels() -> None:
    db.add_account("tok-oc", "ws-oc")
    db.add_account("cookie-bai", "bai-user-1", switch=False, source="bai", dedupe_key="bai-user-1")
    db.add_account("tok-cc", "cc-user-1", switch=False, source="commandcode", dedupe_key="cc-user-1")


def _mock_dsh(monkeypatch, found: bool, today: dict | None = None) -> None:
    """mock dsh_api.get_dsh_usage (server 经 `from . import dsh_api` 引用同一模块对象)."""
    payload = {"found": found}
    if today is not None:
        payload["today"] = today
    monkeypatch.setattr(dsh_api, "get_dsh_usage", lambda: payload)


def test_server_windows_dsh_today_tokens_marks_includes_true(tmp_report_db, monkeypatch):
    _seed_channels()
    _mock_dsh(monkeypatch, found=True, today={"input": 35, "cache": 0, "output": 35, "reasoning": 0})
    resp = server._report_windows_response(None)
    assert resp["compare"]["includes_dsh_today"] is True
    assert resp["today"]["tokens"] == 70   # dsh 今日并入 today 窗口


def test_server_windows_dsh_zero_tokens_marks_includes_false(tmp_report_db, monkeypatch):
    _seed_channels()
    _mock_dsh(monkeypatch, found=True, today={"input": 0, "output": 0, "reasoning": 0})
    resp = server._report_windows_response(None)
    assert resp["compare"]["includes_dsh_today"] is False


def test_server_windows_no_dsh_key_when_not_found(tmp_report_db, monkeypatch):
    """未 found 时键缺省 (前端 `=== true` 判定安全)."""
    _seed_channels()
    _mock_dsh(monkeypatch, found=False)
    resp = server._report_windows_response(None)
    assert "includes_dsh_today" not in resp["compare"]


# ---------------------------------------------------------------------------
# 5. 回归锚 (防顺手重构 / 零新增类)
# ---------------------------------------------------------------------------


def test_style_css_no_new_classes_for_empty_state():
    css = _CSS.read_text(encoding="utf-8")
    assert "stats-scope-hint" not in css   # hint 复用 .scope-hint
    assert "cmp-dsh-note" not in css       # cmp 标注走既有 wb-since 结构


def test_render_function_signatures_unchanged():
    src = _src()
    assert "function renderStatsTotal(totals, source)" in src
    assert "function renderWindows(w, hasEst = false)" in src


def test_root_channel_color_vars_unchanged():
    """:root 渠道配色维持 f6dda34 基线 (commandcode 翡翠绿 / zcode 靛蓝)."""
    css = _CSS.read_text(encoding="utf-8")
    root = css[css.index(":root"):css.index("}", css.index(":root"))]
    assert "--ch-commandcode: #10b981" in root
    assert "--ch-zcode: #6366f1" in root
