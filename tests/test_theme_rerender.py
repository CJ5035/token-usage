"""EVOLUTION-4 切主题重渲回归测试: 源码级静态断言.

前端无 DOM 自动化设施, 参照 test_network_deblocking 的源码断言模式
(doc/20260905-evolution-plan-4.md §测试验证点1 + 实施备注 1/4/5/6):

- 模块级缓存 (reportDailyCache/reportHourlyCache/chTrendCache/ovAccountsCache)
  声明、loadReportAll 入口置空、写入点键校验、读侧 (rerenderCharts) 再校验;
- rerenderCharts 无顶层 `if (!state.data) return;` 早退守卫 (统计页分支内部
  保留 state.data 判断属预期, 勿断言"函数体内不含 state.data");
- 三处 DOM 内联快照色改用 CH_COLOR[...] CSS 变量引用 (qb-dot background 与
  qb-name color 分别命中), 模板行内不再出现 `${chColor(` 内联 style 用法;
  Chart.js 数据集路径仍走 chColor (canvas 不解析 var(), 两条上色路径不混用);
- 9 个图表函数 noAnim 参数 + animation 关闭; themedName 全量解析契约
  (muse→meta / hy 前缀 / 未知→deepseek); refreshIcons 四表体原地换 src;
  applyDarkMode 不再直接调用 refreshIcons (重渲收敛, 唯一入口).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

_APP_JS = Path(__file__).resolve().parents[1] / "app" / "web" / "app.js"


def _src() -> str:
    return _APP_JS.read_text(encoding="utf-8")


def _extract_fn(src: str, name: str) -> str:
    """提取顶层函数源码: 从 `function NAME(` 到首个行首 `}` (本仓统一格式)."""
    start = src.index(f"function {name}(")
    end = src.index("\n}", start)
    return src[start:end + 2]


def _strip_comments(code: str) -> str:
    """去掉 // 行注释, 避免注释里的字样 (如 await) 干扰位置断言."""
    return "\n".join(line.split("//")[0] for line in code.splitlines())


# ---------------------------------------------------------------------------
# 1. 模块级缓存: 声明 / 入口置空 / 写入点键校验 (备注5)
# ---------------------------------------------------------------------------


def test_cache_declarations_exist():
    src = _src()
    for name in ("reportDailyCache", "reportHourlyCache", "chTrendCache", "ovAccountsCache"):
        assert f"let {name}" in src, f"缺少模块级缓存声明: {name}"


def test_load_report_all_nulls_caches_before_first_await():
    """loadReportAll 入口 (await 之前) 先置空缓存: 在途期间切主题走 no-op."""
    code = _strip_comments(_extract_fn(_src(), "loadReportAll"))
    first_await = code.index("await")
    first_null = code.index("reportDailyCache = null;")
    assert first_null < first_await
    assert code.index("reportHourlyCache = null;") < first_await


def test_report_cache_write_side_key_validation():
    """写入点键校验 (备注5): range/metric 与当前 state 不匹配即丢弃, 防连点乱序覆盖."""
    body = _extract_fn(_src(), "loadReportAll")
    # daily URL 使用入口捕获的 metric (而非中途可变的 state.reportMetric)
    assert "`/api/report/daily?range=${range}&metric=${metric}`" in body
    assert "if (range === state.range && metric === state.reportMetric) {" in body
    assert "reportDailyCache = { range, metric, data: daily };" in body
    assert "if (range === state.range) reportHourlyCache = { range, data: hourly };" in body
    # 置 null: loadReportAll 函数体内 2 处 (入口 + 7d/30d/all 档 else 卡隐藏分支, 备注2);
    # 全文件计数再各加 1 (声明行 let x = null 亦含该子串)
    src = _src()
    assert body.count("reportHourlyCache = null;") == 2
    assert src.count("reportHourlyCache = null;") == 3
    assert src.count("reportDailyCache = null;") == 2


