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

    # M6 §3.5: 两个三列容器 (ID 兼容) + 首页 dsh_status 状态条 (I3)
    assert {"dsh-kpis-total", "dsh-kpis-today", "dsh-status", "dsh-error",
            "dsh-trend-chart", "dsh-trend-empty", "home-dsh-status", "home-dsh-error"} <= nodes.ids
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
        "function scheduleDshRefresh(status)",
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


def test_dsh_refresh_scheduler_rhythm_contract():
    """I3 §3.4: 默认 15s 重取; scanning 时 1s 后查状态, 单轮快速查询累计 ≤30s;
    失败退避 = retry_after_seconds (≤60s); 首页消费 windows/channel-overview 顶层
    dsh_status 且只有一个调度入口; 隐藏页取消 timer。"""
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert "const DSH_REFRESH_POLL_MS = 15_000;" in js
    assert "const DSH_SCANNING_POLL_MS = 1_000;" in js
    assert "const DSH_SCANNING_MAX_MS = 30_000;" in js
    assert "const DSH_FAIL_BACKOFF_S = 60;" in js
    assert "function dshSchedulerTarget()" in js     # 统计页或首页 all/dsh 可见时才活动
    assert "function dshSchedulerTick(target)" in js
    assert "dshRefreshTimer = setTimeout" in js       # 唯一自动刷新周期
    assert js.count("dshRefreshTimer = setTimeout") == 1
    assert "renderHomeDshStatus(w.dsh_status);" in js            # 首页 all: windows 顶层
    assert "renderHomeDshStatus(totals.dsh_status);" in js       # 首页 dsh: channel-overview 顶层
    assert "dshRetryButton(seconds)" in js
    assert 'data-dsh-retry${seconds > 0 ? " disabled" : ""}' in js   # 退避未到时禁用重试


def test_dsh_home_and_kpi_containers_contract():
    """I2/M6 §3.5: 首页 DSH 六卡 (速度/步数替换命中量与请求数占位), 统计页双 KPI 容器;
    I4: 纯 DSH 请求计数显示 — 与"已知请求数"提示。"""
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert 'l: t("dshKpiAvgTps"), v: fmtTps(totals.avg_tps)' in js
    assert 'l: t("dshKpiSteps"), v: fmtInt(totals.steps)' in js
    assert 'v: dshUnavailableCell("dshCostUnavailable"), s: t("dshCostUnavailable")' in js
    overview = js[js.index("function renderOverview("):js.index("/* ---------------- 首页: 今日趋势")]
    assert 't("hitAmount")' not in overview.split("isDsh ? [")[1].split("] : [")[0]   # DSH 分支无重复命中量卡
    assert '"dsh-kpis-total"' in js and '"dsh-kpis-today"' in js
    assert 'const reqValue = dshPartial && !known ? "—"' in js
    assert 't("dshRequestsPartial")' in js
    assert 'const hintKey = metric === "requests" ? "reportRequestsIncomplete" : "reportCostIncomplete";' in js
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    assert 'data-i18n="codexCostUnavailable"' not in html   # I4: 不再复用 Codex 专用键
    assert 'data-i18n="reportCostIncomplete"' in html
    # I6 §3.2: 诊断行展示数量 + token 用量, 并明示全部数据范围
    assert "{undatedTokens}" in js and "{futureTokens}" in js
    assert "全部数据范围" in js


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
    # M2: 比较排除提示读计划形态 compare.excluded_channels (仅 DSH 存在时由 server 附带)
    assert 'w.compare.excluded_channels.includes("dsh")' in js
    assert "dsh_excluded_from_compare" not in js
    assert 'r.channel === "dsh" ? dshUnavailableCell("dshRequestsUnavailable")' in js
    assert 'r.channel === "dsh" ? dshUnavailableCell("dshCostUnavailable")' in js
    assert "escapeHtml(r.data_since ||" in js


def test_dsh_home_tick_avoids_full_dashboard_reload():
    """20260911 问题1 方案A②: 首页 all 页签 DSH 周期刷新只静默刷状态条,
    不再整页 loadDashboard (曾致三图每 15s destroy+重建并重播入场动画);
    dsh 页签保留数据保活但 noAnim。重武装仍只经 scheduleDshRefresh (唯一 setTimeout)。"""
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    t0 = js.index("function dshSchedulerTick(")
    tick = js[t0:js.index("\n}", t0)]
    assert 'refreshHomeDshStrip() : loadDashboard(true, true)' in tick   # all 仅刷状态条 / dsh 保活 noAnim
    assert "loadDashboard(true)" not in tick                             # 旧的单参整页刷新已移除
    s0 = js.index("async function refreshHomeDshStrip")
    strip = js[s0:js.index("\n}", s0)]
    assert 'renderHomeDshStatus(w.dsh_status)' in strip                  # 复用状态条渲染 (内部重武装)
    assert "scheduleDshRefresh(" in strip                                # 失败退避也重武装
    assert 'await api("/api/report/windows")' in strip
    assert js.count("dshRefreshTimer = setTimeout") == 1                 # 周期唯一入口不破坏
    # 修复轮3 根因: renderHomeDshStatus 收到无 dsh_status 时不得拆台
    # (否则 scheduleDshRefresh(undefined) 在 :1125 先 clear 再 return, 只清不装)。
    h0 = js.index("function renderHomeDshStatus(")
    home_status = js[h0:js.index("\n}", h0)]
    assert "if (!status) return;" in home_status                         # 无状态则不触碰 timer
    assert "scheduleDshRefresh(status);" in home_status                  # 有状态照旧重武装
    # 顺序即语义: 守卫必须排在重武装之前, 颠倒则等价于修复失效 (仅断言两条子串抓不到)
    assert (home_status.index("if (!status) return;")
            < home_status.index("scheduleDshRefresh(status);"))
    # 纵深防御: 单渠道调用点也不再把缺 dsh_status 的响应送进状态条渲染
    load_dash = js[js.index("async function loadDashboard("):js.index("\n}", js.index("async function loadDashboard("))]
    assert "if (totals.dsh_status) renderHomeDshStatus(totals.dsh_status);" in load_dash
