from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_workbuddy_stats_nodes_and_login_entry():
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    assert 'id="workbuddy-stats"' in html
    assert 'id="workbuddy-kpis"' in html
    assert 'id="workbuddy-model-body"' in html
    assert 'id="btn-add-workbuddy"' in html
    assert 'data-i18n="loginWorkbuddy"' in html


def test_workbuddy_frontend_contract():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    css = (ROOT / "app/web/style.css").read_text(encoding="utf-8")
    assert "/api/workbuddy/summary" in js
    assert "function loadWorkbuddySummary" in js
    assert "function renderWorkbuddySummary" in js
    assert "workbuddy" in js
    assert "credits" in js
    assert 'unit === "credits"' in js
    assert "--ch-workbuddy:" in css


def test_workbuddy_i18n_keys_are_bilingual():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert "loginWorkbuddy:" in js
    assert "workbuddyStatsTitle:" in js
    assert "workbuddyCredits:" in js
    # New auth status keys in I18N
    assert "authRequired:" in js
    assert "authUnknown:" in js
    assert "workbuddyReloginHint:" in js


def test_relogin_passes_account_id_to_open_login_and_api():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    assert 'open_login("relogin", id)' in js
    assert 'api("/api/relogin", { method: "POST", body: JSON.stringify({ id }) })' in js