def test_channel_trend_cache_keyed_by_state_range_in_seq_guard():
    """chTrendCache 写入点在 chSeq 守卫块内, 键控写死 state.range (非接口 date 二值参数).

    若按 date 键控, 7d/30d 档读侧校验恒不匹配 → 24h 图残留旧主题轴色 (回归锚).
    """
    body = _extract_fn(_src(), "loadDashboard")
    guard = body.index("if (seq !== chSeq) return;")
    write = body.index("chTrendCache = { channel: state.channel, range: state.range, data: trend };")
    assert guard < write


def test_overview_accounts_cache_write_in_seq_guard():
    """ovAccountsCache 写入点在 ovSeq 守卫块内, 缓存原始 data.accounts."""
    body = _extract_fn(_src(), "loadOverview")
    guard = body.index("if (seq !== ovSeq) return;")
    write = body.index("ovAccountsCache = data.accounts;")
    assert guard < write


# ---------------------------------------------------------------------------
# 2. rerenderCharts 重构: 无顶层早退守卫 / 读侧校验 / 备注1 传 .data
# ---------------------------------------------------------------------------


def test_rerender_charts_no_top_level_state_data_guard():
    """去掉 `if (!state.data) return;` 顶层早退 (统计页分支内部保留 state.data 属预期)."""
    body = _extract_fn(_src(), "rerenderCharts")
    assert "if (!state.data) return;" not in body
    # 统计页分支内部仍按 state.data 判断
    assert "chartTrend(state.data.trend, true)" in body


def test_rerender_charts_read_side_key_validation():
    """重渲前读侧校验: 缓存键与当前 state.range/reportMetric/channel 比对, 不匹配即 no-op."""
    body = _extract_fn(_src(), "rerenderCharts")
    assert "reportDailyCache.range === state.range" in body
    assert "reportDailyCache.metric === state.reportMetric" in body
    assert "chTrendCache.channel === state.channel" in body
    assert "chTrendCache.range === state.range" in body
    # 总览分支用 ovAccountsCache
    assert "chartOvTrend(ovAccountsCache, true)" in body


def test_rerender_charts_hourly_passes_data_not_cache_object():
    """备注1: chartReportHourly 必须传 reportHourlyCache.data (传缓存对象会
    Object.keys(undefined) 抛错并中断 rerenderCharts 调用链)."""
    body = _extract_fn(_src(), "rerenderCharts")
    assert "chartReportHourly(reportHourlyCache.data, true," in body
    assert "chartReportHourly(reportHourlyCache," not in body


def test_refresh_icons_called_only_from_rerender_charts():
    """重渲收敛: refreshIcons 仅由 rerenderCharts 末尾调用, applyDarkMode 原调用删除."""
    src = _src()
    dark = _extract_fn(src, "applyDarkMode")
    rerender = _extract_fn(src, "rerenderCharts")
    assert "refreshIcons();" not in dark          # applyDarkMode 原调用已删除
    assert "refreshIcons();" in rerender
    assert src.count("refreshIcons();") == 1      # 全文件唯一调用点
    assert src.count("function refreshIcons()") == 1


# ---------------------------------------------------------------------------
# 3. 三处内联快照色改 CSS 变量引用 (备注4: 按"用法"分 + 反向断言)
# ---------------------------------------------------------------------------


def test_inline_channel_colors_use_ch_color_var_refs():
    src = _src()
    # qb-dot background 与 qb-name color 分别命中 (renderQuotaBar 两处卡)
    assert 'qb-dot" style="background:${CH_COLOR[' in src
    assert 'qb-name" style="color:${CH_COLOR[' in src
    # 渠道名 td (renderChannelTable)
    assert '<td style="color:${CH_COLOR[' in src
    # fallback 兜底未知渠道
    assert 'CH_COLOR[ch] || "#4f8ef7"' in src


def test_no_ch_color_inline_style_in_templates():
    """反向断言: 三处模板行内不再出现 ${chColor( 内联 style 用法."""
    src = _src()
    assert 'style="background:${chColor(' not in src
    assert 'style="color:${chColor(' not in src


