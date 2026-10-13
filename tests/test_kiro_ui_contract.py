"""Kiro 前端契约: DOM 节点 / 接线字面量 + Node 沙箱内的渲染行为 (node 缺失时 skip)."""
import os
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
HTML = (ROOT / "app/web/index.html").read_text(encoding="utf-8")


class _Nodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.keys = set(), set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        if "data-i18n" in a:
            self.keys.add(a["data-i18n"])


def _nodes():
    p = _Nodes()
    p.feed(HTML)
    return p


_HARNESS = r"""
const fs = require('fs'); const vm = require('vm'); const path = require('path');
const appJs = fs.readFileSync(path.join(process.cwd(), 'app/web/app.js'), 'utf8');
const elements = {};
function mkEl(id) {
  return { id, innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false,
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    querySelectorAll: () => [], querySelector: () => null, addEventListener: () => {},
    setAttribute: () => {}, getAttribute: () => null };
}
function $(id) { if (!elements[id]) elements[id] = mkEl(id); return elements[id]; }
const dummyEl = mkEl('');
dummyEl.querySelector = () => dummyEl;
dummyEl.querySelectorAll = () => [dummyEl];
const win = { addEventListener: () => {}, outerWidth: 800, outerHeight: 600 };
const doc = { documentElement: { dataset: { theme: 'light' } }, getElementById: $,
  querySelectorAll: () => [], querySelector: () => dummyEl, addEventListener: () => {} };
const scr = { availWidth: 1920, availHeight: 1080 };
win.window = win; win.document = doc; win.screen = scr;
const sandbox = { window: win, document: doc, screen: scr, $, console, setTimeout, clearTimeout,
  setInterval: () => 1, clearInterval: () => {},
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  getComputedStyle: () => ({ getPropertyValue: () => '' }) };
vm.createContext(sandbox);
vm.runInContext(appJs, sandbox);
function run(code) { return vm.runInContext(code, sandbox); }
function assert(cond, msg) { if (!cond) throw new Error(msg); }
"""


