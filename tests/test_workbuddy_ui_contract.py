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