def test_ch_color_still_used_by_chart_datasets():
    """chColor() 本体不动: Chart.js 数据集直接消费 (canvas 不解析 var())."""
    src = _src()
    assert "backgroundColor: chColor(ch)" in src      # chartReportStack / chartReportHourly
    assert "chs.map(chColor)" in src                   # chartReportDonut
    assert "function chColor(ch)" in src


# ---------------------------------------------------------------------------
# 4. noAnim 参数 (备注6: 共 9 个图表函数)
# ---------------------------------------------------------------------------

_NOANIM_FUNCS = [
    "chartToday", "chartReportStack", "chartReportDonut", "chartReportHourly",
    "chartOvTrend", "chartTrend", "chartZcodeTrend", "chartClaudecodeTrend", "chartModel",
]


def test_nine_chart_functions_take_noanim_param():
    src = _src()
    for name in _NOANIM_FUNCS:
        assert re.search(rf"function {name}\([^)]*noAnim", src), f"{name} 缺少 noAnim 参数"
    assert src.count("animation: noAnim ? false : undefined,") == 9


def test_rerender_and_refresh_icons_pass_noanim_true():
    """切主题重渲路径全部传 noAnim=true (避免集体重播生长/扫入动画)."""
    src = _src()
    rerender = _extract_fn(src, "rerenderCharts")
    icons = _extract_fn(src, "refreshIcons")
    for call in (
        "chartReportStack(reportDailyCache.data, true)",
        "chartReportDonut(reportDailyCache.data, true)",
        "chartToday(chTrendCache.data, true)",
        "chartTrend(state.data.trend, true)",
        "chartZcodeTrend(zcodeSummaryLast.daily7, true)",
        "chartClaudecodeTrend(claudecodeSummaryLast.daily7, true)",
    ):
        assert call in rerender, f"rerenderCharts 缺少 noAnim 调用: {call}"
    # chartModel 移入 refreshIcons 统一处理 (noAnim), 不再出现在 rerenderCharts
    assert "chartModel(state.data.models, true)" in icons
    assert "chartModel(" not in rerender


# ---------------------------------------------------------------------------
# 5. 图标变体: themedName 全量解析契约 + refreshIcons 原地换 src
# ---------------------------------------------------------------------------


def test_themed_name_full_mapping_contract():
    """themedName 需承载 modelIcon 原有全部解析逻辑: 缺 muse→meta / hy 前缀 /
    未知→deepseek 任一条会 404 破图 (muse/hy2/未知模型走查锚)."""
    body = _extract_fn(_src(), "themedName")
    assert 'muse: "meta"' in body
    assert 'base.startsWith("hy") ? "hy" : "deepseek"' in body
    assert 'name === "kimi" ? "kimi-color" : name' in body
    assert '["gpt", "grok", "mimo"].includes(name)' in body


def test_model_icon_uses_themed_name():
    body = _extract_fn(_src(), "modelIcon")
    assert "themedName(m, dark)" in body
    assert "alt=\"${escapeHtml(m)}\"" in body  # refreshIcons 依赖 alt 读回原文


def test_refresh_icons_swaps_src_in_place_on_four_tbodies():
    """四张表体 img 原地换 src, 不重建 DOM (记录页滚动/分页/筛选态保持)."""
    body = _extract_fn(_src(), "refreshIcons")
    for tid in ("zcode-model-body", "dsh-model-body", "claudecode-model-body", "records-body"):
        assert f'"{tid}"' in body
    assert 'themedName(img.alt, dark)' in body
    assert 'img.getAttribute("src") !== next' in body
    assert 'img.setAttribute("src", next)' in body


# ---------------------------------------------------------------------------
# 6. 语法检查 (无 node 环境跳过)
# ---------------------------------------------------------------------------


def test_app_js_syntax_node_check():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 不可用")
    proc = subprocess.run([node, "--check", str(_APP_JS)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
