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