def _run_node(body):
    node = shutil.which("node") or (r"D:\Program Files\nodejs\node.exe"
                                    if os.path.exists(r"D:\Program Files\nodejs\node.exe") else None)
    if not node:
        pytest.skip("Node.js not available in environment")
    res = subprocess.run([node, "-e", _HARNESS + body + "\nconsole.log('OK');"], cwd=str(ROOT),
                         capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0 and "OK" in res.stdout, f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"


def test_home_kiro_nodes_exist():
    p = _nodes()
    assert {"kiro-quota", "kiro-quota-head", "kiro-quota-cards", "kiro-plan"} <= p.ids
    assert "kiroQuotaTitle" in p.keys


def test_home_kiro_wiring():
    assert "api(`/api/kiro/quota`).catch(() => null)," in JS
    assert "const [w, rows, ov, zq, kq, daily, hourly, all] = await Promise.all([" in JS
    assert "renderQuotaBar(ov.accounts, zq, kq);" in JS
    assert "function renderQuotaBar(accounts, zdata = null, kdata = null) {" in JS
    assert 'metric === "tokens" ? []' not in JS         # tokens 指标也要显示不可用渠道提示
    assert '"reportTokensIncomplete"' in JS
    assert 'setChartEmpty("today-chart", "today-empty", "kiroTokensUnavailable");' in JS


def test_kiro_quota_card_states_via_node():
    _run_node(r"""
    run(`renderKiroQuota({ success: true, state: 'ok', stale: false, plan: 'KIRO STUDENT',
        used: 109.49, limit: 1000, percent: 10.9, reset_in_sec: 7200 })`);
    let h = elements['kiro-quota-cards'].innerHTML;
    assert(h.includes('109.49') && h.includes('1,000'), 'used/limit: ' + h);
    assert(h.includes('11%'), 'percent: ' + h);
    assert(elements['kiro-plan'].textContent === 'KIRO STUDENT', 'plan badge');
    assert(elements['kiro-quota-head'].hidden === false, 'head shown');

    run(`renderKiroQuota({ success: false, state: 'auth_expired', error: 'x' })`);
    h = elements['kiro-quota-cards'].innerHTML;
    assert(h.includes('kiro-cli 登录已过期'), 'expired hint: ' + h);
    assert(elements['kiro-quota-head'].hidden === true, 'head hidden on failure');

    run(`renderKiroQuota({ success: false, state: 'no_auth' })`);
    assert(elements['kiro-quota-cards'].innerHTML.includes('kiro-cli login'), 'no_auth hint');

    run(`renderKiroQuota({ success: true, stale: true, state: 'network', plan: 'P', used: 1, limit: 10,
        percent: 10, reset_in_sec: 60, fetched_at: new Date(Date.now() - 5 * 60000).toISOString() })`);
    assert(elements['kiro-quota-cards'].innerHTML.includes('数据为 5 分钟前'), 'stale note');

    // 零上限额度 (percent=null): 数字位 —, 不画 0% 宽的进度条
    run(`renderKiroQuota({ success: true, state: 'ok', stale: false, plan: 'P', used: 0, limit: 0,
        percent: null, reset_in_sec: 0 })`);
    h = elements['kiro-quota-cards'].innerHTML;
    assert(!h.includes('ub-bar'), 'percent=null must not draw a 0% bar: ' + h);
    assert(h.includes('—'), 'percent=null shows an em dash: ' + h);
    """)


def test_kiro_quota_bar_card_via_node():
    _run_node(r"""
    run(`renderQuotaBar([], null, { success: true, plan: 'KIRO STUDENT', used: 109.49, limit: 1000,
        percent: 10.9, reset_in_sec: 7200, stale: false })`);
    const h = elements['quota-bar'].innerHTML;
    assert(h.includes('Kiro') && h.includes('KIRO STUDENT') && h.includes('109.49'), h);
    run(`renderQuotaBar([], null, { success: false, state: 'network' })`);
    assert(!elements['quota-bar'].innerHTML.includes('kiro'), 'failed quota must not render a card');
    """)
    # 保证 ④ 的零上限特例: percent=null 是合法额度 (显示 —), 不得画 0% 进度条
    _run_node(r"""
    run(`renderQuotaBar([], null, { success: true, plan: 'P', used: 0, limit: 0, percent: null,
        reset_in_sec: 0, stale: false })`);
    const z = elements['quota-bar'].innerHTML;
    assert(z.includes('Kiro'), 'zero-limit card still renders: ' + z);
    assert(!z.includes('qb-bar'), 'percent=null must not draw a 0% progress bar: ' + z);
    assert(z.includes('—'), 'percent=null renders an em dash: ' + z);
    """)


def test_kiro_channel_row_and_overview_via_node():
    _run_node(r"""
    run(`renderChannelTable([{ channel: 'kiro', tokens: 0, input: 0, output: 0, cache_read: 0,
        requests: 12, cost: 0.5, credits: 12.5, tokens_available: false, estimated: true,
        data_since: null }], [])`);
    const t = elements['report-table'].innerHTML;
    assert((t.match(/Kiro 不提供 Token 数据/g) || []).length === 4, '4 个 token 单元格应为 —: ' + t);
    assert(t.includes('12.5') && t.includes('Credits'), 'credits suffix: ' + t);

    run(`renderOverview({ credits: 12.5, request_count: 7, turn_count: 2, session_count: 1,
        total_cost_usd: 0.5, avg_duration_ms: 90000 }, 'kiro')`);
    const g = elements['overview-grid'].innerHTML;
    assert(g.includes('12.5') && g.includes('对话轮数') && g.includes('Kiro 不提供 Token 数据'), g);
    assert(g.includes('est-badge'), '费用应挂估算徽章: ' + g);
    """)

def test_kiro_only_bypasses_login_overlay():
    _run_node(r"""
    assert(run(`canUseLocalCodex({logged_in:false, kiro_found:true})`), 'Kiro only must enter app');
    assert(!run(`canUseLocalCodex({logged_in:false, kiro_found:false})`), 'empty install');
    """)


def test_stats_kiro_nodes_exist_without_i18n_title():
    p = _nodes()
    assert {"kiro-stats", "kiro-missing", "kiro-skipped", "kiro-kpis", "kiro-tables",
            "kiro-model-body"} <= p.ids
    assert {"kiroStatsTitle", "kiroCostHint", "kiroTurns", "kiroApiRequests", "kiroCredits"} <= p.keys
    block = HTML[HTML.index('id="kiro-stats"'):HTML.index('id="codex-stats"')]
    assert "data-i18n-title" not in block


def test_stats_and_records_kiro_wiring():
    assert 'api("/api/kiro/summary?range=" + encodeURIComponent(state.statsRange))' in JS
    assert 'if (page === "stats") loadKiroSummary().catch(() => {});' in JS
    assert "loadKiroSummary();  // Kiro 区块跟随 range 切换" in JS
    assert "if (kiroSummaryLast) renderKiroSummary(kiroSummaryLast);" in JS
    assert 'tokCell(r.source === "kiro", r.input_tokens)' in JS
    assert 'tokCell(s.source === "kiro", s.total_input_tokens)' in JS


def test_kiro_stats_panel_via_node():
    _run_node(r"""
    run(`renderKiroSummary({ found: false })`);
    assert(elements['kiro-stats'].hidden === true, '未装 kiro-cli 不出区块');

    run(`renderKiroSummary({ found: true, has_data: true, skipped: 2,
        totals: { credits: 12.5, request_count: 7, turn_count: 2, session_count: 1, total_cost_usd: 0.5 },
        models: [{ model: 'auto', turns: 1, requests: 3, credits: 2, cost: 0.08 },
                 { model: 'claude-opus-5', turns: 1, requests: 4, credits: 10.5, cost: 0.42 }] })`);
    assert(elements['kiro-stats'].hidden === false, 'panel shown');
    assert(elements['kiro-missing'].hidden === true, 'missing hidden');
    assert(elements['kiro-skipped'].hidden === false && elements['kiro-skipped'].textContent.includes('2'), 'skipped');
    const body = elements['kiro-model-body'].innerHTML;
    assert(body.includes('自动路由（实际模型未知）') && body.includes('claude-opus-5'), body);
    assert(elements['kiro-kpis'].innerHTML.includes('12.5'), 'kpi credits');

    run(`renderKiroSummary({ found: true, has_data: false, skipped: 0, totals: {}, models: [] })`);
    assert(elements['kiro-missing'].hidden === false && elements['kiro-tables'].hidden === true, 'empty state');
    assert(elements['kiro-skipped'].hidden === true, 'no skipped note');
    """)


def test_tok_cell_and_session_card_via_node():
    _run_node(r"""
    assert(run(`tokCell(true, 123)`).includes('—'), 'unavailable → —');
    assert(!run(`tokCell(false, 123)`).includes('—'), 'available → number');
    run(`renderSessionCard({ source: 'kiro', session_id: 's1', request_count: 3, request_count_exact: true,
        total_tokens: 0, total_input_tokens: 0, total_output_tokens: 0, total_reasoning_tokens: 0,
        cache_hit_tokens: 0, hit_rate: 0, speed_samples: 0, ttft_samples: 0 })`);
    const g = elements['ses-card-grid'].innerHTML;
    assert(!g.includes(run(`t("totalTokens")`) + " 0"), "must not claim zero tokens");
    assert((g.match(/Kiro 不提供 Token 数据/g) || []).length >= 3, 'token 指标应说明不可得: ' + g);
    """)

def test_kiro_only_does_not_show_global_empty():
    _run_node(r'''
    for (const id of ['stats-total-cards','zcode-stats','dsh-stats','claudecode-stats','codex-stats']) $(id).hidden = true;
    run(`renderKiroSummary({found:true, has_data:true, totals:{turn_count:1}, models:[]}); updateStatsEmptyState()`);
    assert(elements['stats-empty'].hidden, 'Kiro data coexists with global empty');
    ''')

def test_records_kiro_residual_nodes():
    p = _nodes()
    assert "rec-kiro-hint" in p.ids
    assert "kiroRecordsCount" in p.keys   # 提示文案本身保留, 仅显隐受控


def test_records_kiro_residual_hidden_via_node():
    _run_node(r"""
    run(`state.kiroFound = false; state.records.source = 'all'; syncSourceFilter()`);
    const h = elements['rec-source-filter'].innerHTML;
    assert(!h.includes('value="kiro"'), 'kiro option must be absent when kiro not installed: ' + h);
    assert(elements['rec-kiro-hint'].hidden === true, 'hint must be hidden when kiro not installed');

    run(`state.kiroFound = true; syncSourceFilter()`);
    const h2 = elements['rec-source-filter'].innerHTML;
    assert(h2.includes('value="kiro"'), 'kiro option must be present when kiro installed: ' + h2);
    assert(elements['rec-kiro-hint'].hidden === false, 'hint must be shown when kiro installed');
    assert(elements['rec-source-filter'].value === 'all', 'default selection unchanged');
    """)


def test_records_kiro_presence_wiring():
    assert "kiroFound: false," in JS
    assert JS.count("state.kiroFound = !!st.kiro_found;") == 2   # checkState + gousageOnLoginSuccess