def test_workbuddy_ui_behavior_via_node():
    import os
    import shutil
    import subprocess
    node_bin = shutil.which("node") or (r"D:\Program Files\nodejs\node.exe" if os.path.exists(r"D:\Program Files\nodejs\node.exe") else None)
    if not node_bin:
        pytest.skip("Node.js not available in environment")

    js_code = r"""
    const fs = require('fs');
    const vm = require('vm');
    const path = require('path');

    const appJs = fs.readFileSync(path.join(process.cwd(), 'app/web/app.js'), 'utf8');

    // Minimal DOM/mock environment
    const elements = {};
    function $(id) {
        if (!elements[id]) {
            elements[id] = { id, innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false, querySelectorAll: () => [], querySelector: () => null, addEventListener: () => {}, setAttribute: () => {}, getAttribute: () => null };
        }
        return elements[id];
    }
    const I18N = {
        zh: {
            authRequired: "需要重新登录",
            authUnknown: "会话待验证",
            workbuddyReloginHint: "WorkBuddy 身份验证失败，请重新登录后获取用量。",
            loggedIn: "已登录",
            notLoggedIn: "未登录",
            relogin: "重新登录",
            userSwitchTip: "切换",
            userCountTip: "计数",
            updatedAt: "更新于",
            lastSync: "上次同步",
            records: "条"
        }
    };
    let currentLang = 'zh';
    function t(k) { return I18N[currentLang][k] || k; }
    function escapeHtml(s) { return String(s || ''); }
    function fmtRelative(s) { return s || ''; }
    function fmtInt(n) { return String(n || 0); }
    const state = { quotaRetryTimer: null };

    // Extract syncTopBar and renderUsageBlocks
    const dummyEl = { id: '', innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false, querySelectorAll: () => [], querySelector: () => null, addEventListener: () => {} };
    dummyEl.querySelector = () => dummyEl;
    dummyEl.querySelectorAll = () => [dummyEl];
    const win = { addEventListener: () => {}, outerWidth: 800, outerHeight: 600 };
    const doc = { documentElement: { dataset: { theme: 'light' } }, getElementById: $, querySelectorAll: () => [], querySelector: () => dummyEl, addEventListener: () => {} };
    const scr = { availWidth: 1920, availHeight: 1080 };
    win.window = win;
    win.document = doc;
    win.screen = scr;
    const sandbox = { window: win, document: doc, screen: scr, $, t, escapeHtml, fmtRelative, fmtInt, state, console, setTimeout, clearTimeout, setInterval: () => 1, clearInterval: () => {}, fetch: async () => ({ ok: true, json: async () => ({}) }) };
    vm.createContext(sandbox);

    // Run app.js definitions or extract functions
    vm.runInContext(appJs + '; this.syncTopBar = syncTopBar; this.renderUsageBlocks = renderUsageBlocks;', sandbox);

    // 1. Test syncTopBar with auth_status === "required"
    sandbox.syncTopBar({ logged_in: true, auth_status: "required", account_name: "TestWB" });
    const tbLogin = sandbox.$("tb-login");
    if (!tbLogin.innerHTML.includes("需要重新登录")) {
        throw new Error("syncTopBar failed to show authRequired label: " + tbLogin.innerHTML);
    }
    if (tbLogin.style.color !== "var(--red)") {
        throw new Error("syncTopBar failed to set red style for required auth: " + tbLogin.style.color);
    }

    // 2. Test syncTopBar with auth_status === "unknown"
    sandbox.syncTopBar({ logged_in: true, auth_status: "unknown", account_name: "TestWB" });
    if (!tbLogin.innerHTML.includes("会话待验证")) {
        throw new Error("syncTopBar failed to show authUnknown label: " + tbLogin.innerHTML);
    }

    // 3. Test renderUsageBlocks with quota.auth_error and accountId = 42
    const box = { innerHTML: '', querySelector: () => ({ addEventListener: () => {} }) };
    sandbox.renderUsageBlocks({ success: false, auth_error: true }, box, 42);
    if (!box.innerHTML.includes('data-workbuddy-relogin="42"')) {
        throw new Error("renderUsageBlocks failed to render relogin button with accountId: " + box.innerHTML);
    }
    if (!box.innerHTML.includes("WorkBuddy 身份验证失败")) {
        throw new Error("renderUsageBlocks failed to show workbuddyReloginHint: " + box.innerHTML);
    }

    console.log("OK");
    """
    res = subprocess.run([node_bin, "-e", js_code], cwd=str(ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Node verification failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "OK" in res.stdout





def test_workbuddy_account_list_unifies_with_topbar_via_node():
    """口径统一: renderUsersList 的账号列表与顶栏 (syncTopBar) 使用同一 auth_status 映射.

    - auth_status "required" + has_token -> 「需要重新登录」badge + data-act="relogin" 按钮
    - auth_status "valid" (活跃行, id === activeId, has_token) -> wsStatus 「已登录」, 且不含
      「需要重新登录」/「会话待验证」 (即渠道恢复后列表与顶栏一致, 无矛盾)
    - auth_status "unknown" -> 「会话待验证」

    node 不可用时优雅跳过, 与 test_workbuddy_ui_behavior_via_node 同模式.
    """
    import os
    import shutil
    import subprocess
    node_bin = shutil.which("node") or (r"D:\Program Files\nodejs\node.exe" if os.path.exists(r"D:\Program Files\nodejs\node.exe") else None)
    if not node_bin:
        pytest.skip("Node.js not available in environment")

    js_code = r"""
    const fs = require('fs');
    const vm = require('vm');
    const path = require('path');

    const appJs = fs.readFileSync(path.join(process.cwd(), 'app/web/app.js'), 'utf8');

    // Minimal DOM/mock environment (mirror test_workbuddy_ui_behavior_via_node)
    const elements = {};
    function $(id) {
        if (!elements[id]) {
            elements[id] = { id, innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false, querySelectorAll: () => [], querySelector: () => null, addEventListener: () => {}, setAttribute: () => {}, getAttribute: () => null };
        }
        return elements[id];
    }
    // renderUsersList 使用的全部 t() key -> 使用真实 zh 标签, 断言比对真实文案
    const I18N = {
        zh: {
            noUsers: "暂无账号",
            loginRow: "登录",
            renameBtn: "重命名",
            deleteUser: "删除",
            relogin: "重新登录",
            logout: "退出登录",
            switchTo: "切换到",
            notLoggedIn: "未登录",
            authRequired: "需要重新登录",
            authUnknown: "会话待验证",
            currentUserBadge: "当前用户",
            loggedIn: "已登录",
            sourceBai: "BAI",
            sourceCommandcode: "CommandCode",
            ccHistoryNote: "仅历史用量"
        }
    };
    let currentLang = 'zh';
    function t(k) { return I18N[currentLang][k] || k; }
    function escapeHtml(s) { return String(s || ''); }
    function fmtRelative(s) { return s || ''; }
    function fmtInt(n) { return String(n || 0); }
    const state = { quotaRetryTimer: null };

    const dummyEl = { id: '', innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false, querySelectorAll: () => [], querySelector: () => null, addEventListener: () => {} };
    dummyEl.querySelector = () => dummyEl;
    dummyEl.querySelectorAll = () => [dummyEl];
    const win = { addEventListener: () => {}, outerWidth: 800, outerHeight: 600 };
    const doc = { documentElement: { dataset: { theme: 'light' } }, getElementById: $, querySelectorAll: () => [], querySelector: () => dummyEl, addEventListener: () => {} };
    const scr = { availWidth: 1920, availHeight: 1080 };
    win.window = win;
    win.document = doc;
    win.screen = scr;
    const sandbox = { window: win, document: doc, screen: scr, $, t, escapeHtml, fmtRelative, fmtInt, state, console, setTimeout, clearTimeout, setInterval: () => 1, clearInterval: () => {}, fetch: async () => ({ ok: true, json: async () => ({}) }) };
    vm.createContext(sandbox);

    vm.runInContext(appJs + '; this.renderUsersList = renderUsersList;', sandbox);

    const list = sandbox.$("users-list");

    // Case A: WorkBuddy account with auth_status "required" -> 需要重新登录 + relogin button
    sandbox.renderUsersList([
        { id: 1, name: "WB-Required", source: "workbuddy", workspace_id: "wb-ws", has_token: true, auth_status: "required" }
    ], 1);
    if (!list.innerHTML.includes("需要重新登录")) {
        throw new Error("renderUsersList required-state missing authRequired label: " + list.innerHTML);
    }
    if (!list.innerHTML.includes('data-act="relogin"')) {
        throw new Error("renderUsersList required-state missing relogin button: " + list.innerHTML);
    }

    // Case B: WorkBuddy active account with auth_status "valid" -> 已登录, NOT 需要重新登录/会话待验证
    sandbox.renderUsersList([
        { id: 2, name: "WB-Valid", source: "workbuddy", workspace_id: "wb-ws2", has_token: true, auth_status: "valid" }
    ], 2);
    if (!list.innerHTML.includes("已登录")) {
        throw new Error("renderUsersList valid-state missing loggedIn label: " + list.innerHTML);
    }
    if (list.innerHTML.includes("需要重新登录") || list.innerHTML.includes("会话待验证")) {
        throw new Error("renderUsersList valid-state must NOT show required/unknown (口径统一 violated): " + list.innerHTML);
    }

    // Case C: WorkBuddy account with auth_status "unknown" -> 会话待验证
    sandbox.renderUsersList([
        { id: 3, name: "WB-Unknown", source: "workbuddy", workspace_id: "wb-ws3", has_token: true, auth_status: "unknown" }
    ], 999);
    if (!list.innerHTML.includes("会话待验证")) {
        throw new Error("renderUsersList unknown-state missing authUnknown label: " + list.innerHTML);
    }

    console.log("OK");
    """
    res = subprocess.run([node_bin, "-e", js_code], cwd=str(ROOT), capture_output=True, text=True)

    assert res.returncode == 0, f"Node verification failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "OK" in res.stdout


def test_workbuddy_relogin_routing_already_locked_by_relogin_targeting():
    """WorkBuddy 定向重登路由已由 tests/test_relogin_targeting.py 直接锁定 (import _parse_login_mode).

    在此静态确认 app/main.py 的路由行仍与已有测试断言一致, 避免逻辑漂移未被察觉.
    不重复 test_relogin_targeting.py 的行为断言 (见 test_workbuddy_relogin_resolves_clicked_account).
    """
    main_src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert 'source = "workbuddy" if account and account["source"] == "workbuddy" else "opencode"' in main_src


def test_workbuddy_local_dual_cost_contract():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    # 费用 = token 估算 USD (主值); credits 仅作并行展示的积分指标, 不参与换算
    assert "credits" in js
    assert "local_only" in js
    assert "unpriced_requests" in js
    assert js.count('"workbuddy"].includes(source)') == 1      # 仅 renderOverview 一处 (R17)


def test_workbuddy_i18n_dual_cost_keys_bilingual():
    js = (ROOT / "app/web/app.js").read_text(encoding="utf-8")
    for key in ("wbLocalOnly:", "wbCostEstimated:", "wbUnpricedModels:", "wbRemoteCreditsOnly:"):
        assert js.count(key) >= 2, f"{key} 需中英各一份"


def test_workbuddy_local_note_inside_report_single():
    """Step 8 #wb-local-note 必须位于单渠道容器 #report-single 的概览卡内 (DOM 结构断言)."""
    html = (ROOT / "app/web/index.html").read_text(encoding="utf-8")
    start = html.index('<div id="report-single"')
    end = html.index('id="page-stats"', start)
    single = html[start:end]
    assert 'id="wb-local-note"' in single
    assert 'id="overview-grid"' in single


def test_workbuddy_local_autorefresh_behavior_via_node():
    """Step 8a 行为验证 (Node VM, 非字符串计数): WorkBuddy 本地导入自动重取 + R54 时序 + 轮询生命周期.

    覆盖 (行为断言, 用可控 fetch/假时钟驱动, 不通过字符串计数代替行为验证):
    - 首次空库 overview running=true -> 500ms 轮询 -> 完成后 running=false 有数据, 六卡更新, 停表
    - R54: overview 返回前不得发 trend; overview 完成后 trend 与六卡同一轮更新
    - 切走 (channel/page) 后定时器不重取不重绘; 迟到 (seq 过期) 响应不绘制不重设轮询
    - all 全渠道并发 (.some) 不重复调度; running=false 停表
    - applyCurrency/applyLang 首页 workbuddy 重取 (货币/语言随动); init 首屏不发报表请求
    - 回到前台 home/workbuddy 重取一次; document.hidden 停表
    """
    import os
    import shutil
    import subprocess
    node_bin = shutil.which("node") or (r"D:\Program Files\nodejs\node.exe" if os.path.exists(r"D:\Program Files\nodejs\node.exe") else None)
    if not node_bin:
        pytest.skip("Node.js not available in environment")

    js_code = r"""
    const fs = require('fs');
    const vm = require('vm');
    const path = require('path');
    const appJs = fs.readFileSync(path.join(process.cwd(), 'app/web/app.js'), 'utf8');

    // ---------- 可控制定时器 (假时钟) ----------
    let fakeTimers = [];
    function setTimeout(fn, ms) {
      const t = { fn, ms: ms || 0, cancelled: false };
      fakeTimers.push(t);
      return t;
    }
    function clearTimeout(id) {
      if (!id) return;
      id.cancelled = true;
      fakeTimers = fakeTimers.filter((x) => x !== id);
    }
    function setInterval() { return 1; }
    function clearInterval() {}
    function pendingTimerCount() { return fakeTimers.length; }
    function fireDueTimers() {
      const due = fakeTimers.slice();
      fakeTimers = [];
      for (const t of due) { t.cancelled = true; t.fn(); }
    }
    function flushAsync() { return new Promise((r) => setImmediate(r)); }

    // ---------- 假 DOM ----------
    const elements = {};
    function classList() { return { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
    function $(id) {
      if (!elements[id]) {
        elements[id] = {
          id, innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false,
          classList: classList(), closest: () => ({ hidden: false, querySelector: () => null }),
          parentElement: null, querySelectorAll: () => [], querySelector: () => null,
          addEventListener: () => {}, setAttribute: () => {}, getAttribute: () => null,
          insertAdjacentHTML: () => {},
        };
      }
      return elements[id];
    }
    const dummyEl = { id: '', innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false,
      classList: classList(), closest: () => ({ hidden: false, querySelector: () => null }),
      parentElement: null, querySelectorAll: () => [], querySelector: () => null,
      addEventListener: () => {}, setAttribute: () => {}, getAttribute: () => null, insertAdjacentHTML: () => {} };
    const docListeners = {};
    const doc = {
      documentElement: { dataset: { theme: 'light' }, lang: '' },
      getElementById: $, querySelectorAll: () => [], querySelector: () => dummyEl,
      hidden: false, body: dummyEl,
      addEventListener: (type, fn) => { docListeners[type] = fn; },
    };
    const win = { addEventListener: () => {}, outerWidth: 800, outerHeight: 600, document: doc };
    win.window = win;
    const scr = { availWidth: 1920, availHeight: 1080 };
    function ChartMock() { this.destroy = () => {}; this.resize = () => {}; }

    // ---------- 可控 fetch ----------
    const fetchLog = [];
    const routes = {};
    function registerRoute(prefix, handler) { routes[prefix] = handler; }
    function mockFetch(url) {
      fetchLog.push(url);
      const prefix = Object.keys(routes).find((k) => url.startsWith(k));
      if (prefix) {
        return Promise.resolve(routes[prefix](url)).then((body) => ({ ok: true, json: async () => body }));
      }
      return Promise.resolve({ ok: true, json: async () => ({}) });
    }
    const sandbox = {
      window: win, document: doc, screen: scr, $, console,
      setTimeout, clearTimeout, setInterval, clearInterval, fetch: mockFetch,
      getComputedStyle: () => ({ getPropertyValue: () => '' }), Chart: ChartMock,
    };
    vm.createContext(sandbox);

    vm.runInContext(appJs, sandbox);

    (async () => {
      await flushAsync(); await flushAsync();   // 等 init IIFE 完成 (version/settings/state 全落地)

      function makeTotals(over) {
        return Object.assign({
          hit_rate: 0, cache_hit_tokens: 0, uncached_input_tokens: 0,
          total_tokens: 0, total_input_tokens: 0, total_output_tokens: 0, total_reasoning_tokens: 0,
          request_count: 0, session_count: 0, total_cost_usd: null, cost_available: false,
          credits: null, unpriced_requests: 0, local_only: false,
          workbuddy_local: { running: false, error: '' },
        }, over || {});
      }
      function assert(cond, msg) { if (!cond) throw new Error(msg); }
      function deferred() {
        let resolve, reject;
        const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
        return { promise, resolve, reject };
      }

      const overviewCalls = [];
      let trendData = [];
      registerRoute('/api/report/channel-overview', () => {
        const d = deferred();
        overviewCalls.push(d);
        return d.promise;
      });
      registerRoute('/api/report/channel-trend', () => trendData);
      registerRoute('/api/accounts/overview', () => ({ accounts: [] }));
      registerRoute('/api/report/channels', () => ({ rows: [], summary: [{ channel: 'workbuddy', accounts: 1 }, { channel: 'opencode', accounts: 1 }] }));

      function resetCase(ch, range) {
        overviewCalls.length = 0;
        fetchLog.length = 0;
        fakeTimers = [];
        trendData = [];
        vm.runInContext('state.page = "home"; state.channel = "' + ch + '"; state.range = "' + range + '"; state.data = null; state.reportMetric = "tokens";', sandbox);
        vm.runInContext('wbLocalPollStop();', sandbox);
      }

      // init 首屏: applyLang/applyCurrency (homeReportShown=false) 不发报表请求
      assert(!fetchLog.some((u) => u.includes('/api/report/channel-overview') || u.includes('/api/report/windows') || u.includes('/api/report/daily')), 'init 首次 applyLang/applyCurrency 不应提前发报表请求');

      // ===== 场景 1: 空库 running=true -> 500ms 轮询 -> 完成后有数据, 六卡更新, 停表 =====
      resetCase('workbuddy', 'today');
      vm.runInContext('loadDashboard(true, true);', sandbox);
      assert(fetchLog.some((u) => u.startsWith('/api/report/channel-overview') && u.includes('channel=workbuddy')), '应发起 workbuddy overview');
      assert(!fetchLog.some((u) => u.startsWith('/api/report/channel-trend')), 'R54: overview 返回前不得发 trend');
      overviewCalls[0].resolve(makeTotals({ credits: 0, total_cost_usd: null, cost_available: false, local_only: false, workbuddy_local: { running: true, error: '' } }));
      await flushAsync();
      assert(fetchLog.some((u) => u.startsWith('/api/report/channel-trend')), 'overview 完成后应发 trend');
      assert(elements['overview-grid'].innerHTML.length > 0, '六卡应渲染');
      assert(elements['today-empty'].hidden === false, '空 trend 应显示空态占位');
      assert(vm.runInContext('wbLocalPollTimer', sandbox) !== null, 'running=true 应武装轮询');
      assert(pendingTimerCount() === 1, '单渠道同轮只允许一个轮询定时器');
      trendData = [{ hour: 1, input: 100, output: 50, total_input_tokens: 100, total_output_tokens: 50, total_reasoning_tokens: 0, total_tokens: 150, cache_read_tokens: 0, cache_write_tokens: 0 }];
      fireDueTimers();
      await flushAsync();
      assert(overviewCalls.length >= 2, '轮询应触发第二轮 overview');
      overviewCalls[1].resolve(makeTotals({ credits: 0.85, total_cost_usd: 0.05, cost_available: true, local_only: true, unpriced_requests: 0, workbuddy_local: { running: false, error: '' } }));
      await flushAsync();
      assert(elements['overview-grid'].innerHTML.includes('0.85'), '0.85 credits 不截为整数: ' + elements['overview-grid'].innerHTML);
      assert(elements['today-empty'].hidden === true, 'trend 与六卡同一轮更新');
      assert(vm.runInContext('wbLocalPollTimer', sandbox) === null, 'running=false 应停表');
      assert(elements['wb-local-note'].hidden === false, 'workbuddy + local_only 时 #wb-local-note 应显示');

      // ===== 场景 2: 切走 (channel) 后定时器不重取不重绘 =====
      resetCase('workbuddy', 'today');
      vm.runInContext('loadDashboard(true, true);', sandbox);
      overviewCalls[0].resolve(makeTotals({ workbuddy_local: { running: true, error: '' } }));
      await flushAsync();
      assert(vm.runInContext('wbLocalPollTimer', sandbox) !== null, '应武装轮询');
      const nBeforeSwitch = fetchLog.length;
      vm.runInContext('state.channel = "opencode";', sandbox);
      fireDueTimers();
      await flushAsync();
      assert(fetchLog.length === nBeforeSwitch, '切走后不得再发 workbuddy overview: ' + JSON.stringify(fetchLog.slice(nBeforeSwitch)));
      assert(vm.runInContext('wbLocalPollTimer', sandbox) === null, '切走后轮询应停止');

      // ===== 场景 3: 切页 (page) 后定时器不重取 =====
      resetCase('workbuddy', 'today');
      vm.runInContext('loadDashboard(true, true);', sandbox);
      overviewCalls[0].resolve(makeTotals({ workbuddy_local: { running: true, error: '' } }));
      await flushAsync();
      const nBeforePage = fetchLog.length;
      vm.runInContext('state.page = "stats";', sandbox);
      fireDueTimers();
      await flushAsync();
      assert(fetchLog.length === nBeforePage, '切页后不得再发 workbuddy overview: ' + JSON.stringify(fetchLog.slice(nBeforePage)));
      assert(vm.runInContext('wbLocalPollTimer', sandbox) === null, '切页后轮询应停止');

      // ===== 场景 4: 迟到 (seq 过期) 响应不绘制不重设轮询 =====
      resetCase('workbuddy', 'today');
      vm.runInContext('loadDashboard(true, true);', sandbox);   // seq N
      vm.runInContext('loadDashboard(true, true);', sandbox);   // seq N+1 覆盖
      overviewCalls[0].resolve(makeTotals({ credits: 12345, workbuddy_local: { running: true, error: '' } }));
      await flushAsync();
      assert(!elements['overview-grid'].innerHTML.includes('12345'), '迟到 overview 不得绘制');
      assert(vm.runInContext('wbLocalPollTimer', sandbox) === null, '迟到响应不得武装轮询');
      overviewCalls[1].resolve(makeTotals({ credits: 0.85, workbuddy_local: { running: false, error: '' } }));
      await flushAsync();
      assert(elements['overview-grid'].innerHTML.includes('0.85'), '当前响应应正常绘制');

      // ===== 场景 5: all 全渠道并发不重复调度; running=false 停表 =====
      resetCase('all', 'today');
      let wbRunning = true;
      registerRoute('/api/report/windows', () => ({ today: { tokens: 0, cost: null }, yesterday: { tokens: 0, cost: null }, '7d': { tokens: 0, cost: null }, '30d': { tokens: 0, cost: null }, compare: { pct: null, spike: false, insufficient_sample: true, excluded_channels: [] }, channel_count: 0, account_count: 0, workbuddy_local: { running: wbRunning, error: '' }, data_since: null }));
      registerRoute('/api/report/daily', () => ({ series: {}, labels: [], metric: 'tokens', workbuddy_local: { running: wbRunning, error: '' } }));
      registerRoute('/api/report/hourly', () => ({ series: {}, labels: [], workbuddy_local: { running: wbRunning, error: '' } }));
      registerRoute('/api/dashboard', () => ({ totals: { total_tokens: 0, total_input_tokens: 0, total_output_tokens: 0, request_count: 0, total_cost_usd: null, request_count_exact: true, cost_partial: false }, workbuddy_local: { running: wbRunning, error: '' } }));
      registerRoute('/api/zcode/quota', () => null);
      vm.runInContext('loadDashboard(true, true);', sandbox);
      await flushAsync();
      assert(vm.runInContext('wbLocalPollTimer', sandbox) !== null, 'all 任一响应 running=true 应武装轮询');
      assert(pendingTimerCount() === 1, '同轮 all 并发不重复调度, 只允许一个定时器');
      wbRunning = false;
      fireDueTimers();
      await flushAsync();
      assert(pendingTimerCount() === 0, 'running=false 应停表');

      // ===== 场景 6: applyCurrency/applyLang 首页 workbuddy 重取 (货币/语言随动) =====
      resetCase('workbuddy', 'today');
      vm.runInContext('loadDashboard(true, true);', sandbox);
      overviewCalls[0].resolve(makeTotals({ total_cost_usd: 0.05, cost_available: true, credits: 5, workbuddy_local: { running: false, error: '' } }));
      await flushAsync();
      assert(vm.runInContext('homeReportShown', sandbox) === true, '首页报表渲染后 homeReportShown=true');
      assert(elements['overview-grid'].innerHTML.includes('\u00a5'), 'CNY 默认货币主值应含 ¥: ' + elements['overview-grid'].innerHTML);
      const nCur = fetchLog.length;
      vm.runInContext('applyCurrency("USD");', sandbox);
      assert(fetchLog.length > nCur, 'applyCurrency 应重取首页报表: ' + JSON.stringify(fetchLog.slice(nCur)));
      overviewCalls[1].resolve(makeTotals({ total_cost_usd: 0.05, cost_available: true, credits: 5, workbuddy_local: { running: false, error: '' } }));
      await flushAsync();
      assert(elements['overview-grid'].innerHTML.includes('$0.0500'), 'USD 货币主值应显示美元: ' + elements['overview-grid'].innerHTML);
      const nLang = fetchLog.length;
      vm.runInContext('applyLang("en");', sandbox);
      assert(fetchLog.length > nLang, 'applyLang 应重取首页报表: ' + JSON.stringify(fetchLog.slice(nLang)));
      overviewCalls[2].resolve(makeTotals({ total_cost_usd: 0.05, cost_available: true, credits: 5, workbuddy_local: { running: false, error: '' } }));
      await flushAsync();
      assert(elements['overview-grid'].innerHTML.includes('Credits'), '英文积分标签应随语言: ' + elements['overview-grid'].innerHTML);

      // ===== 场景 7: document.hidden 停表; 回到前台 home/workbuddy 重取一次 =====
      const beforeVis = fetchLog.length;
      doc.hidden = true;
      docListeners['visibilitychange']();
      assert(vm.runInContext('wbLocalPollTimer', sandbox) === null, 'document.hidden 应停表');
      doc.hidden = false;
      docListeners['visibilitychange']();
      assert(fetchLog.length > beforeVis, '回到前台应重取一次');

      console.log("OK");
    })().catch((e) => { console.error(e); process.exit(1); });
    """
    res = subprocess.run([node_bin, "-e", js_code], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"Node verification failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "OK" in res.stdout


def test_workbuddy_local_render_contracts_via_node():
    """Step 8a/9 渲染契约 (Node VM): 0.85 credits 不截断 / 全未知费用不显示假 $0 /
    unpriced 提示 / 本地 vs 远程来源提示不同 / #wb-local-note 显隐切换."""
    import os
    import shutil
    import subprocess
    node_bin = shutil.which("node") or (r"D:\Program Files\nodejs\node.exe" if os.path.exists(r"D:\Program Files\nodejs\node.exe") else None)
    if not node_bin:
        pytest.skip("Node.js not available in environment")

    js_code = r"""
    const fs = require('fs');
    const vm = require('vm');
    const path = require('path');
    const appJs = fs.readFileSync(path.join(process.cwd(), 'app/web/app.js'), 'utf8');

    const elements = {};
    function classList() { return { add() {}, remove() {}, toggle() {}, contains() { return false; } }; }
    function $(id) {
      if (!elements[id]) {
        elements[id] = {
          id, innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false,
          classList: classList(), closest: () => ({ hidden: false, querySelector: () => null }),
          parentElement: null, querySelectorAll: () => [], querySelector: () => null,
          addEventListener: () => {}, setAttribute: () => {}, getAttribute: () => null,
          insertAdjacentHTML: () => {},
        };
      }
      return elements[id];
    }
    const dummyEl = { id: '', innerHTML: '', textContent: '', style: {}, title: '', dataset: {}, hidden: false,
      classList: classList(), closest: () => ({ hidden: false, querySelector: () => null }),
      parentElement: null, querySelectorAll: () => [], querySelector: () => null,
      addEventListener: () => {}, setAttribute: () => {}, getAttribute: () => null, insertAdjacentHTML: () => {} };
    const doc = {
      documentElement: { dataset: { theme: 'light' }, lang: '' },
      getElementById: $, querySelectorAll: () => [], querySelector: () => dummyEl,
      hidden: false, body: dummyEl, addEventListener: () => {},
    };
    const win = { addEventListener: () => {}, outerWidth: 800, outerHeight: 600, document: doc };
    win.window = win;
    const scr = { availWidth: 1920, availHeight: 1080 };
    function ChartMock() { this.destroy = () => {}; this.resize = () => {}; }
    const sandbox = {
      window: win, document: doc, screen: scr, $, console,
      setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
      fetch: async () => ({ ok: true, json: async () => ({}) }),
      getComputedStyle: () => ({ getPropertyValue: () => '' }), Chart: ChartMock,
    };
    vm.createContext(sandbox);
    vm.runInContext(appJs, sandbox);

    (async () => {
      await new Promise((r) => setImmediate(r));
      await new Promise((r) => setImmediate(r));

      function makeTotals(over) {
        return Object.assign({
          hit_rate: 0, cache_hit_tokens: 0, uncached_input_tokens: 0,
          total_tokens: 0, total_input_tokens: 0, total_output_tokens: 0, total_reasoning_tokens: 0,
          request_count: 0, session_count: 0, total_cost_usd: null, cost_available: false,
          credits: null, unpriced_requests: 0, local_only: false,
          workbuddy_local: { running: false, error: '' },
        }, over || {});
      }
      function assert(cond, msg) { if (!cond) throw new Error(msg); }
      function renderOverview(over, source) {
        vm.runInContext('renderOverview(' + JSON.stringify(makeTotals(over)) + ', ' + JSON.stringify(source) + ');', sandbox);
      }

      // 0.85 credits 不截为整数; 估算徽章 (cost_available=true) + wbCostEstimated 提示
      renderOverview({ credits: 0.85, total_cost_usd: 0.05, cost_available: true, local_only: true, unpriced_requests: 0 }, 'workbuddy');
      let g = elements['overview-grid'].innerHTML;
      assert(g.includes('0.85'), '0.85 credits 不截为整数: ' + g);
      assert(g.includes('按本地定价表估算'), '应显示 wbCostEstimated 提示: ' + g);
      assert(g.includes('est-badge'), 'cost_available=true 应挂估算徽章: ' + g);

      // 全未知费用: 主值 — (不是假 $0), 不挂估算徽章
      renderOverview({ credits: 5, total_cost_usd: null, cost_available: false, unpriced_requests: 0 }, 'workbuddy');
      g = elements['overview-grid'].innerHTML;
      assert(g.includes('\u2014'), '未知费用主值应为 —: ' + g);
      assert(!g.includes('$0'), '未知费用不得显示假 $0: ' + g);
      assert(!g.includes('est-badge'), 'cost_available=false 不得挂估算徽章: ' + g);

      // unpriced_requests > 0 -> wbUnpricedModels 提示
      renderOverview({ credits: 5, total_cost_usd: 0.05, cost_available: true, unpriced_requests: 3, local_only: true }, 'workbuddy');
      g = elements['overview-grid'].innerHTML;
      assert(g.includes('部分模型缺少有效定价'), '应显示 wbUnpricedModels 提示: ' + g);

      // 渠道明细表: 本地 vs 远程来源提示不同
      const localRow = { channel: 'workbuddy', tokens: 100, input: 60, output: 40, cache_read: 10, requests: 5, cost: 0.05, credits: 0.85, local_only: true, cost_partial: false, data_since: null };
      vm.runInContext('renderChannelTable(' + JSON.stringify([localRow]) + ', []);', sandbox);
      const lt = elements['report-table'].innerHTML;
      assert(lt.includes('本机用量'), '本地行应显示 wbLocalOnly: ' + lt);
      assert(lt.includes('0.85'), '本地行 credits 0.85 不截断: ' + lt);
      const remoteRow = JSON.parse(JSON.stringify(localRow)); remoteRow.local_only = false;
      vm.runInContext('renderChannelTable(' + JSON.stringify([remoteRow]) + ', []);', sandbox);
      const rt = elements['report-table'].innerHTML;
      assert(rt.includes('远程积分记录'), '远程行应显示 wbRemoteCreditsOnly: ' + rt);
      assert(!rt.includes('本机用量'), '远程行不得显示 wbLocalOnly: ' + rt);

      // #wb-local-note 显隐: workbuddy+local_only 显示; 其他渠道 / 非本地隐藏
      renderOverview({ local_only: true }, 'workbuddy');
      assert(elements['wb-local-note'].hidden === false, 'workbuddy+local_only 应显示 #wb-local-note');
      renderOverview({ local_only: true }, 'opencode');
      assert(elements['wb-local-note'].hidden === true, '其他渠道应隐藏 #wb-local-note');
      renderOverview({ local_only: false }, 'workbuddy');
      assert(elements['wb-local-note'].hidden === true, 'workbuddy 非本地应隐藏 #wb-local-note');

      console.log("OK");
    })().catch((e) => { console.error(e); process.exit(1); });
    """
    res = subprocess.run([node_bin, "-e", js_code], cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8")
    assert res.returncode == 0, f"Node verification failed:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
    assert "OK" in res.stdout

