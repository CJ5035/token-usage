/* GoGauge - 4 页 (首页/用量统计/设置/关于) + 双主题 + 中英国际化 */
"use strict";

const $ = (id) => document.getElementById(id);

/* ================= 国际化 ================= */
const I18N = {
  zh: {
    syncing: "同步中", themeDark: "暗色", themeLight: "亮色", refresh: "刷新",
    homeTitle: "用量统计总览", today: "今天", d7: "近7天", d30: "近30天", all: "全部",
    overviewTitle: "用量概览", followRange: "数据跟随时间范围",
    todayTrend: "今日趋势", hours24: "24 小时",
    statsTitle: "用量统计", tokenBreakdown: "Token 构成",
    modelUsage: "模型用量", input: "输入", output: "输出", cost: "成本",
    usageTrend: "用量趋势", usageRecords: "使用记录", allModels: "全部模型",
    recordsPage: "使用记录",
    sessionUsage: "会话用量", colSession: "会话", colKey: "Key 名称", colLastUsed: "最后使用", colRequests: "请求/Token", unassigned: "未归属",
    accountOverview: "账户总览", costTrend7d: "7 日费用趋势对比",
    todayTotalReq: "今日总请求", todayTotalTokens: "今日总 TOKEN", todayTotalCost: "今日总费用", todayTotalInput: "今日总输入",
    activeAccount: "当前活跃", quotaNotReady: "配额获取中…",
    overviewPanel: "账户总览面板", overviewPanelDesc: "侧边栏显示多账户总览入口，聚合展示各账户配额与用量",
    setUpdate: "软件更新", currentVersion: "当前版本", checkUpdate: "检查更新", checkUpdateDesc: "检查 GitHub 上是否有新版本", checkUpdateBtn: "检查更新",
    checkingUpdate: "检查中…", updateFound: "发现新版本", updateNone: "已是最新版本", updateFailed: "检查更新失败", goDownload: "前往下载",
    colTime: "时间", colModel: "模型", colInput: "输入", colOutput: "输出",
    colReasoning: "推理", colCacheRead: "缓存读", colCost: "费用", colPlan: "PLAN",
    prev: "上一页", next: "下一页",
    settingsTitle: "设置", setAccount: "OpenCode 账户", setLoginState: "登录状态",
    setWorkspace: "工作区", setLoginMethod: "登录方式",
    loginMethodDesc: "内置浏览器 (WebView2) 打开官方授权页，自动回填",
    relogin: "重新登录", logout: "退出登录",
    setAutoSync: "自动同步", autoSync: "自动增量同步", autoSyncDesc: "按间隔拉取最新用量记录",
    syncInterval: "同步间隔", syncIntervalDesc: "多久自动同步一次",
    min1: "1 分钟", min5: "5 分钟", min15: "15 分钟", min30: "30 分钟",
    syncRange: "同步范围", syncRangeDesc: "本地保留与首次拉取的历史窗口；\"所有\"= 拉取全部（500 页保险）",
    d30short: "30天", d60: "60天", d90: "90天", d180: "180天",
    fullSync: "立即全量同步", fullSyncDesc: "重新拉取历史记录，补全数据", startFullSync: "开始全量同步",
    setAppearance: "外观", theme: "主题", themeDesc: "亮色 / 深色，顶栏按钮快捷切换",
    light: "浅色", dark: "深色", currency: "默认货币", currencyDesc: "费用主显示货币（实时汇率）",
    language: "语言 / Language", languageDesc: "界面显示语言",
    setData: "数据", dataDir: "数据目录", syncInfo: "同步记录",
    aboutTitle: "关于", aboutIntro: "简介",
    introText: "是一款本地优先的 OpenCode Go 用量面板：配额窗口、Token 构成、模型排行与使用记录整理在同一处，打开即见。所有数据仅保存在本地，登录凭证只用于同步官方接口。",
    aboutFeatures: "功能", feat1: "配额窗口实时监控（滚动 5 小时 / 每周 / 每月）",
    feat2: "今日用量与 24 小时趋势", feat3: "各模型 Token 消耗排行与用量趋势",
    feat4: "详细使用记录分页浏览（10 条/页）", feat5: "自动同步数据，无需手动刷新",
    aboutTech: "技术栈", aboutLinks: "链接", aboutThanks: "致谢", thanksText: "数据提供",
    pageFoot: "{version} · GoGauge · 数据仅保存在本地 · 数据提供 OpenCode",
    loginTitle: "连接 OpenCode Go",
    welcomeDesc: "本地优先的 OpenCode Go 用量仪表盘 — 配额窗口、Token 构成、模型排行、使用记录，打开即见。",
    welcomeFeat1: "配额实时监控（5 小时 / 每周 / 每月）",
    welcomeFeat2: "Token 全维度统计与 24 小时趋势",
    welcomeFeat3: "数据仅保存在本机，安全私密",
    loginBtn: "立即登录",
    loginNote: "点击后将打开 OpenCode Go 官方授权页完成登录。",
    quitApp: "退出应用", manageLocalData: "管理本地数据",
    rolling: "滚动用量", weekly: "每周用量", monthly: "每月用量",
    remaining: "剩余", used: "已用", resetsIn: "重置于",
    hitRate: "缓存命中率", hitAmount: "缓存命中量", totalTokens: "总 TOKEN 消耗",
    totalRequests: "总请求", totalCost: "总费用", sessions: "会话数",
    hit: "命中", miss: "未命中", pctOfInput: "占输入", inclCache: "含缓存命中",
    currentRange: "当前范围", avgPer: "均", perReq: "/次", dedup: "去重 sessionID",
    noData: "暂无记录", loadFailed: "加载失败", requestTimeout: "请求超时，请检查网络后重试", retry: "重试", totalN: "共", items: "条",
    pageOf: "第", ofPages: "页",
    loggedIn: "已登录", notLoggedIn: "未登录", connected: "已连接", notConnected: "未连接",
    lastSync: "上次同步", records: "条记录", updatedAt: "更新于",
    justNow: "刚刚", minAgo: "分钟前", hrAgo: "小时前", dayAgo: "天前", never: "从未同步",
    day: "天", hour: "小时", minute: "分钟", soon: "即将重置",
    dUnit: "天", hUnit: "小时", mUnit: "分钟",
    confirm: "确认", cancel: "取消", ok: "确定",
    fullSyncConfirm: "将重新拉取历史记录（按同步范围），确定开始？", startSync: "开始同步",
    quit: "退出",
    quotaFail: "配额获取失败", retryTip: "点击右上角刷新重试",
    syncIntervalSet: "同步间隔已设为", syncRangeUpdated: "同步范围已更新，下次全量同步生效",
    trendHint: "30 天", totalTokenHint: "含缓存命中",
    sourceBai: "BAI", quotaPointsBalance: "余额 {n} 积分", quotaPointsExpiring: "其中 {n} 即将到期", estimateTip: "估算口径：成本为本地定价估算，非实际扣费", estimateBadge: "估算",
    setUsers: "用户管理", addUser: "添加用户", addUserBai: "添加 BAI 账号", addUserTip: "登录新的 OpenCode Go 账号并保存到本机",
    userSwitchTip: "切换用户", userCountTip: "已登录用户数",
    switchTo: "切换", currentUserBadge: "当前", renameBtn: "重命名", deleteUser: "删除", loginRow: "登录",
    renameTitle: "重命名用户", save: "保存", deleteUserTitle: "删除用户",
    deleteUserConfirm: "确定删除用户「{name}」？其本地用量数据与同步记录将一并清除，且无法恢复。",
    userDeleted: "用户已删除", userRenamed: "已重命名", switchedAccount: "已切换账号",
    noUsers: "暂无账号，点击右上角「添加用户」登录",
    setToCurrent: "设为当前", loggedOut: "已退出登录",
    logoutUserConfirm: "将退出「{name}」，仅清除登录凭证，本地用量数据保留。确定？",
    sourceCommandcode: "CommandCode", loginCommandcode: "登录 Command Code",
    ccSummaryTitle: "账期汇总", ccRequests: "请求", ccTokens: "Token", ccCost: "费用", ccSuccessRate: "成功率",
    ccHistoryNote: "API 仅提供最近 24 小时明细，更早历史自接入起本地积累",
    zcodeQuotaTitle: "GLM Coding Plan · ZCode",
    zcodeQuotaGuide: "未检测到 ZCode 登录凭证。请在 ZCode 客户端登录 GLM Coding Plan 订阅，额度将自动显示",
    zcodeQuotaFail: "ZCode 额度获取失败",
    mcpMonthly: "MCP 月度",
    zcodeStatsTitle: "ZCode 本地用量",
    zcodeStatsMissing: "未检测到 ZCode 本地数据（~/.zcode/cli/db/db.sqlite）",
    zcodeCostHint: "费用为按量价目估算值（订阅套餐实际不按此扣费），未收录定价的模型按 0 计算",
    zcodeChannel: "渠道", zcodeModel: "模型",
    zcodeAvgTps: "平均输出速度", zcodeAvgTtft: "平均首字延迟",
    zcodeEstCost: "估算费用", zcodeHitRate: "命中率",
    zcodeNoData: "暂无数据", zcodeTimes: "次",
    dshStatsTitle: "DSH 本地用量",
    dshStatsMissing: "未检测到 DSH 本地数据（~/.dsh/sessions）",
    dshSegTotal: "总量", dshSegToday: "今日",
    dshTpsHint: "平均 {tps} tok/s",
    dshTodayTableNote: "渠道/模型明细仅提供总量口径",
    dshKpiSessions: "会话数", dshKpiInput: "总输入(含缓存)", dshKpiOutput: "总输出",
    dshKpiTodayInput: "今日输入(含缓存)", dshKpiTodayOutput: "今日输出", dshKpiTodaySpeed: "今日秒速",
    dshColSteps: "步数", dshColTps: "平均 tok/s",
    claudecodeStatsTitle: "Claude Code 本地用量",
    claudecodeStatsMissing: "未检测到 Claude Code 本地数据（~/.claude/projects）",
    claudecodeCostHint: "费用为按量价目估算值（订阅套餐实际不按此扣费），未收录定价的模型按 0 计算",
    claudecodeKpiOutput: "输出 TOKEN",
    channelAll: "全部渠道", yesterday: "昨天", vsSame: "vs 昨日同时段",
    sampleInsufficient: "样本不足", dailyAvg: "日均", scopeHint: "{n} 渠道 · {m} 账号",
    accountsUnit: "账号", quotaBarTitle: "各渠道配额",
    stackTitle: "分渠道消耗趋势", donutTitle: "渠道占比", chTableTitle: "渠道明细", channel: "渠道",
    reportEmpty: "暂无数据", segTokens: "Token",
    dataSinceToday: "仅今日", dataSince: "数据自",
  },
  en: {
    syncing: "Syncing", themeDark: "Dark", themeLight: "Light", refresh: "Refresh",
    homeTitle: "Usage Overview", today: "Today", d7: "7 Days", d30: "30 Days", all: "All",
    overviewTitle: "Usage Overview", followRange: "Follows selected range",
    todayTrend: "Today's Trend", hours24: "24 Hours",
    statsTitle: "Usage Stats", tokenBreakdown: "Token Breakdown",
    modelUsage: "Model Usage", input: "Input", output: "Output", cost: "Cost",
    usageTrend: "Usage Trend", usageRecords: "Usage Records", allModels: "All Models",
    recordsPage: "Records",
    sessionUsage: "Session Usage", colSession: "Session", colKey: "Key Name", colLastUsed: "Last Used", colRequests: "Requests/Token", unassigned: "Unassigned",
    accountOverview: "Accounts Overview", costTrend7d: "7-Day Cost Trend",
    todayTotalReq: "Today Requests", todayTotalTokens: "Today Tokens", todayTotalCost: "Today Cost", todayTotalInput: "Today Input",
    activeAccount: "Active", quotaNotReady: "Fetching quota…",
    overviewPanel: "Accounts Panel", overviewPanelDesc: "Show multi-account overview entry in sidebar",
    setUpdate: "Software Update", currentVersion: "Current Version", checkUpdate: "Check Updates", checkUpdateDesc: "Check GitHub for new versions", checkUpdateBtn: "Check Updates",
    checkingUpdate: "Checking…", updateFound: "New Version Available", updateNone: "You're up to date", updateFailed: "Check failed", goDownload: "Go to Download",
    colTime: "Time", colModel: "Model", colInput: "Input", colOutput: "Output",
    colReasoning: "Reasoning", colCacheRead: "Cache Read", colCost: "Cost", colPlan: "PLAN",
    prev: "Prev", next: "Next",
    settingsTitle: "Settings", setAccount: "OpenCode Account", setLoginState: "Login Status",
    setWorkspace: "Workspace", setLoginMethod: "Login Method",
    loginMethodDesc: "Built-in browser (WebView2) opens the official auth page and auto-fills",
    relogin: "Re-login", logout: "Logout",
    setAutoSync: "Auto Sync", autoSync: "Auto incremental sync", autoSyncDesc: "Fetch latest usage records at interval",
    syncInterval: "Sync Interval", syncIntervalDesc: "How often to auto sync",
    min1: "1 min", min5: "5 min", min15: "15 min", min30: "30 min",
    syncRange: "Sync Range", syncRangeDesc: "Local history window for initial fetch; \"All\" = fetch everything (500-page safety cap)",
    d30short: "30d", d60: "60d", d90: "90d", d180: "180d",
    fullSync: "Full Sync Now", fullSyncDesc: "Re-fetch history records to fill gaps", startFullSync: "Start Full Sync",
    setAppearance: "Appearance", theme: "Theme", themeDesc: "Light / Dark, quick toggle in top bar",
    light: "Light", dark: "Dark", currency: "Currency", currencyDesc: "Primary currency for costs (live FX rate)",
    language: "Language", languageDesc: "Interface language",
    setData: "Data", dataDir: "Data Directory", syncInfo: "Sync History",
    aboutTitle: "About", aboutIntro: "Intro",
    introText: "is a local-first OpenCode Go usage dashboard: quota windows, token breakdown, model ranking and usage records in one place. All data stays on your machine; credentials are only used to sync official APIs.",
    aboutFeatures: "Features", feat1: "Quota window monitoring (5h rolling / weekly / monthly)",
    feat2: "Today's usage with 24-hour trend", feat3: "Per-model token ranking and usage trend",
    feat4: "Paginated usage records (10 per page)", feat5: "Auto sync — no manual refresh needed",
    aboutTech: "Tech Stack", aboutLinks: "Links", aboutThanks: "Thanks", thanksText: "Data provided by",
    pageFoot: "{version} · GoGauge · Local-only data · Data by OpenCode",
    loginTitle: "Connect OpenCode Go",
    welcomeDesc: "A local-first OpenCode Go usage dashboard — quota windows, token breakdown, model ranking and usage records in one place.",
    welcomeFeat1: "Real-time quota monitoring (5h / weekly / monthly)",
    welcomeFeat2: "Full token stats with 24-hour trend",
    welcomeFeat3: "All data stays on your machine — private & safe",
    loginBtn: "Login Now",
    loginNote: "Clicking opens the official OpenCode Go authorization page.",
    quitApp: "Quit App", manageLocalData: "Manage local data",
    rolling: "Rolling Usage", weekly: "Weekly Usage", monthly: "Monthly Usage",
    remaining: "Remaining", used: "Used", resetsIn: "Resets in",
    hitRate: "Cache Hit Rate", hitAmount: "Cache Hits", totalTokens: "Total Tokens",
    totalRequests: "Requests", totalCost: "Total Cost", sessions: "Sessions",
    hit: "hit", miss: "missed", pctOfInput: "of input", inclCache: "incl. cache hits",
    currentRange: "current range", avgPer: "avg", perReq: "/req", dedup: "dedup sessionID",
    noData: "No records", loadFailed: "Failed to load", requestTimeout: "Request timed out. Check your network and retry.", retry: "Retry", totalN: "Total", items: "records",
    pageOf: "Page", ofPages: "of",
    loggedIn: "Logged in", notLoggedIn: "Not logged in", connected: "Connected", notConnected: "Not connected",
    lastSync: "Last sync", records: "records", updatedAt: "Updated",
    justNow: "just now", minAgo: "min ago", hrAgo: "hr ago", dayAgo: "d ago", never: "Never synced",
    day: "d", hour: "h", minute: "m", soon: "resets soon",
    dUnit: "d", hUnit: "h", mUnit: "m",
    confirm: "Confirm", cancel: "Cancel", ok: "OK",
    fullSyncConfirm: "This will re-fetch all history records (per sync range). Continue?", startSync: "Start Sync",
    quit: "Logout",
    quotaFail: "Quota fetch failed", retryTip: "Click refresh in top bar to retry",
    syncIntervalSet: "Sync interval set to", syncRangeUpdated: "Sync range updated, takes effect on next full sync",
    trendHint: "30 days", totalTokenHint: "incl. cache hits",
    sourceBai: "BAI", quotaPointsBalance: "Balance {n} points", quotaPointsExpiring: "of which {n} expiring", estimateTip: "Estimate: cost is a local price estimate, not actual billing", estimateBadge: "Est.",
    setUsers: "User Management", addUser: "Add User", addUserBai: "Add BAI Account", addUserTip: "Sign in with another OpenCode Go account",
    userSwitchTip: "Switch user", userCountTip: "Logged-in users",
    switchTo: "Switch", currentUserBadge: "Active", renameBtn: "Rename", deleteUser: "Delete", loginRow: "Sign in",
    renameTitle: "Rename User", save: "Save", deleteUserTitle: "Delete User",
    deleteUserConfirm: "Delete user \"{name}\"? Their local usage data and sync history will be removed permanently.",
    userDeleted: "User deleted", userRenamed: "Renamed", switchedAccount: "Account switched",
    noUsers: "No accounts yet — click \"Add User\" to sign in",
    setToCurrent: "Make Active", loggedOut: "Signed out",
    logoutUserConfirm: "Sign out \"{name}\"? This only clears the credential — local usage data is kept. Continue?",
    sourceCommandcode: "CommandCode", loginCommandcode: "Add CommandCode Account",
    ccSummaryTitle: "Billing Summary", ccRequests: "Requests", ccTokens: "Tokens", ccCost: "Cost", ccSuccessRate: "Success Rate",
    ccHistoryNote: "API provides only the last 24h of details; older history accumulates locally since first sync",
    zcodeQuotaTitle: "GLM Coding Plan · ZCode",
    zcodeQuotaGuide: "No ZCode credentials detected. Sign in to a GLM Coding Plan subscription in the ZCode client and quotas will appear automatically",
    zcodeQuotaFail: "Failed to fetch ZCode quota",
    mcpMonthly: "MCP Monthly",
    zcodeStatsTitle: "ZCode Local Usage",
    zcodeStatsMissing: "ZCode local data not found (~/.zcode/cli/db/db.sqlite)",
    zcodeCostHint: "Costs are pay-as-you-go estimates (subscriptions are not actually billed this way); models without pricing are counted as 0",
    zcodeChannel: "Channel", zcodeModel: "Model",
    zcodeAvgTps: "Avg Output Speed", zcodeAvgTtft: "Avg First-Token Latency",
    zcodeEstCost: "Est. Cost", zcodeHitRate: "Hit Rate",
    zcodeNoData: "No data", zcodeTimes: "times",
    dshStatsTitle: "DSH Local Usage",
    dshStatsMissing: "DSH local data not found (~/.dsh/sessions)",
    dshSegTotal: "Total", dshSegToday: "Today",
    dshTpsHint: "Avg {tps} tok/s",
    dshTodayTableNote: "Channel/model details are totals only",
    dshKpiSessions: "Sessions", dshKpiInput: "Total Input (incl. cache)", dshKpiOutput: "Total Output",
    dshKpiTodayInput: "Today Input (incl. cache)", dshKpiTodayOutput: "Today Output", dshKpiTodaySpeed: "Today Speed",
    dshColSteps: "Steps", dshColTps: "Avg tok/s",
    claudecodeStatsTitle: "Claude Code Local Usage",
    claudecodeStatsMissing: "Claude Code local data not found (~/.claude/projects)",
    claudecodeCostHint: "Costs are pay-as-you-go estimates (subscriptions are not actually billed this way); models without pricing are counted as 0",
    claudecodeKpiOutput: "Output Tokens",
    channelAll: "All Channels", yesterday: "Yesterday", vsSame: "vs yesterday same time",
    sampleInsufficient: "Low sample", dailyAvg: "Daily avg", scopeHint: "{n} channels · {m} accounts",
    accountsUnit: " acct", quotaBarTitle: "Channel Quotas",
    stackTitle: "Usage by Channel", donutTitle: "Channel Share", chTableTitle: "Channel Breakdown", channel: "Channel",
    reportEmpty: "No data yet", segTokens: "Tokens",
    dataSinceToday: "Today only", dataSince: "Data since",
  },
};
let lang = "zh";
function t(key) { return (I18N[lang] && I18N[lang][key]) || I18N.zh[key] || key; }

let state = {
  page: "home",
  range: "today",
  statsRange: "7d",
  modelDim: "input",
  dshDim: "total",
  data: null,
  exchangeRate: 7.0,
  currency: "CNY",
  darkMode: false,
  syncTimer: null,
  quotaRetryTimer: null,
  ovRetryTimer: null,
  records: { page: 1, pageSize: 7, total: 0, model: "" },
  sessions: { page: 1, pageSize: 7, total: 0 },
  settings: { sync_interval_sec: 300, window_days: 60, auto_sync: true },
  channel: "all",        // 首页渠道 tab; 冷启动强制 all (spec v2)
  reportMetric: "tokens",
};

const COLOR = { input: "#4f8ef7", output: "#22c55e", reasoning: "#a78bfa", cache: "#06b6d4", cost: "#d97706" };
const QUOTA_LABEL = { "5h Rolling": () => t("rolling"), "Weekly": () => t("weekly"), "Monthly": () => t("monthly"), "MCP Monthly": () => t("mcpMonthly") };
const PLAN_BADGE = { lite: "GO", sub: "GO", byok: "BYOK" };

/* ---------------- 格式化 ---------------- */
function fmtTokens(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(Math.round(n));
}
function fmtInt(n) { return Number(n || 0).toLocaleString("en-US"); }
function fmtMoney(usd) {
  usd = Number(usd) || 0;
  if (state.currency === "CNY") {
    const v = usd * state.exchangeRate;
    return "¥" + (v >= 1 ? v.toFixed(2) : v.toFixed(4));
  }
  if (usd >= 1) return "$" + usd.toFixed(2);
  if (usd > 0) return "$" + usd.toFixed(4);
  return "$0";
}
function fmtUsd(v) {
  // USD 额度固定美元显示 (commandcode 配额池/账期费用为美元计价, 不随默认货币换算)
  v = Number(v) || 0;
  if (v >= 1) return "$" + v.toFixed(2);
  if (v > 0) return "$" + v.toFixed(4);
  return "$0";
}
function fmtDur(sec) {
  sec = Math.max(0, Number(sec) || 0);
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d > 0) return d + " " + t("dUnit") + " " + h + " " + t("hUnit");
  if (h > 0) return h + " " + t("hUnit") + " " + m + " " + t("mUnit");
  if (m > 0) return m + " " + t("mUnit");
  return t("soon");
}
function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  const pad = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}
function fmtRelative(iso) {
  if (!iso) return t("never");
  const d = new Date(iso);
  if (isNaN(d)) return t("never");
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return t("justNow");
  if (diff < 3600) return Math.floor(diff / 60) + " " + t("minAgo");
  if (diff < 86400) return Math.floor(diff / 3600) + " " + t("hrAgo");
  return Math.floor(diff / 86400) + " " + t("dayAgo");
}
function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/* ---------------- API ---------------- */
async function api(path, opts = {}) {
  try {
    const resp = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      // 20s 请求超时 (EVOLUTION-3): 防后端阻塞时 fetch 无限挂起;
      // signal 置于 ...opts 前, 调用方传 signal 可覆盖; 老内核无 AbortSignal.timeout 时降级为无超时
      signal: (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") ? AbortSignal.timeout(20000) : undefined,
      ...opts,
    });
    if (!resp.ok) {
      let msg = "HTTP " + resp.status;
      try { const b = await resp.json(); if (b && b.error) msg = b.error; } catch (e) { /* 无 body 或非 JSON 时保持默认 */ }
      throw new Error(msg);
    }
    return resp.json();
  } catch (e) {
    // AbortSignal.timeout 到点 reject DOMException(name="TimeoutError"), 本地化为可读文案
    if (e && e.name === "TimeoutError") throw new Error(t("requestTimeout"));
    throw e;
  }
}

/* ---------------- 语言切换 ---------------- */
function applyLang(l) {
  lang = l === "en" ? "en" : "zh";
  try { localStorage.setItem("gousage-lang", lang); } catch (e) { /* ignore */ }
  document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  // 静态 data-i18n 文案
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("#set-lang-pills .pill").forEach((b) => b.classList.toggle("active", b.dataset.v === lang));
  // 版本号: 唯一来源为后端 /api/version (app/__init__.py), 前端动态获取
  const ver = APP_VERSION ? "v" + APP_VERSION : "GoGauge";
  document.getElementById("about-sub").textContent = `${ver} · OpenCode Go Usage Panel`;
  const pf = document.querySelector('[data-i18n="pageFoot"]');
  if (pf) pf.textContent = t("pageFoot").replace("{version}", ver);
  const sv = document.getElementById("set-version");
  if (sv) sv.textContent = APP_VERSION ? `v${APP_VERSION}` : "—";
  // 动态内容重渲染
  if (state.data) {
    renderAll(state.data);
    renderSettings();
    loadRecords().catch(() => {});
  }
  // ZCode 区块随语言即时重渲染 (复用已拉取数据, 不重发请求)
  if (zcodeQuotaLast && state.page === "home" && state.channel === "zcode") renderZcodeQuota(zcodeQuotaLast);
  if (zcodeSummaryLast) renderZcodeSummary(zcodeSummaryLast);
  if (dshUsageLast) renderDsh(dshUsageLast);
  if (claudecodeSummaryLast) renderClaudecodeSummary(claudecodeSummaryLast);
}

/* ---------------- 弹框 / Toast ---------------- */
function showModal({ title = t("confirm"), message = "", okText = t("ok"), cancelText = t("cancel"), danger = false, onOk }) {
  const overlay = $("modal-overlay");
  $("modal-title").textContent = title;
  $("modal-message").innerHTML = message;
  $("modal-ok").textContent = okText;
  $("modal-cancel").textContent = cancelText;
  $("modal-cancel").hidden = !cancelText;
  const icon = $("modal-icon");
  icon.className = "modal-icon" + (danger ? " danger" : "");
  icon.textContent = danger ? "⚠" : "?";
  overlay.hidden = false;
  const cleanup = () => { overlay.hidden = true; $("modal-ok").onclick = null; $("modal-cancel").onclick = null; };
  $("modal-ok").onclick = () => { cleanup(); onOk && onOk(); };
  $("modal-cancel").onclick = () => { cleanup(); };
}
function toast(msg, type = "ok") {
  const wrap = $("toast-wrap");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, 3200);
}

/* ---------------- 标题栏 ---------------- */
async function pywebviewApi() {
  try { if (window.pywebview && window.pywebview.api) return window.pywebview.api; } catch (e) { /* ignore */ }
  return null;
}
function bindTitlebar() {
  $("tb-min").addEventListener("click", async () => { const a = await pywebviewApi(); if (a) a.minimize(); });
  $("tb-close").addEventListener("click", async () => { const a = await pywebviewApi(); if (a) a.close(); });
  $("tb-theme").addEventListener("click", () => applyDarkMode(document.documentElement.dataset.theme !== "dark"));

  /* 标题栏拖动 (自实现, 替代 pywebview easy_drag):
     easy_drag 的 JS 用 clientX 记起点、screenX 算增量 (DPI 缩放下两坐标系
     不同源), 后端 move() 再乘一次缩放, 高 DPI 屏幕拖动会漂移抽动.
     这里用相邻两次 mousemove 的屏幕增量 (screenX/screenY 物理像素) 交给
     后端 move_by, 后端以同坐标系 SetWindowPos 增量移动, 1:1 跟随.
     关键点:
     1) 增量取相邻事件差值, 不能取按下点差值 — 否则每次都按总位移叠加到
        窗口当前位置, 连续触发会累积放大, 拖远一点就飞出屏幕;
     2) mousemove 频率远高于 js_api 往返速度, 逐事件调用会丢消息/乱序,
        先把增量累积到 pending, 用 requestAnimationFrame 合并成一次
        move_by 再发, 保证每次移动都精确送达. */
  let drag = null;
  let pending = { x: 0, y: 0 };
  let rafId = null;
  function flushDrag() {
    rafId = null;
    if (pending.x === 0 && pending.y === 0) return;
    const dx = pending.x, dy = pending.y;
    pending = { x: 0, y: 0 };
    pywebviewApi().then((a) => { if (a && a.move_by) a.move_by(dx, dy); });
  }
  document.querySelector(".tb").addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    if (e.target.closest("button, a")) return;  // 标题栏控件不触发拖动
    drag = { lx: e.screenX, ly: e.screenY };
    pending = { x: 0, y: 0 };
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!drag) return;
    pending.x += e.screenX - drag.lx;
    pending.y += e.screenY - drag.ly;
    drag.lx = e.screenX;
    drag.ly = e.screenY;
    if (!rafId) rafId = requestAnimationFrame(flushDrag);
  });
  window.addEventListener("mouseup", () => {
    drag = null;
    if (rafId) { cancelAnimationFrame(rafId); rafId = null; }
    flushDrag();  // 释放残留增量, 避免窗口停在半路
  });
}

/* ---------------- 主题 / 货币 ---------------- */
function applyDarkMode(on) {
  state.darkMode = on;
  document.documentElement.dataset.theme = on ? "dark" : "light";
  $("tb-theme").innerHTML = `◐ <span data-i18n="${on ? "themeLight" : "themeDark"}">${on ? t("themeLight") : t("themeDark")}</span>`;
  try { localStorage.setItem("gousage-dark", on ? "1" : "0"); } catch (e) { /* ignore */ }
  syncThemePills();
  refreshIcons();
  rerenderCharts();
}
function syncThemePills() {
  document.querySelectorAll("#set-theme-pills .pill").forEach((b) => b.classList.toggle("active", b.dataset.v === (state.darkMode ? "dark" : "light")));
}
function applyCurrency(cur) {
  state.currency = cur;
  document.querySelectorAll("#set-currency-pills .pill").forEach((b) => b.classList.toggle("active", b.dataset.v === cur));
  try { localStorage.setItem("gousage-currency", cur); } catch (e) { /* ignore */ }
  if (!state.data) return;
  rerenderCharts();
  renderOverview(state.data.totals);
  renderStatsTotal(state.data.totals);
  renderDetail6(state.data.totals);
  loadRecords().catch(() => {});
  if (state.page === "overview") loadOverview(true).catch(() => {});  // 总览页费用随货币即时换算
  if (zcodeSummaryLast) renderZcodeSummary(zcodeSummaryLast);  // ZCode 估算费用随货币即时换算
  if (claudecodeSummaryLast) renderClaudecodeSummary(claudecodeSummaryLast);  // Claude Code 估算费用随货币即时换算
}

/* ---------------- 页面路由 ---------------- */
function switchPage(page) {
  state.page = page;
  document.querySelectorAll(".page").forEach((p) => (p.hidden = true));
  $("page-" + page).hidden = false;
  document.querySelectorAll(".side-item").forEach((b) => b.classList.toggle("active", b.dataset.page === page));
  if (page === "home" || page === "stats") loadDashboard();
  if (page === "stats") loadZcodeSummary().catch(() => {});  // ZCode 本地用量区块
  if (page === "stats") loadDshUsage().catch(() => {});  // DSH 本地用量区块
  if (page === "stats") loadClaudecodeSummary().catch(() => {});  // Claude Code 本地用量区块
  if (page === "overview") loadOverview().catch(() => {});
  if (page === "records") { loadSessions().catch(() => {}); loadRecords().catch(() => {}); }
  if (page === "settings") renderSettings();
}

/* ---------------- 骨架屏 ---------------- */
function renderSkeletons() {
  const sBlock = `<div class="ub skeleton"><div class="sk-line w40"></div><div class="sk-line w20 lg"></div><div class="sk-bar"></div><div class="sk-line w60"></div></div>`;
  $("usage-blocks").innerHTML = sBlock.repeat(3);
  const sKpi = `<div class="card kpi skeleton"><div class="sk-line w30"></div><div class="sk-line w40 lg"></div><div class="sk-line w50"></div></div>`;
  $("overview-grid").innerHTML = sKpi.repeat(6);
  // 趋势图骨架: 保留 canvas, 叠加灰色遮罩 (数据到后移除)
  const trendBox = document.querySelector(".today-trend .chart-box");
  if (trendBox) trendBox.classList.add("sk-box");
  if (!$("stats-total-cards").innerHTML) $("stats-total-cards").innerHTML = sKpi.repeat(4);
  if (!$("stats-detail6").innerHTML) $("stats-detail6").innerHTML = `<div class="tc skeleton"><div class="sk-line w40"></div><div class="sk-line w50 lg"></div><div class="sk-line w30"></div></div>`.repeat(6);
}
/* 加载失败占位 (EVOLUTION-3): 写入 usage-blocks / overview-grid / stats-total-cards
   三区——前两区为 renderSkeletons 无条件赋值, 重试可恢复; stats-total-cards 成功
   路径 renderStatsTotal 无条件覆盖 innerHTML, 占位不影响数据渲染 (其 if(!innerHTML)
   骨架守卫仅使重试加载期短暂显示旧占位而非骨架, 可接受), 该区为 grid 布局, 占位
   以 grid-column:1/-1 通栏; stats-detail6 维持清空; trend 区为 canvas + sk-box
   class 遮罩 (非 innerHTML), 移除 class 即可 */
function renderDashboardError(e) {
  const msg = `${escapeHtml(t("loadFailed"))}: ${escapeHtml((e && e.message) || String(e))}`;
  const errHtml = `<div class="ub ub-error" style="grid-column:1/-1">${msg}<button class="pill" style="margin-left:8px" data-dash-retry>${escapeHtml(t("retry"))}</button></div>`;
  $("usage-blocks").innerHTML = errHtml;
  $("overview-grid").innerHTML = errHtml;
  $("stats-total-cards").innerHTML = errHtml;
  $("stats-detail6").innerHTML = "";
  const trendBox = document.querySelector(".today-trend .chart-box");
  if (trendBox) trendBox.classList.remove("sk-box");
  document.querySelectorAll("[data-dash-retry]").forEach((b) => b.addEventListener("click", () => loadDashboard()));
}

/* ---------------- 数据加载 ---------------- */
let loadSeq = 0;
let chSeq = 0;   // 单渠道响应序号: 快速连点渠道 tab 时丢弃旧响应 (方案4④)
async function loadDashboard(quiet = false) {
  if (state.page === "home") {
    renderChannelTabs();                     // 每次刷新渠道列表(账号增减/删除回退)
    if (state.channel === "all") {
      $("report-all").hidden = false; $("report-single").hidden = true;
      $("report-scope").hidden = false;
      await loadReportAll(quiet);
      return;
    }
    $("report-all").hidden = true; $("report-single").hidden = false;
    // GLM Coding Plan 额度卡只属于 zcode 渠道页签 (问题5):
    // a) 非本页签隐藏; b) 本页签主动渲染 — loadZcodeQuota 仅统计页分支会调,
    // 冷启动直达 zcode 页签时 zcodeQuotaLast 为 null, 必须主动拉取
    $("zcode-quota").hidden = state.channel !== "zcode";
    if (state.channel === "zcode") {
      zcodeQuotaLast ? renderZcodeQuota(zcodeQuotaLast)
                     : loadZcodeQuota().then(() => {   // 迟到响应防护: 请求期间已切走则重新隐藏
                         if (state.channel !== "zcode") $("zcode-quota").hidden = true;
                       });
    }
    $("report-scope").hidden = true;
    // 单渠道: 消耗走 report 接口(与活跃账号无关), 配额块/账期卡走 accounts/overview 逐账号 (spec v5/v8)
    const seq = ++chSeq;                                  // 新增: 快速切渠道时丢弃过期响应 (方案4④)
    $("report-single").classList.add("swapping");         // 新增: 加载提示 (方案4③)
    Promise.all([
      api(`/api/report/channel-overview?range=${state.range}&channel=${state.channel}`),
      api(`/api/report/channel-trend?date=${state.range === "yesterday" ? "yesterday" : "today"}&channel=${state.channel}`),
      api(`/api/accounts/overview`),
    ]).then(([totals, trend, ov]) => {
      if (seq !== chSeq) return;                          // 新增: 过期响应丢弃
      $("report-single").classList.remove("swapping");    // 新增
      const chAccounts = ov.accounts.filter((a) => a.source === state.channel);
      renderQuotaSingle(chAccounts);
      const rangeHint = document.querySelector(".overview .hint");   // 新R1 N13: dsh 仅今日口径提示
      if (rangeHint) rangeHint.textContent = totals.today_only ? t("dataSinceToday") : t("followRange");
      renderOverview(totals, state.channel);          // 概览 6 格: channel_totals 键与 db.totals 对齐 (T5)
      chartToday(trend);                              // 24h input/output 双系列 (spec v8)
      const isCc = state.channel === "commandcode";
      $("cc-summary").hidden = !isCc;
      if (isCc) renderCcAccounts(chAccounts);         // 账期卡逐账号 (spec v5); 全部 tab 不显示
    }).catch((e) => {
      if (seq === chSeq) $("report-single").classList.remove("swapping");   // 新增
      if (!quiet) toast(t("loadFailed") + ": " + e);
    });
    return;   // R5 补: 必须 return, 否则落入现有逻辑 renderAll 双重渲染 (与 Step 2 要求一致)
  }
  const seq = ++loadSeq;
  if (!state.data) renderSkeletons();
  showLoading(true);
  try {
    const range = state.page === "stats" ? state.statsRange : state.range;
    const data = await api(`/api/dashboard?range=${range}`);
    if (seq !== loadSeq) return;
    renderAll(data);
    showLoading(false);
    loadZcodeQuota().catch(() => {});  // ZCode 额度卡: 并发拉取, 失败不阻塞 dashboard
  } catch (e) {
    if (seq === loadSeq) {
      showLoading(false);
      // 失败三态 (EVOLUTION-3): 有数据的静默刷新 (5s 配额重试/重命名后静默刷新)
      // 维持静默不打扰正常数据; 其余 (用户主动加载 / 防御性: 静默但无数据) 渲染错误占位 + 重试
      if (!(quiet && state.data)) renderDashboardError(e);
    }
    if (!quiet) console.error("dashboard load failed", e);
  }
}
let channelTabsCache = { at: 0, data: null };   // 方案4⑤: 切渠道高频触发, 60s 内复用; 已知取舍: 60s 内账号增删后 tab 角标可能过时, 60s 后自愈
function renderChannelTabs() {
  if (channelTabsCache.data && Date.now() - channelTabsCache.at < 60000) {
    renderChannelTabsFrom(channelTabsCache.data);
    return;
  }
  api("/api/report/channels?range=today").then((d) => {
    channelTabsCache = { at: Date.now(), data: d };
    renderChannelTabsFrom(d);
  }).catch(() => {});
}
function renderChannelTabsFrom(d) {
  const tabs = [{ ch: "all", label: t("channelAll") }]
    .concat(d.summary.map((s) => ({ ch: s.channel, label: s.channel, n: s.accounts })));
  $("channel-tabs").innerHTML = tabs.map((x) =>
    `<button class="pill${x.ch === state.channel ? " active" : ""}" data-ch="${x.ch}">${x.label}${x.n > 1 ? ` <small>·${x.n}</small>` : ""}</button>`).join("");
  if (state.channel !== "all" && !d.summary.some((s) => s.channel === state.channel)) switchChannel("all"); // 账号被删回退
}
function showLoading(show) { $("top-loading").hidden = !show; }

/* ---------------- 首页: 用量块 ---------------- */
/* USD 额度窗口块 (commandcode): used/cap 为美元额度, 进度条按 used/total,
   数值固定美元显示 (额度口径, 不随默认货币换算); reset_in_sec 订阅信息不可用时
   可能为 null, fmtDur 内部按 0 处理显示"即将重置" */
function usdWindowHtml(w, extraCls) {
  const used = Number(w.used) || 0;
  const total = Number(w.total) || 0;
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const cls = w.label === "5h Rolling" ? "c-rolling" : w.label === "Weekly" ? "c-week" : "c-month";
  return `<div class="ub ${cls}${extraCls ? " " + extraCls : ""}">
    <div class="ub-head"><span class="ub-l">${(QUOTA_LABEL[w.label] || (() => w.label))()}</span><span class="ub-rem">${t("remaining")} ${fmtUsd(w.remaining)}</span></div>
    <div class="ub-bar"><div class="ub-bar-fill" style="width:${pct.toFixed(1)}%"></div></div>
    <div class="ub-meta"><span>${fmtUsd(used)} / ${fmtUsd(total)}</span><span>${t("resetsIn")} ${fmtDur(w.reset_in_sec)}</span></div>
  </div>`;
}
function renderUsageBlocks(quota, box) {
  const row = box || $("usage-blocks");
  if (!quota || !quota.success) {
    if (quota && !quota.success) {
      clearTimeout(state.quotaRetryTimer);
      row.innerHTML = `<div class="ub ub-error">${t("quotaFail")}：${escapeHtml(quota.error || "?")}，${t("retryTip")}</div>`;
      return;
    }
    if (state.quotaRetryTimer) clearTimeout(state.quotaRetryTimer);
    state.quotaRetryTimer = setTimeout(() => loadDashboard(true), 5000);
    row.innerHTML = `<div class="ub skeleton"><div class="sk-line w40"></div><div class="sk-line w20 lg"></div><div class="sk-bar"></div><div class="sk-line w60"></div></div>`.repeat(3);
    return;
  }
  if (state.quotaRetryTimer) { clearTimeout(state.quotaRetryTimer); state.quotaRetryTimer = null; }
  const blocks = [];
  for (const w of quota.windows || []) {
    // BAI 配额: 单积分格 (unit==="points" 或存在 points_balance), 不走百分比进度条
    if (w.unit === "points" || w.points_balance != null) {
      const exp = Number(w.points_expiring) || 0;
      blocks.push({
        bai: true,
        cls: "c-bai",
        label: (QUOTA_LABEL[w.label] || (() => w.label))(),
        balance: t("quotaPointsBalance").replace("{n}", fmtInt(w.points_balance)),
        expiring: exp > 0 ? t("quotaPointsExpiring").replace("{n}", fmtInt(exp)) : "",
      });
      continue;
    }
    // CommandCode 配额: USD 额度窗口 (unit==="USD"), 复用 USD 块模板
    if (w.unit === "USD") {
      blocks.push({ usd: true, html: usdWindowHtml(w, "") });
      continue;
    }
    const used = Number(w.used) || 0;
    blocks.push({
      cls: w.label === "5h Rolling" ? "c-rolling" : w.label === "Weekly" ? "c-week" : "c-month",
      label: (QUOTA_LABEL[w.label] || (() => w.label))(),
      used: used,
      remaining: (Number(w.remaining) || 0).toFixed(0) + "%",
      reset: `${t("resetsIn")} ${fmtDur(w.reset_in_sec)}`,
    });
  }
  row.innerHTML = blocks.map((b) => b.bai ? `<div class="ub ${b.cls}">
      <div class="ub-head"><span class="ub-l">${b.label}</span></div>
      <div class="ub-bal">${b.balance}</div>
      ${b.expiring ? `<div class="ub-exp">${b.expiring}</div>` : ""}
    </div>` : b.usd ? b.html : `<div class="ub ${b.cls}">
      <div class="ub-head"><span class="ub-l">${b.label}</span><span class="ub-rem">${t("remaining")} ${b.remaining}</span></div>
      <div class="ub-bar"><div class="ub-bar-fill" style="width:${b.used}%"></div></div>
      <div class="ub-meta"><span>${t("used")} ${b.used.toFixed(0)}%</span><span>${b.reset}</span></div>
    </div>`).join("");
}

/* ---------------- 首页: CommandCode 账期汇总卡 ---------------- */
/* 仅 commandcode 账户且 cc_summary 存在时显示 (账期口径快照, 由服务层同步缓存) */
function renderCcSummary(data) {
  const box = $("cc-summary");
  if (!box) return;
  const cs = data && data.account && data.account.source === "commandcode" ? data.cc_summary : null;
  if (!cs || !Object.keys(cs).length) { box.hidden = true; return; }
  const cards = [
    { cls: "c-blue", l: t("ccRequests"), v: fmtInt(cs.totalCount) },
    { cls: "c-violet", l: t("ccTokens"), v: fmtTokens(cs.totalTokens) },
    { cls: "c-amber", l: t("ccCost"), v: fmtUsd(cs.totalCost) },
    { cls: "c-green", l: t("ccSuccessRate"), v: (Number(cs.successRate) || 0).toFixed(1) + "%" },
  ];
  $("cc-grid").innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div></div>`).join("");
  box.hidden = false;
}

/* ---------------- 首页: 单渠道 tab 渲染 (Task 12) ---------------- */
function renderQuotaSingle(accounts) {
  const box = $("usage-blocks");
  if (!accounts.length) {   // 本地渠道 (zcode/claudecode/dsh) 无账号 -> 整块隐藏, 不显示占位文字 (问题6)
    box.hidden = true;
    box.innerHTML = "";
    return;
  }
  box.hidden = false;       // 复位: hidden 不随 innerHTML 更新自动恢复, 漏掉会让有账号页签配额卡消失
  box.innerHTML = accounts.map((a) =>
    `<div class="acct-quota"><div class="acct-name">${escapeHtml(a.name)}</div><div class="acct-quota-body" id="aq-${a.id}"></div></div>`).join("");
  accounts.forEach((a) => renderUsageBlocks(a.quota, $(`aq-${a.id}`)));
}

function renderCcAccounts(accounts) {
  const cc = accounts.filter((a) => a.source === "commandcode" && a.cc_summary && Object.keys(a.cc_summary).length);
  if (!cc.length) { $("cc-summary").hidden = true; return; }
  $("cc-grid").innerHTML = cc.map((a) => {
    const cs = a.cc_summary;
    const cards = [   // 新R2: 四色与现有 renderCcSummary 一致 (c-blue/violet/amber/green)
      { cls: "c-blue", l: t("ccRequests"), v: fmtInt(cs.totalCount) },
      { cls: "c-violet", l: t("ccTokens"), v: fmtTokens(cs.totalTokens) },
      { cls: "c-amber", l: t("ccCost"), v: fmtUsd(cs.totalCost) },
      { cls: "c-green", l: t("ccSuccessRate"), v: (Number(cs.successRate) || 0).toFixed(1) + "%" },
    ];
    return `<div class="acct-name" title="${escapeHtml(a.name)}">${escapeHtml(a.name)}</div>` + cards.map((c) =>
      `<div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div></div>`).join("");
  }).join("");
  $("cc-summary").hidden = false;
}

/* ---------------- 首页: ZCode (GLM Coding Plan) 额度卡 ---------------- */
/* 数据源 /api/zcode/quota (后端契约固定): fetch 抛异常 (端点不存在/网络错误)
   时容器保持 hidden 且 toast 提示 (EVOLUTION-3, 统计页后台拉取失败同样 toast,
   接受); 凭证缺失 (错误文案以「未找到 ZCode Coding Plan 凭证」开头, 后端
   CREDENTIAL_ERROR_PREFIX 契约) 显示登录引导框 */
let zcodeQuotaLast = null;
async function loadZcodeQuota() {
  const box = $("zcode-quota");
  if (!box) return;
  try {
    const data = await api("/api/zcode/quota");
    zcodeQuotaLast = data;
    renderZcodeQuota(data);
  } catch (e) {
    zcodeQuotaLast = null;
    box.hidden = true;  // ZCode 不可用: 容器隐藏, 仅 toast 提示
    toast(t("zcodeQuotaFail"), "err");
  }
}
function zcodeLevelText(level) {
  const s = String(level || "").trim();
  if (!s) return "";
  const lower = s.toLowerCase();
  if (lower === "pro") return "Pro";
  if (lower === "max") return "Max";
  return s.charAt(0).toUpperCase() + s.slice(1);
}
function zcodeResetCell(sec) {
  // reset_in_sec 为 0 表示未知 (后端契约), 显示 "—" 而非 fmtDur 的"即将重置"
  return (Number(sec) || 0) > 0 ? `${t("resetsIn")} ${fmtDur(sec)}` : "—";
}
function renderZcodeQuota(data) {
  const box = $("zcode-quota");
  if (!box) return;
  const head = $("zcode-quota-head");
  const badge = $("zcode-level");
  const row = $("zcode-quota-cards");
  if (data == null) {  // 后端获取中的占位: 骨架 (照 renderUsageBlocks 骨架模式)
    box.hidden = false;
    head.hidden = true;
    row.innerHTML = `<div class="ub skeleton"><div class="sk-line w40"></div><div class="sk-line w20 lg"></div><div class="sk-bar"></div><div class="sk-line w60"></div></div>`.repeat(3);
    return;
  }
  if (!data.success) {
    box.hidden = false;
    head.hidden = true;
    const err = String(data.error || "");
    row.innerHTML = err.includes("未找到 ZCode Coding Plan 凭证")
      ? `<div class="ub ub-hint">${t("zcodeQuotaGuide")}</div>`
      : `<div class="ub ub-error">${t("zcodeQuotaFail")}：${escapeHtml(err || "?")}</div>`;
    return;
  }
  box.hidden = false;
  head.hidden = false;
  const lvl = zcodeLevelText(data.level);
  badge.textContent = lvl;
  badge.hidden = !lvl;
  row.innerHTML = (data.windows || []).map((w) => {
    const cls = w.label === "5h Rolling" ? "c-rolling" : w.label === "Weekly" ? "c-week" : "c-month";
    const label = escapeHtml((QUOTA_LABEL[w.label] || (() => w.label))());
    const used = Math.min(100, Math.max(0, Number(w.used) || 0));  // 后端契约为百分比 0-100
    const reset = zcodeResetCell(w.reset_in_sec);
    if (w.label === "MCP Monthly") {
      const uc = Number(w.used_count) || 0;
      const tc = Number(w.total_count) || 0;
      const cnt = tc > 0 ? `${fmtInt(uc)}/${fmtInt(tc)}` : fmtInt(uc);
      return `<div class="ub ${cls}">
        <div class="ub-head"><span class="ub-l">${label}</span><span class="ub-rem">${cnt}</span></div>
        <div class="ub-bar"><div class="ub-bar-fill" style="width:${used.toFixed(1)}%"></div></div>
        <div class="ub-meta"><span>${t("used")} ${cnt} ${t("zcodeTimes")}</span><span>${reset}</span></div>
      </div>`;
    }
    return `<div class="ub ${cls}">
      <div class="ub-head"><span class="ub-l">${label}</span><span class="ub-rem">${used.toFixed(0)}%</span></div>
      <div class="ub-bar"><div class="ub-bar-fill" style="width:${used.toFixed(1)}%"></div></div>
      <div class="ub-meta"><span>${t("used")} ${used.toFixed(0)}%</span><span>${reset}</span></div>
    </div>`;
  }).join("");
}

/* ---------------- 统计页: ZCode 本地用量区块 ---------------- */
/* 数据源 /api/zcode/summary?range=<statsRange> (与 loadDashboard 统计页 range 同源);
   db_found=false → 仅显示引导文案; fetch 异常 → 整块隐藏 */
let zcodeSummaryLast = null;
let zcodeSumSeq = 0;
let cZcodeTrend = null;
async function loadZcodeSummary() {
  const seq = ++zcodeSumSeq;
  const box = $("zcode-stats");
  if (!box) return;
  try {
    const data = await api(`/api/zcode/summary?range=${state.statsRange}`);
    if (seq !== zcodeSumSeq) return;  // 丢弃过期响应 (快速切 range 时旧请求)
    renderZcodeSummary(data);
  } catch (e) {
    if (seq === zcodeSumSeq) { zcodeSummaryLast = null; box.hidden = true; }
  }
}
function zcodeProviderLabel(p) {
  // 1) provider_name 非空 → 原样; 2) 内置渠道映射; 3) 其余 (UUID) → 前 8 位 + "…"
  const name = p && p.provider_name != null ? String(p.provider_name).trim() : "";
  if (name) return name;
  const id = String((p && p.provider_id) || "");
  if (id === "builtin:bigmodel-coding-plan" || id === "builtin:zai-coding-plan") return "GLM Coding Plan";
  if (id.includes("-start-plan")) return "GLM Start";
  return id ? id.slice(0, 8) + "…" : "—";
}
function zcodeSpeed(v) { return v == null ? "—" : Number(v).toFixed(1); }
function zcodeLatency(v) { return v == null ? "—" : String(Math.round(Number(v))); }
function zcodeRenderHeads() {
  $("zcode-prov-head").innerHTML = `
    <th>${t("zcodeChannel")}</th><th class="num">${t("totalRequests")}</th>
    <th class="num">${t("input")}(${t("inclCache")})</th><th class="num">${t("output")}</th>
    <th class="num">${t("hitAmount")}</th><th class="num">${t("zcodeEstCost")}</th>
    <th class="num">${t("zcodeAvgTps")}</th><th class="num">${t("zcodeAvgTtft")}</th>`;
  $("zcode-model-head").innerHTML = `
    <th>${t("zcodeChannel")}</th><th>${t("zcodeModel")}</th><th class="num">${t("totalRequests")}</th>
    <th class="num">${t("input")}(${t("inclCache")})</th><th class="num">${t("output")}</th>
    <th class="num">${t("hitAmount")}</th><th class="num">${t("zcodeHitRate")}</th>
    <th class="num">${t("zcodeEstCost")}</th><th class="num">${t("zcodeAvgTps")}</th>`;
}
function renderZcodeSummary(data) {
  zcodeSummaryLast = data;
  const box = $("zcode-stats");
  if (!box) return;
  const missing = $("zcode-missing");
  const kpis = $("zcode-kpis");
  const tables = $("zcode-tables");
  const trendBox = $("zcode-trend-box");
  if (!data || data.db_found === false) {
    // 未检测到本地库: 仅显示引导文案, 隐藏 KPI/表格/图
    box.hidden = false;
    missing.hidden = false;
    kpis.hidden = true;
    kpis.innerHTML = "";
    tables.hidden = true;
    trendBox.hidden = true;
    if (cZcodeTrend) { cZcodeTrend.destroy(); cZcodeTrend = null; }
    return;
  }
  box.hidden = false;
  missing.hidden = true;
  kpis.hidden = false;
  tables.hidden = false;
  trendBox.hidden = false;
  zcodeRenderHeads();
  const tt = data.totals || {};
  const totalTokens = (tt.total_input_tokens || 0) + (tt.total_output_tokens || 0) + (tt.total_reasoning_tokens || 0);
  const cards = [
    { cls: "c-blue", l: t("totalRequests"), v: fmtInt(tt.request_count) },
    { cls: "c-violet", l: t("totalTokens"), v: fmtTokens(totalTokens) },
    { cls: "c-amber", l: t("zcodeEstCost"), v: fmtMoney(tt.total_cost_usd) },
    { cls: "c-green", l: t("zcodeAvgTps"), v: tt.avg_tps == null ? "—" : Number(tt.avg_tps).toFixed(1) + " tok/s" },
    { cls: "c-cyan", l: t("zcodeAvgTtft"), v: tt.avg_ttft_ms == null ? "—" : Math.round(Number(tt.avg_ttft_ms)) + " ms" },
  ];
  kpis.innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div></div>`).join("");
  const provs = data.providers || [];
  $("zcode-prov-body").innerHTML = provs.length ? provs.map((p) => `
    <tr><td>${escapeHtml(zcodeProviderLabel(p))}</td>
    <td class="num">${fmtInt(p.request_count)}</td>
    <td class="num">${fmtTokens(p.total_input_tokens)}</td>
    <td class="num">${fmtTokens(p.total_output_tokens)}</td>
    <td class="num">${fmtTokens(p.cache_hit_tokens)}</td>
    <td class="num">${fmtMoney(p.total_cost_usd)}</td>
    <td class="num">${zcodeSpeed(p.avg_tps)}</td>
    <td class="num">${zcodeLatency(p.avg_ttft_ms)}</td></tr>`).join("")
    : `<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:20px">${t("zcodeNoData")}</td></tr>`;
  const models = data.models || [];
  $("zcode-model-body").innerHTML = models.length ? models.map((m) => `
    <tr><td>${escapeHtml(zcodeProviderLabel(m))}</td>
    <td><span class="model-cell">${modelIcon(m.model_id)}${escapeHtml(m.model_id)}</span></td>
    <td class="num">${fmtInt(m.request_count)}</td>
    <td class="num">${fmtTokens(m.total_input_tokens)}</td>
    <td class="num">${fmtTokens(m.total_output_tokens)}</td>
    <td class="num">${fmtTokens(m.cache_hit_tokens)}</td>
    <td class="num">${m.hit_rate == null ? "—" : Number(m.hit_rate).toFixed(1) + "%"}</td>
    <td class="num">${fmtMoney(m.total_cost_usd)}</td>
    <td class="num">${zcodeSpeed(m.avg_tps)}</td></tr>`).join("")
    : `<tr><td colspan="9" style="text-align:center;color:var(--text3);padding:20px">${t("zcodeNoData")}</td></tr>`;
  chartZcodeTrend(data.daily7 || []);
}
/* 7 日趋势: Token + 估算费用两条线, 固定近 7 天窗口 (数据源 daily7, 不随 range 变化) */
function chartZcodeTrend(daily7) {
  const canvas = $("zcode-trend-chart");
  const emptyEl = $("zcode-trend-empty");
  if (!canvas) return;
  if (cZcodeTrend) { cZcodeTrend.destroy(); cZcodeTrend = null; }
  if (!daily7 || !daily7.length) {
    if (emptyEl) { emptyEl.textContent = t("zcodeNoData"); emptyEl.hidden = false; }
    return;
  }
  if (emptyEl) emptyEl.hidden = true;
  cZcodeTrend = new Chart(canvas, {
    type: "line",
    data: {
      labels: daily7.map((d) => d.date.slice(5)),
      datasets: [
        { label: t("totalTokens"), data: daily7.map((d) => (d.total_input_tokens || 0) + (d.total_output_tokens || 0) + (d.total_reasoning_tokens || 0)), borderColor: COLOR.reasoning, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y" },
        { label: t("zcodeEstCost"), data: daily7.map((d) => d.total_cost_usd || 0), borderColor: COLOR.input, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y1" },
      ],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } },
        tooltip: { callbacks: { label: (it) => ` ${it.dataset.label}: ${it.dataset.yAxisID === "y" ? fmtTokens(it.parsed.y) : fmtMoney(it.parsed.y)}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 7 } },
        y: { position: "left", grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtTokens(v) } },
        y1: { position: "right", grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtMoney(v) } },
      },
    },
  });
  cZcodeTrend.resize();
}

/* ---------------- 统计页: DSH 本地用量区块 ---------------- */
/* 数据源 /api/dsh/usage (TTL 缓存在后端 dsh_api 模块内部, 端点不加缓存);
   found=false → 显示空态文案; fetch 异常 → 整块隐藏 (照 ZCode 容错);
   注意: 后端返回模块缓存对象本体, 只读消费, 严禁原地修改;
   providers/models 仅总量口径: today 档保持总量数据并显示口径说明 (dshTodayTableNote) */
let dshUsageLast = null;
async function loadDshUsage() {
  const box = $("dsh-stats");
  if (!box) return;
  try {
    const data = await api("/api/dsh/usage");
    dshUsageLast = data;
    renderDsh(data);
  } catch (e) {
    dshUsageLast = null;
    box.hidden = true;  // DSH 端点不可用: 不显示错误, 容器隐藏
  }
}
function dshRenderHeads() {
  $("dsh-prov-head").innerHTML = `
    <th>${t("zcodeChannel")}</th><th class="num">${t("dshColSteps")}</th>
    <th class="num">${t("input")}(${t("inclCache")})</th><th class="num">${t("output")}</th>
    <th class="num">${t("dshColTps")}</th>`;
  $("dsh-model-head").innerHTML = `
    <th>${t("zcodeChannel")}</th><th>${t("zcodeModel")}</th><th class="num">${t("dshColSteps")}</th>
    <th class="num">${t("input")}(${t("inclCache")})</th><th class="num">${t("output")}</th>
    <th class="num">${t("dshColTps")}</th>`;
}
function renderDsh(data) {
  const box = $("dsh-stats");
  if (!box) return;
  const missing = $("dsh-missing");
  const body = $("dsh-body");
  if (!data || data.found === false) {
    // 未检测到 DSH 本地数据: 仅显示引导文案, 隐藏 KPI/表格
    box.hidden = false;
    missing.hidden = false;
    body.hidden = true;
    return;
  }
  box.hidden = false;
  missing.hidden = true;
  body.hidden = false;
  dshRenderHeads();
  const tt = data.total || {};
  const td = data.today || {};
  $("dsh-tps-hint").textContent = t("dshTpsHint").replace("{tps}", (Number(tt.tps) || 0).toFixed(1));
  const kpi = (cls, l, v) => `<div class="card kpi ${cls}"><div class="kpi-l">${l}</div><div class="kpi-v">${v}</div></div>`;
  $("dsh-kpis-total").innerHTML = [
    kpi("c-blue", t("dshKpiSessions"), fmtInt(data.sessions_count)),
    kpi("c-green", t("dshKpiInput"), fmtTokens(tt.input)),
    kpi("c-violet", t("dshKpiOutput"), fmtTokens(tt.output)),
  ].join("");
  $("dsh-kpis-today").innerHTML = [
    kpi("c-blue", t("dshKpiTodayInput"), fmtTokens(td.input)),
    kpi("c-green", t("dshKpiTodayOutput"), fmtTokens(td.output)),
    kpi("c-amber", t("dshKpiTodaySpeed"), (Number(td.tps) || 0).toFixed(1) + " tok/s"),
  ].join("");
  // 渠道/模型明细仅总量口径: 两档都渲染总量数字, today 档显示口径说明
  const provs = data.providers || [];
  $("dsh-prov-body").innerHTML = provs.length ? provs.map((p) => `
    <tr><td>${escapeHtml(p.provider || "—")}</td>
    <td class="num">${fmtInt(p.steps)}</td>
    <td class="num">${fmtTokens(p.input)}</td>
    <td class="num">${fmtTokens(p.output)}</td>
    <td class="num">${(Number(p.tps) || 0).toFixed(1)}</td></tr>`).join("")
    : `<tr><td colspan="5" style="text-align:center;color:var(--text3);padding:20px">${t("zcodeNoData")}</td></tr>`;
  const models = data.models || [];
  $("dsh-model-body").innerHTML = models.length ? models.map((m) => `
    <tr><td>${escapeHtml(m.provider || "—")}</td>
    <td><span class="model-cell">${modelIcon(m.model)}${escapeHtml(m.model || "—")}</span></td>
    <td class="num">${fmtInt(m.steps)}</td>
    <td class="num">${fmtTokens(m.input)}</td>
    <td class="num">${fmtTokens(m.output)}</td>
    <td class="num">${(Number(m.tps) || 0).toFixed(1)}</td></tr>`).join("")
    : `<tr><td colspan="6" style="text-align:center;color:var(--text3);padding:20px">${t("zcodeNoData")}</td></tr>`;
  const note = $("dsh-today-note");
  if (note) note.hidden = state.dshDim !== "today";
}

/* ---------------- 统计页: Claude Code 本地用量区块 ---------------- */
/* 数据源 /api/claudecode/summary?range=<statsRange> (与 loadDashboard 统计页 range 同源);
   db_found=false → 仅显示引导文案; fetch 异常 → 整块隐藏 (照 ZCode 容错);
   渠道名导入时已落中文名/hostname, 直接渲染 channel 字段, 无需前端映射 */
let claudecodeSummaryLast = null;
let claudecodeSumSeq = 0;
let cClaudecodeTrend = null;
async function loadClaudecodeSummary() {
  const seq = ++claudecodeSumSeq;
  const box = $("claudecode-stats");
  if (!box) return;
  try {
    const data = await api(`/api/claudecode/summary?range=${state.statsRange}`);
    if (seq !== claudecodeSumSeq) return;  // 丢弃过期响应 (快速切 range 时旧请求)
    renderClaudecodeSummary(data);
  } catch (e) {
    if (seq === claudecodeSumSeq) { claudecodeSummaryLast = null; box.hidden = true; }
  }
}
function claudecodeRenderHeads() {
  $("claudecode-prov-head").innerHTML = `
    <th>${t("zcodeChannel")}</th><th class="num">${t("totalRequests")}</th>
    <th class="num">${t("totalTokens")}</th><th class="num">${t("output")}</th>
    <th class="num">${t("zcodeAvgTps")}</th><th class="num">${t("zcodeEstCost")}</th>`;
  $("claudecode-model-head").innerHTML = `
    <th>${t("zcodeModel")}</th><th class="num">${t("totalRequests")}</th>
    <th class="num">${t("totalTokens")}</th><th class="num">${t("output")}</th>
    <th class="num">${t("zcodeAvgTps")}</th><th class="num">${t("zcodeEstCost")}</th>`;
}
function renderClaudecodeSummary(data) {
  claudecodeSummaryLast = data;
  const box = $("claudecode-stats");
  if (!box) return;
  const missing = $("claudecode-missing");
  const kpis = $("claudecode-kpis");
  const tables = $("claudecode-tables");
  const trendBox = $("claudecode-trend-box");
  if (!data || data.db_found === false) {
    // 未检测到本地数据目录: 仅显示引导文案, 隐藏 KPI/表格/图
    box.hidden = false;
    missing.hidden = false;
    kpis.hidden = true;
    kpis.innerHTML = "";
    tables.hidden = true;
    trendBox.hidden = true;
    if (cClaudecodeTrend) { cClaudecodeTrend.destroy(); cClaudecodeTrend = null; }
    return;
  }
  box.hidden = false;
  missing.hidden = true;
  kpis.hidden = false;
  tables.hidden = false;
  trendBox.hidden = false;
  claudecodeRenderHeads();
  const tt = data.totals || {};
  const cards = [
    { cls: "c-violet", l: t("totalTokens"), v: fmtTokens(tt.total_tokens) },
    { cls: "c-green", l: t("claudecodeKpiOutput"), v: fmtTokens(tt.total_output_tokens) },
    { cls: "c-blue", l: t("totalRequests"), v: fmtInt(tt.request_count) },
    { cls: "c-cyan", l: t("zcodeAvgTps"), v: tt.avg_tps == null ? "—" : Number(tt.avg_tps).toFixed(1) + " tok/s" },
    { cls: "c-amber", l: t("zcodeEstCost"), v: fmtMoney(tt.total_cost_usd) },
  ];
  kpis.innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div></div>`).join("");
  const channels = data.channels || [];
  $("claudecode-prov-body").innerHTML = channels.length ? channels.map((p) => `
    <tr><td>${escapeHtml(p.channel || "—")}</td>
    <td class="num">${fmtInt(p.request_count)}</td>
    <td class="num">${fmtTokens(p.total_tokens)}</td>
    <td class="num">${fmtTokens(p.total_output_tokens)}</td>
    <td class="num">${zcodeSpeed(p.avg_tps)}</td>
    <td class="num">${fmtMoney(p.total_cost_usd)}</td></tr>`).join("")
    : `<tr><td colspan="6" style="text-align:center;color:var(--text3);padding:20px">${t("zcodeNoData")}</td></tr>`;
  const models = data.models || [];
  $("claudecode-model-body").innerHTML = models.length ? models.map((m) => `
    <tr><td><span class="model-cell">${modelIcon(m.model)}${escapeHtml(m.model || "—")}</span></td>
    <td class="num">${fmtInt(m.request_count)}</td>
    <td class="num">${fmtTokens(m.total_tokens)}</td>
    <td class="num">${fmtTokens(m.total_output_tokens)}</td>
    <td class="num">${zcodeSpeed(m.avg_tps)}</td>
    <td class="num">${fmtMoney(m.total_cost_usd)}</td></tr>`).join("")
    : `<tr><td colspan="6" style="text-align:center;color:var(--text3);padding:20px">${t("zcodeNoData")}</td></tr>`;
  chartClaudecodeTrend(data.daily7 || []);
}
/* 7 日趋势: Token + 估算费用两条线, 固定近 7 天窗口 (数据源 daily7, 不随 range 变化) */
function chartClaudecodeTrend(daily7) {
  const canvas = $("claudecode-trend-chart");
  const emptyEl = $("claudecode-trend-empty");
  if (!canvas) return;
  if (cClaudecodeTrend) { cClaudecodeTrend.destroy(); cClaudecodeTrend = null; }
  if (!daily7 || !daily7.length) {
    if (emptyEl) { emptyEl.textContent = t("zcodeNoData"); emptyEl.hidden = false; }
    return;
  }
  if (emptyEl) emptyEl.hidden = true;
  cClaudecodeTrend = new Chart(canvas, {
    type: "line",
    data: {
      labels: daily7.map((d) => d.date.slice(5)),
      datasets: [
        { label: t("totalTokens"), data: daily7.map((d) => d.total_tokens || 0), borderColor: COLOR.reasoning, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y" },
        { label: t("zcodeEstCost"), data: daily7.map((d) => d.total_cost_usd || 0), borderColor: COLOR.input, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y1" },
      ],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } },
        tooltip: { callbacks: { label: (it) => ` ${it.dataset.label}: ${it.dataset.yAxisID === "y" ? fmtTokens(it.parsed.y) : fmtMoney(it.parsed.y)}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 7 } },
        y: { position: "left", grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtTokens(v) } },
        y1: { position: "right", grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtMoney(v) } },
      },
    },
  });
  cClaudecodeTrend.resize();
}

/* ---------------- 首页: 用量概览 6 格 ---------------- */
function renderOverview(totals, source) {
  const isEst = ["bai", "zcode", "claudecode"].includes(source);   // R6: 费用估算徽章扩展至本地渠道
  const totalTokens = totals.total_input_tokens + totals.total_output_tokens + totals.total_reasoning_tokens;
  const cards = [
    { cls: "c-green", l: t("hitRate"), v: totals.hit_rate.toFixed(1) + "%", s: `${t("hit")} ${fmtTokens(totals.cache_hit_tokens)} · ${t("miss")} ${fmtTokens(totals.uncached_input_tokens)}` },
    { cls: "c-cyan", l: t("hitAmount"), v: fmtTokens(totals.cache_hit_tokens), s: `${t("pctOfInput")} ${totals.hit_rate.toFixed(1)}%` },
    { cls: "c-blue", l: t("totalTokens"), v: fmtTokens(totalTokens), s: t("inclCache") },
    { cls: "c-slate", l: t("totalRequests"), v: fmtInt(totals.request_count), s: t("currentRange") },
    { cls: "c-amber", l: t("totalCost") + (isEst ? ` <span class="est-badge" title="${t("estimateTip")}">${t("estimateBadge")}</span>` : ""), v: fmtMoney(totals.total_cost_usd), s: `${t("avgPer")} ${fmtMoney(totals.request_count ? totals.total_cost_usd / totals.request_count : 0)}${t("perReq")}` },
    { cls: "c-violet", l: t("sessions"), v: fmtInt(totals.session_count), s: t("dedup") },
  ];
  $("overview-grid").innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div><div class="kpi-s">${c.s}</div></div>`).join("");
}

/* ---------------- 首页: 今日趋势 24h ---------------- */
let cToday = null;
function chartToday(trend) {
  const canvas = $("today-chart");
  if (cToday) cToday.destroy();
  const box = canvas ? canvas.parentElement : null;
  if (box) box.classList.remove("sk-box");  // 移除骨架遮罩
  if (!trend || !trend.length) { cToday = null; return; }
  cToday = new Chart(canvas, {
    type: "bar",
    data: {
      labels: trend.map((d) => d.hour),
      datasets: [
        { label: t("input"), data: trend.map((d) => d.input), backgroundColor: COLOR.input, borderRadius: 2, barPercentage: 0.8 },
        { label: t("output"), data: trend.map((d) => d.output), backgroundColor: COLOR.output, borderRadius: 2, barPercentage: 0.8 },
      ],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 8 } },
        y: { grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtTokens(v) } },
      },
    },
  });
  cToday.resize();
}

/* ---------------- 统计页: 4 总卡 + 6 明细 ---------------- */
function renderStatsTotal(totals, source) {
  const isEst = ["bai", "zcode", "claudecode"].includes(source);   // R6: 费用估算徽章扩展至本地渠道
  const totalTokens = totals.total_input_tokens + totals.total_output_tokens + totals.total_reasoning_tokens;
  const cards = [
    { cls: "c-amber", l: t("totalCost") + (isEst ? ` <span class="est-badge" title="${t("estimateTip")}">${t("estimateBadge")}</span>` : ""), v: fmtMoney(totals.total_cost_usd), s: `${t("avgPer")} ${fmtMoney(totals.request_count ? totals.total_cost_usd / totals.request_count : 0)}${t("perReq")}` },
    { cls: "c-blue", l: t("totalRequests"), v: fmtInt(totals.request_count), s: t("currentRange") },
    { cls: "c-violet", l: t("totalTokens"), v: fmtTokens(totalTokens), s: `${t("input")} ${fmtTokens(totals.total_input_tokens)} · ${t("output")} ${fmtTokens(totals.total_output_tokens)}` },
    { cls: "c-green", l: t("hitRate"), v: totals.hit_rate.toFixed(1) + "%", s: `${t("hit")} ${fmtTokens(totals.cache_hit_tokens)} / ${t("miss")} ${fmtTokens(totals.uncached_input_tokens)}` },
  ];
  $("stats-total-cards").innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div><div class="kpi-s">${c.s}</div></div>`).join("");
}
function renderDetail6(totals) {
  const total = totals.uncached_input_tokens + totals.total_output_tokens + totals.total_reasoning_tokens;
  const cards = [
    { l: t("input"), v: fmtTokens(totals.uncached_input_tokens), s: `${t("inclCache")} ${fmtTokens(totals.total_input_tokens)}` },
    { l: t("output"), v: fmtTokens(totals.total_output_tokens), s: t("output") },
    { l: t("colReasoning"), v: fmtTokens(totals.total_reasoning_tokens), s: total ? ((totals.total_reasoning_tokens / total) * 100).toFixed(1) + "%" : "0%" },
    { l: t("colCacheRead"), v: fmtTokens(totals.cache_hit_tokens), s: `${t("hitRate")} ${totals.hit_rate.toFixed(1)}%` },
    { l: lang === "zh" ? "缓存写" : "Cache Write", v: fmtTokens(totals.cache_write_tokens), s: lang === "zh" ? "新写入缓存" : "new cache writes" },
    { l: t("sessions"), v: fmtInt(totals.session_count), s: t("dedup") },
  ];
  $("stats-detail6").innerHTML = cards.map((c) => `
    <div class="tc"><div class="tc-l">${c.l}</div><div class="tc-v">${c.v}</div><div class="tc-s">${c.s}</div></div>`).join("");
}

/* ---------------- 统计页: 模型用量 ---------------- */
let cModel = null;
function chartModel(models) {
  const canvas = $("mr-chart");
  if (cModel) cModel.destroy();
  if (!models || !models.length) { cModel = null; $("mr-list").innerHTML = ""; return; }
  const dim = state.modelDim;
  const getVal = (m) => (dim === "input" ? m.uncached_input_tokens : dim === "output" ? m.total_output_tokens : m.total_cost_usd);
  const fmt = dim === "cost" ? (v) => fmtMoney(v) : fmtTokens;
  const sorted = [...models].sort((a, b) => getVal(b) - getVal(a));
  const top = sorted.slice(0, 6);
  const total = sorted.reduce((s, m) => s + getVal(m), 0);
  const palette = [COLOR.input, COLOR.output, COLOR.reasoning, COLOR.cache, COLOR.cost, "#ec4899"];
  cModel = new Chart(canvas, {
    type: "doughnut",
    data: {
      labels: top.map((m) => m.model),
      datasets: [{ data: top.map(getVal), backgroundColor: palette, borderWidth: 2, borderColor: cssVar("--card") }],
    },
    options: {
      responsive: false, maintainAspectRatio: false, cutout: "60%",
      plugins: {
        legend: { position: "right", labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } },
        tooltip: { callbacks: { label: (it) => ` ${it.label}: ${fmt(it.parsed)}${total ? ` (${((it.parsed / total) * 100).toFixed(1)}%)` : ""}` } },
      },
    },
  });
  cModel.resize();
  $("mr-list").innerHTML = sorted.slice(0, 3).map((m, i) => `
    <div class="mr-item"><span class="mr-rank">#${i + 1}</span>
    <span class="mr-name">${modelIcon(m.model)}<span class="txt">${escapeHtml(m.model)}</span></span>
    <span class="mr-sub">${fmtInt(m.request_count)} · ${t("hitRate")} ${m.hit_rate}%</span>
    <span class="mr-cost">${fmtMoney(m.total_cost_usd)}</span></div>`).join("");
}

/* ---------------- 统计页: 用量趋势 ---------------- */
let cTrend = null;
function chartTrend(trend) {
  const canvas = $("trend-chart");
  if (cTrend) cTrend.destroy();
  if (!trend || !trend.length) { cTrend = null; return; }
  cTrend = new Chart(canvas, {
    data: {
      labels: trend.map((d) => d.date.slice(5)),
      datasets: [
        { type: "line", label: t("totalCost"), data: trend.map((d) => d.total_cost_usd), borderColor: COLOR.input, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y" },
        { type: "line", label: t("totalRequests"), data: trend.map((d) => d.request_count), borderColor: COLOR.output, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y1", borderDash: [4, 3] },
        { type: "line", label: t("totalTokens"), data: trend.map((d) => d.total_input_tokens + d.total_output_tokens + d.total_reasoning_tokens), borderColor: COLOR.reasoning, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y2" },
      ],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } },
        tooltip: {
          callbacks: {
            label: (item) => {
              if (item.dataset.label === t("totalTokens")) return ` ${item.dataset.label}: ${fmtTokens(item.parsed.y)}`;
              if (item.dataset.label === t("totalRequests")) return ` ${item.dataset.label}: ${fmtInt(item.parsed.y)}`;
              return ` ${item.dataset.label}: ${fmtMoney(item.parsed.y)}`;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 8 } },
        y: { position: "left", grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtMoney(v) } },
        y1: { position: "right", grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 } } },
        y2: { position: "right", display: false },  // 总 Token 独立隐藏轴
      },
    },
  });
  cTrend.resize();
}

/* ---------------- 会话用量 ---------------- */
let sesSeq = 0;
async function loadSessions() {
  const seq = ++sesSeq;
  const body = $("sessions-body");
  try {
    const q = new URLSearchParams({ page: state.sessions.page, page_size: 7 });
    const data = await api(`/api/usage/sessions?${q}`);
    if (seq !== sesSeq) return; // 丢弃过期响应 (快速切页/翻页时旧请求)
    state.sessions.total = data.total;
    $("ses-count").textContent = `${t("totalN")} ${fmtInt(data.total)} ${t("sessions")}`;
    if (!data.records.length) {
      body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:20px">${t("noData")}</td></tr>`;
    } else {
      let html = data.records.map((s) => `
        <tr><td class="key-name">${escapeHtml(s.key_name || "—")}</td>
        ${s.session_id
          ? `<td title="${escapeHtml(s.session_id)}">${escapeHtml(shortId(s.session_id))}</td>`
          : `<td class="unassigned">${t("unassigned")}</td>`}
        <td>${fmtDateTime(s.last_at)}</td>
        <td class="num">${fmtTokens(s.total_input_tokens)}</td>
        <td class="num">${fmtTokens(s.total_output_tokens)}</td>
        <td class="num">${fmtTokens(s.total_reasoning_tokens)}</td>
        <td class="num">${fmtInt(s.request_count)} / ${fmtTokens(s.total_input_tokens + s.total_output_tokens + s.total_reasoning_tokens)}</td>
        <td class="num">${fmtMoney(s.total_cost_usd)}</td></tr>`).join("");
      // 固定 7 行, 不足补空行
      if (data.records.length < 7) {
        html += ('<tr>' + '<td>&nbsp;</td>'.repeat(8) + '</tr>').repeat(7 - data.records.length);
      }
      body.innerHTML = html;
    }
    const totalPages = Math.max(1, Math.ceil(data.total / 7));
    $("ses-pager").textContent = `${t("pageOf")} ${state.sessions.page} ${t("ofPages")} ${totalPages}`;
    $("ses-prev").disabled = state.sessions.page <= 1;
    $("ses-next").disabled = state.sessions.page >= totalPages;
  } catch (e) {
    if (seq === sesSeq) body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--red);padding:20px">${t("loadFailed")}: ${escapeHtml(e.message)}</td></tr>`;
  }
}
function shortId(id) {
  const s = String(id || "");
  // 会话 ID 较长时省略中间, 保留头尾便于区分
  if (s.length <= 24) return s;
  const head = s.slice(0, 10);
  const tail = s.slice(-6);
  return `${head}…${tail}`;
}
function fmtDateTimeShort(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return "—";
  const pad = (x) => String(x).padStart(2, "0");
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* ---------------- 使用记录 ---------------- */
let recSeq = 0;
async function loadRecords() {
  const seq = ++recSeq;
  const body = $("records-body");
  try {
    const q = new URLSearchParams({ page: state.records.page, page_size: 7 });
    if (state.records.model) q.set("model", state.records.model);
    const data = await api(`/api/usage/records?${q}`);
    if (seq !== recSeq) return; // 丢弃过期响应 (快速切页/翻页时旧请求)
    state.records.total = data.total;
    const sel = $("rec-model-filter");
    const cur = sel.value;
    sel.innerHTML = '<option value="">' + t("allModels") + '</option>' + data.models.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`).join("");
    sel.value = state.records.model || cur || "";
    $("rec-count").textContent = `${t("totalN")} ${fmtInt(data.total)} ${t("items")}`;
    if (!data.records.length) {
      body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--text3);padding:24px">${t("noData")}</td></tr>`;
    } else {
      let html = data.records.map((r) => `
        <tr><td class="key-name">${escapeHtml(r.key_name || "—")}</td>
        <td>${fmtDateTime(r.created_at)}</td>
        <td><span class="model-cell">${modelIcon(r.model)}${escapeHtml(r.model)}</span></td>
        <td class="num">${fmtTokens(r.input_tokens)}</td>
        <td class="num">${fmtTokens(r.output_tokens)}</td>
        <td class="num">${fmtTokens(r.reasoning_tokens)}</td>
        <td class="num">${fmtTokens(r.cache_read_tokens)}</td>
        <td class="num">${fmtMoney(r.cost_usd)}</td></tr>`).join("");
      // 固定 7 行, 不足补空行
      if (data.records.length < 7) {
        html += ('<tr>' + '<td>&nbsp;</td>'.repeat(8) + '</tr>').repeat(7 - data.records.length);
      }
      body.innerHTML = html;
    }
    const totalPages = Math.max(1, Math.ceil(data.total / 7));
    $("rec-pager").textContent = `${t("pageOf")} ${state.records.page} ${t("ofPages")} ${totalPages}`;
    $("pg-prev").disabled = state.records.page <= 1;
    $("pg-next").disabled = state.records.page >= totalPages;
  } catch (e) {
    if (seq === recSeq) body.innerHTML = `<tr><td colspan="8" style="text-align:center;color:var(--red);padding:24px">${t("loadFailed")}: ${escapeHtml(e.message)}</td></tr>`;
  }
}

/* ---------------- 模型图标 ---------------- */
function modelIcon(m) {
  const s = String(m || "").toLowerCase();
  const base = s.split("-")[0];
  const map = { deepseek: "deepseek", glm: "glm", gpt: "gpt", grok: "grok", kimi: "kimi", meta: "meta", mimo: "mimo", minimax: "minimax", muse: "meta", qwen: "qwen", hy: "hy", claude: "claude" };
  // hy2/hy3 等混元系列模型统一使用 hy 图标 (首段非精确 hy 时按前缀匹配)
  let name = map[base];
  if (!name) name = base.startsWith("hy") ? "hy" : "deepseek";
  const dark = document.documentElement.dataset.theme === "dark";
  // kimi 白 K 仅适配深色背景, 浅色主题切 color 变体; gpt/grok/mimo 相反, 深色主题切 color 变体
  const themed = dark
    ? (["gpt", "grok", "mimo"].includes(name) ? `${name}-color` : name)
    : (name === "kimi" ? "kimi-color" : name);
  return `<img src="icons/${themed}.svg" alt="${escapeHtml(m)}" title="${escapeHtml(m)}" style="width:16px;height:16px">`;
}
function refreshIcons() {
  if (!document.getElementById("page-stats").hidden) chartModel(state.data?.models);
}

/* ---------------- 组装 ---------------- */
function renderAll(data) {
  state.data = data;
  if (data.exchange_rate?.usd_cny) state.exchangeRate = data.exchange_rate.usd_cny;
  renderUsageBlocks(data.quota);
  renderCcSummary(data);
  renderOverview(data.totals, data.account?.source);
  const homeVisible = !document.getElementById("page-home").hidden;
  const statsVisible = !document.getElementById("page-stats").hidden;
  // 只重建当前可见页面的图表 (hidden 页面的 canvas 尺寸为 0, 创建会失败)
  if (homeVisible) chartToday(data.today_trend);
  if (statsVisible) {
    renderStatsTotal(data.totals, data.account?.source);
    renderDetail6(data.totals);
    chartModel(data.models);
    chartTrend(data.trend);
    $("trend-hint").textContent = t("trendHint");
  }
  $("tb-sync").textContent = data.logged_in ? `${t("lastSync")} ${fmtRelative(data.sync?.last_sync_at)} · ${fmtInt(data.sync?.total_records || 0)} ${t("records")}` : t("notLoggedIn");
  const accLabel = data.account_name || maskWs(data);
  $("tb-login").innerHTML = data.logged_in ? `<b>${t("loggedIn")}</b> · ${escapeHtml(accLabel)}` : t("notLoggedIn");
  $("tb-login").style.color = data.logged_in ? "" : "var(--red)";
  $("tb-login").title = t("userSwitchTip");
  const uc = $("tb-user-count");
  if (uc) {
    uc.hidden = !(Number(data.accounts_logged_in) > 0);
    uc.textContent = String(data.accounts_logged_in ?? 0);  // 仅已登录数 (与列表口径一致)
    uc.title = t("userCountTip");
  }
  const st = data.server_time || "";
  if (st) $("tb-updated").textContent = `${t("updatedAt")} ${st.slice(0, 16).replace("T", " ")}`;
  renderSyncBanner(data.progress);
  renderSettingsSyncProgress(data.progress);
}
function maskWs(data) {
  const ws = data?.quota?.workspace_id || "";
  return ws.length > 12 ? ws.slice(0, 8) + "…" : ws;
}

/* ---------------- 同步 ---------------- */
async function startSync(mode) {
  $("tb-refresh").disabled = true;
  $("btn-full-sync").disabled = true;
  try { await api("/api/sync?mode=" + mode, { method: "POST" }); } catch (e) { console.error(e); }
  pollUntilIdle();
}
function pollUntilIdle() {
  if (state.syncTimer) clearInterval(state.syncTimer);
  state.syncTimer = setInterval(async () => {
    try {
      const st = await api("/api/state");
      renderSyncBanner(st.progress);
      renderSettingsSyncProgress(st.progress);
      if (!st.progress.running) {
        clearInterval(state.syncTimer); state.syncTimer = null;
        $("tb-refresh").disabled = false;
        $("btn-full-sync").disabled = false;
        await loadDashboard();
        if (state.page === "settings") renderSettings();
        if (state.page === "overview") loadOverview(true).catch(() => {});
      }
    } catch (e) { /* ignore */ }
  }, 2500);
}
function renderSyncBanner(progress) {
  $("sync-indicator").hidden = !(progress && progress.running);
}
function renderSettingsSyncProgress(progress) {
  if (!progress || !progress.running) {
    $("set-sync-progress-desc").textContent = t("fullSyncDesc");
    $("set-sync-progress-val").textContent = "";
    return;
  }
  const phase = progress.phase === "usage" ? t("syncing") : t("syncing");
  $("set-sync-progress-desc").textContent = `${phase} · ${t("pageOf")} ${progress.page + 1}`;
  $("set-sync-progress-val").textContent = `${t("totalN")} ${fmtInt(progress.inserted)}`;
}

/* ---------------- 账户总览面板 (多账户聚合) ---------------- */
let ovSeq = 0;
let cOvTrendChart = null;
const OV_COLORS = ["#7c5cf6", "#4f8ef7", "#22c55e", "#d97706", "#06b6d4", "#ec4899"];

/* 开关控制侧边栏入口显隐; 关闭时若停留在总览页则退回首页 */
function applyOverviewPanel(show) {
  const btn = document.getElementById("side-overview");
  if (btn) btn.hidden = !show;
  if (!show && state.page === "overview") switchPage("home");
}

async function loadOverview(quiet = false) {
  const seq = ++ovSeq;
  if (!quiet) {
    const sKpi = `<div class="card kpi skeleton"><div class="sk-line w30"></div><div class="sk-line w40 lg"></div><div class="sk-line w50"></div></div>`;
    $("ov-summary-cards").innerHTML = sKpi.repeat(4);
    $("ov-accounts").innerHTML = `<div class="card ov-acc skeleton" style="height:140px"></div>`.repeat(2);
  }
  try {
    const data = await api("/api/accounts/overview");
    if (seq !== ovSeq) return; // 丢弃过期响应 (快速切换页面时旧请求)
    if (data.exchange_rate?.usd_cny) state.exchangeRate = data.exchange_rate.usd_cny;
    renderAccountOverview(data);
    // 已登录账号配额缓存缺失 (后台刷新中), 5s 后静默重拉一次
    const missing = (data.accounts || []).some((a) => a.logged_in && !a.quota);
    clearTimeout(state.ovRetryTimer);
    if (missing) state.ovRetryTimer = setTimeout(() => { if (state.page === "overview") loadOverview(true); }, 5000);
  } catch (e) {
    if (!quiet) toast(e.message || t("loadFailed"), "err");
  }
}

function renderAccountOverview(data) {
  const accounts = (data.accounts || []).map((a, i) => ({ ...a, color: OV_COLORS[i % OV_COLORS.length] }));
  // ---- 顶部汇总: 今日合计 ----
  const sum = accounts.reduce((acc, a) => {
    const tt = a.today || {};
    acc.req += tt.request_count || 0;
    acc.in += tt.total_input_tokens || 0;
    acc.out += tt.total_output_tokens || 0;
    acc.rsn += tt.total_reasoning_tokens || 0;
    acc.cost += tt.total_cost_usd || 0;
    return acc;
  }, { req: 0, in: 0, out: 0, rsn: 0, cost: 0 });
  const cards = [
    { cls: "c-violet", l: t("todayTotalReq"), v: fmtInt(sum.req) },
    { cls: "c-blue", l: t("todayTotalTokens"), v: fmtTokens(sum.in + sum.out + sum.rsn) },
    { cls: "c-cyan", l: t("todayTotalInput"), v: fmtTokens(sum.in) },
    { cls: "c-amber", l: t("todayTotalCost"), v: fmtMoney(sum.cost) },
  ];
  $("ov-summary-cards").innerHTML = cards.map((c) => `
    <div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div></div>`).join("");

  // ---- 7 日费用趋势对比 ----
  chartOvTrend(accounts);

  // ---- 账号卡片 ----
  $("ov-accounts").innerHTML = accounts.length
    ? accounts.map((a) => renderAccountCard(a)).join("")
    : `<div class="card ov-acc"><div class="ov-quota-empty">${t("noUsers")}</div></div>`;
}

function renderAccountCard(a) {
  // 配额卡片: opencode 三百分比窗口 / BAI 单积分格; 缓存未就绪显示占位
  let quotaHtml;
  if (a.quota && a.quota.success && a.quota.windows) {
    quotaHtml = `<div class="ov-quota-grid">${a.quota.windows.map((w) => {
      // BAI 积分单格
      if (w.unit === "points" || w.points_balance != null) {
        const exp = Number(w.points_expiring) || 0;
        return `<div class="ub c-bai ov-ub">
          <div class="ub-head"><span class="ub-l">${(QUOTA_LABEL[w.label] || (() => w.label))()}</span></div>
          <div class="ub-bal">${t("quotaPointsBalance").replace("{n}", fmtInt(w.points_balance))}</div>
          ${exp > 0 ? `<div class="ub-exp">${t("quotaPointsExpiring").replace("{n}", fmtInt(exp))}</div>` : ""}
        </div>`;
      }
      // CommandCode USD 额度窗口 (与首页同模板)
      if (w.unit === "USD") { return usdWindowHtml(w, "ov-ub"); }
      const used = Number(w.used) || 0;
      const cls = w.label === "5h Rolling" ? "c-rolling" : w.label === "Weekly" ? "c-week" : "c-month";
      return `<div class="ub ${cls} ov-ub">
        <div class="ub-head"><span class="ub-l">${(QUOTA_LABEL[w.label] || (() => w.label))()}</span><span class="ub-rem">${t("remaining")} ${(Number(w.remaining) || 0).toFixed(0)}%</span></div>
        <div class="ub-bar"><div class="ub-bar-fill" style="width:${used}%"></div></div>
        <div class="ub-meta"><span>${t("used")} ${used.toFixed(0)}%</span><span>${t("resetsIn")} ${fmtDur(w.reset_in_sec)}</span></div>
      </div>`;
    }).join("")}</div>`;
  } else {
    quotaHtml = `<div class="ov-quota-empty">${t("quotaNotReady")}</div>`;
  }
  const tt = a.today || {};
  const spark = sparklineSvg((a.today_trend || []).map((d) => d.input + d.output + d.reasoning), a.color);
  return `<div class="card ov-acc">
    <div class="ov-acc-head">
      <span class="ov-acc-name">${escapeHtml(a.name)}</span>
      <span class="ov-acc-badges">${a.source === "bai" ? `<span class="src-badge">${t("sourceBai")}</span>` : ""}${a.active ? `<span class="plan-badge">${t("activeAccount")}</span>` : ""}</span>
      <span class="ov-acc-sync">${t("lastSync")} ${fmtRelative(a.last_sync_at)}</span>
    </div>
    ${quotaHtml}
    <div class="tc-grid ov-today">
      <div class="tc"><div class="tc-l">${t("totalRequests")}</div><div class="tc-v">${fmtInt(tt.request_count)}</div></div>
      <div class="tc"><div class="tc-l">${t("input")}</div><div class="tc-v">${fmtTokens(tt.total_input_tokens)}</div></div>
      <div class="tc"><div class="tc-l">${t("output")}</div><div class="tc-v">${fmtTokens(tt.total_output_tokens)}</div></div>
      <div class="tc"><div class="tc-l">${t("colReasoning")}</div><div class="tc-v">${fmtTokens(tt.total_reasoning_tokens)}</div></div>
      <div class="tc"><div class="tc-l">${t("colCost")}</div><div class="tc-v">${fmtMoney(tt.total_cost_usd)}</div></div>
      <div class="tc"><div class="tc-l">${t("todayTrend")}</div><div class="tc-v ov-spark">${spark}</div></div>
    </div>
  </div>`;
}

/* 24h 迷你趋势: 纯 SVG 折线 (无 Chart 实例, 轻量随卡片渲染) */
function sparklineSvg(values, color) {
  const w = 120, h = 30, n = values.length;
  if (!n) return `<svg viewBox="0 0 ${w} ${h}" class="spark"></svg>`;
  const max = Math.max(...values, 1);
  const step = n > 1 ? w / (n - 1) : w;
  const pts = values.map((v, i) => `${(i * step).toFixed(1)},${(h - 2 - (v / max) * (h - 4)).toFixed(1)}`);
  return `<svg viewBox="0 0 ${w} ${h}" class="spark" preserveAspectRatio="none">
    <polyline points="${pts.join(" ")}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>
    <polyline points="0,${h} ${pts.join(" ")} ${w},${h}" fill="${color}" opacity="0.12" stroke="none"/>
  </svg>`;
}

/* 7 日费用对比: 全部账号合计为 总费用/请求/Token 三条线, 与用量趋势样式一致 */
function chartOvTrend(accounts) {
  const canvas = $("ov-trend-chart");
  if (!canvas) return;
  if (cOvTrendChart) { cOvTrendChart.destroy(); cOvTrendChart = null; }
  const dated = accounts.filter((a) => (a.daily7 || []).length);
  if (!dated.length) return;
  const dateSet = new Set();
  dated.forEach((a) => a.daily7.forEach((d) => dateSet.add(d.date)));
  const labels = [...dateSet].sort();
  // 全部账号合计: 每日 总费用 / 请求数 / Token 总数 (输入+输出+推理)
  const costSum = {}, reqSum = {}, tokSum = {};
  dated.forEach((a) => a.daily7.forEach((d) => {
    costSum[d.date] = (costSum[d.date] || 0) + (d.total_cost_usd || 0);
    reqSum[d.date] = (reqSum[d.date] || 0) + (d.request_count || 0);
    tokSum[d.date] = (tokSum[d.date] || 0) + (d.total_input_tokens || 0) + (d.total_output_tokens || 0) + (d.total_reasoning_tokens || 0);
  }));
  const costData = labels.map((dt) => costSum[dt] || 0);
  const reqData = labels.map((dt) => reqSum[dt] || 0);
  const tokData = labels.map((dt) => tokSum[dt] || 0);
  cOvTrendChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: t("totalCost"), data: costData, borderColor: COLOR.input, borderWidth: 2, pointRadius: 1.5, tension: 0.3, yAxisID: "y" },
        { label: t("totalRequests"), data: reqData, borderColor: COLOR.output, borderWidth: 2, pointRadius: 1.5, tension: 0.3, borderDash: [4, 3], yAxisID: "y1" },
        { label: t("totalTokens"), data: tokData, borderColor: COLOR.reasoning, borderWidth: 2, pointRadius: 1.5, tension: 0.3, borderDash: [4, 3], yAxisID: "y2" },
      ],
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } },
        tooltip: { callbacks: { label: (it) => it.dataset.label === t("totalRequests") ? ` ${it.dataset.label}: ${fmtInt(it.parsed.y)}` : it.dataset.label === t("totalTokens") ? ` ${it.dataset.label}: ${fmtTokens(it.parsed.y)}` : ` ${it.dataset.label}: ${fmtMoney(it.parsed.y)}` } },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 7 } },
        y: { position: "left", grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtMoney(v) } },
        y1: { position: "right", grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 } } },
        y2: { position: "right", display: false },  // 总 Token 独立隐藏轴 (与用量趋势一致)
      },
    },
  });
  cOvTrendChart.resize();
}

/* ---------------- 设置页 ---------------- */
async function renderSettings() {
  try {
    const st = await api("/api/state");
    $("set-sync-info").textContent = st.sync && st.sync.last_sync_at
      ? `${t("lastSync")} ${fmtDateTime(st.sync.last_sync_at)} (${st.sync.last_sync_status}) · ${t("totalN")} ${fmtInt(st.sync.total_records || 0)} ${t("items")}`
      : t("never");
    $("set-datadir").textContent = st.datadir || "—";
    const settings = await api("/api/settings");
    state.settings = settings;
    syncSettingsPills();
    $("set-auto-sync").checked = settings.auto_sync !== false;
    $("set-overview-panel").checked = settings.show_accounts_panel === true;
    await fetchAccounts();  // 账户列表 (失败不阻塞其他设置渲染)
  } catch (e) { /* ignore */ }
}
function syncSettingsPills() {
  const s = state.settings;
  document.querySelectorAll("#set-interval-pills .pill").forEach((b) => b.classList.toggle("active", Number(b.dataset.v) === Number(s.sync_interval_sec)));
  document.querySelectorAll("#set-window-pills .pill").forEach((b) => b.classList.toggle("active", (s.window_days == null ? "all" : String(s.window_days)) === b.dataset.v));
}

/* ---------------- 多用户: 顶栏切换器 ---------------- */

/* 登录流程期间的账户变化监视: 登录窗是独立窗口, 成功后的跨窗口通知
   (load_url 同URL跳过 / evaluate_js 时序) 均不可靠, 用短轮询兜底保证
   账户列表/顶栏计数即时刷新. 5 分钟无变化自动停止. */
let loginWatchTimer = null;
function startLoginWatch() {
  stopLoginWatch();
  let baseline = "";
  const startedAt = Date.now();
  const poll = async () => {
    if (Date.now() - startedAt > 5 * 60 * 1000) { stopLoginWatch(); return; }
    try {
      const r = await api("/api/accounts");
      const sig = JSON.stringify((r.accounts || []).map((a) => [a.id, a.has_token, a.name])) + "|" + r.active_id;
      if (!baseline) { baseline = sig; return; }  // 首轮采基线
      if (sig !== baseline) {
        stopLoginWatch();
        await loadDashboard();
        if (state.page === "settings") renderSettings().catch(() => {});
        else if (state.page === "records") { loadSessions().catch(() => {}); loadRecords().catch(() => {}); }
        if (state.page === "overview") loadOverview(true).catch(() => {});
      }
    } catch (e) { /* ignore */ }
  };
  poll();
  loginWatchTimer = setInterval(poll, 2000);
}
function stopLoginWatch() {
  if (loginWatchTimer) { clearInterval(loginWatchTimer); loginWatchTimer = null; }
}

async function toggleUserMenu(force) {
  const menu = $("user-menu");
  if (!menu) return;
  const show = force !== undefined ? force : menu.hidden;
  if (!show) { menu.hidden = true; return; }
  try {
    const r = await api("/api/accounts");
    renderUserMenu((r.accounts || []).filter((a) => a.has_token), r.active_id);
    menu.hidden = false;
  } catch (e) { toast(t("loadFailed"), "err"); }
}
function renderUserMenu(accounts, activeId) {
  const menu = $("user-menu");
  menu.innerHTML = (accounts.length ? accounts.map((a) => `
    <div class="um-item" data-id="${a.id}">
      <span class="um-check">${a.id === activeId ? "✓" : ""}</span>
      <span class="um-meta">
        <span class="um-name-row"><span class="um-name">${escapeHtml(a.name)}</span>${a.source === "bai" ? `<span class="src-badge">${t("sourceBai")}</span>` : a.source === "commandcode" ? `<span class="src-badge">${t("sourceCommandcode")}</span>` : ""}</span>
        <span class="um-ws">${escapeHtml(a.workspace_id || "—")}${a.has_token ? "" : " · " + t("notLoggedIn")}</span>
      </span>
    </div>`).join("") : `<div class="um-item um-empty">${t("noUsers")}</div>`) +
    `<div class="um-item um-manage" id="um-manage"><span class="um-check">⚙</span><span class="um-meta"><span class="um-name">${t("setUsers")}</span></span></div>`;
  menu.querySelectorAll(".um-item[data-id]").forEach((el) => {
    el.addEventListener("click", async () => {
      const id = Number(el.dataset.id);
      toggleUserMenu(false);
      if (id === activeId) return;
      try {
        await api("/api/accounts/switch", { method: "POST", body: JSON.stringify({ id }) });
        toast(t("switchedAccount"));
        await loadDashboard();
        if (state.page === "settings") renderSettings().catch(() => {});
        else if (state.page === "records") { loadSessions().catch(() => {}); loadRecords().catch(() => {}); }
        if (state.page === "overview") loadOverview(true).catch(() => {});
      } catch (e) { toast(e.message || t("loadFailed"), "err"); }
    });
  });
  const mg = $("um-manage");
  if (mg) mg.addEventListener("click", () => { toggleUserMenu(false); switchPage("settings"); });
}

/* ---------------- 多用户: 设置页列表 ---------------- */
async function fetchAccounts() {
  const r = await api("/api/accounts");
  renderUsersList(r.accounts || [], r.active_id);
}
function renderUsersList(accounts, activeId) {
  const box = $("users-list");
  if (!box) return;
  if (!(accounts || []).length) {
    box.innerHTML = `<div class="hint" style="padding:12px 16px">${t("noUsers")}</div>`;
    return;
  }
  box.innerHTML = (accounts || []).map((a) => {
    const isActive = a.id === activeId && a.has_token;  // 活跃态只对已登录行生效
    const actions = !a.has_token
      ? `<button class="btn" data-act="login">${t("loginRow")}</button>
         <button class="btn" data-act="rename">${t("renameBtn")}</button>
         <button class="btn btn-danger" data-act="delete">${t("deleteUser")}</button>`
      : isActive
      ? `<button class="btn" data-act="relogin">${t("relogin")}</button>
         <button class="btn" data-act="rename">${t("renameBtn")}</button>
         <button class="btn" data-act="logout">${t("logout")}</button>`
      : `<button class="btn" data-act="switch">${t("switchTo")}</button>
         <button class="btn" data-act="rename">${t("renameBtn")}</button>
         <button class="btn btn-danger" data-act="delete">${t("deleteUser")}</button>`;
    const badge = !a.has_token
      ? `<span class="badge no ur-badge">${t("notLoggedIn")}</span>`
      : isActive ? `<span class="badge ok ur-badge">${t("currentUserBadge")}</span>` : "";
    return `
    <div class="user-row${isActive ? " active" : ""}" data-id="${a.id}">
      <div class="ur-meta">
        <div class="ur-name">${escapeHtml(a.name)}${a.source === "bai" ? `<span class="src-badge ur-badge">${t("sourceBai")}</span>` : a.source === "commandcode" ? `<span class="src-badge ur-badge">${t("sourceCommandcode")}</span>` : ""}${badge}</div>
        <div class="ur-ws">${escapeHtml(a.workspace_id || "—")}${a.has_token ? " · " + t("loggedIn") : ""}</div>
        ${a.source === "commandcode" ? `<div class="ur-note">${t("ccHistoryNote")}</div>` : ""}
      </div>
      <div class="ur-actions">${actions}</div>
    </div>`;
  }).join("");
}
async function onUserRowAction(id, act) {
  if (act === "switch") {
    try {
      await api("/api/accounts/switch", { method: "POST", body: JSON.stringify({ id }) });
      toast(t("switchedAccount"));
      await loadDashboard();
      renderSettings().catch(() => {});
      if (state.page === "overview") loadOverview(true).catch(() => {});
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
    return;
  }
  if (act === "login") {  // 未登录行的「登录」: 定向登录该账号
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login("relogin", id); return; }
    try {  // 浏览器兜底
      await api("/api/relogin", { method: "POST", body: JSON.stringify({ id }) });
      toast(t("loginNote"));
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
    return;
  }
  if (act === "relogin") {
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login("relogin"); return; }
    try {  // 浏览器兜底
      await api("/api/relogin", { method: "POST", body: "{}" });
      toast(t("loginNote"));
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
    return;
  }
  if (act === "logout") {
    const accounts = (await api("/api/accounts").catch(() => ({ accounts: [] }))).accounts || [];
    const acc = accounts.find((x) => x.id === id);
    showModal({
      title: t("logout"),
      message: escapeHtml(t("logoutUserConfirm").replace("{name}", acc ? acc.name : "")),
      okText: t("confirm"),
      onOk: async () => {
        try {
          await api("/api/logout", { method: "POST", body: "{}" });
          toast(t("loggedOut"));
          const r = await api("/api/accounts").catch(() => ({ accounts: [] }));
          renderUsersList(r.accounts || [], r.active_id);
          await loadDashboard();
          if (state.page === "overview") loadOverview(true).catch(() => {});  // 退出后账号卡片即时移除
          if (!(r.accounts || []).some((x) => x.has_token)) showLoginOverlay(true);  // 全部退出 -> 欢迎页
        } catch (e) { toast(e.message || t("loadFailed"), "err"); }
      },
    });
    return;
  }
  const accounts = (await api("/api/accounts").catch(() => ({ accounts: [] }))).accounts || [];
  const acc = accounts.find((x) => x.id === id);
  if (act === "rename") {
    let renamed = acc ? acc.name : "";
    showModal({
      title: t("renameTitle"),
      message: `<input id="rename-input" class="select" maxlength="50" value="${escapeHtml(renamed)}">`,
      okText: t("save"),
      onOk: async () => {
        try {
          await api("/api/accounts/rename", { method: "POST", body: JSON.stringify({ id, name: renamed }) });
          toast(t("userRenamed"));
          renderSettings().catch(() => {});
          loadDashboard(true);
          if (state.page === "overview") loadOverview(true).catch(() => {});  // 卡片名称即时更新
        } catch (e) { toast(e.message || t("loadFailed"), "err"); }
      },
    });
    const input = $("rename-input");
    if (input) {
      input.addEventListener("input", () => { renamed = input.value; });
      input.focus();
    }
    return;
  }
  if (act === "delete") {
    showModal({
      title: t("deleteUserTitle"), danger: true,
      message: escapeHtml(t("deleteUserConfirm").replace("{name}", acc ? acc.name : `#${id}`)),
      okText: t("confirm"),
      onOk: async () => {
        try {
          const r = await api("/api/accounts/delete", { method: "POST", body: JSON.stringify({ id }) });
          toast(t("userDeleted"));
          await loadDashboard();
          renderSettings().catch(() => {});
          if (state.page === "overview") loadOverview(true).catch(() => {});
          if ((r.remaining ?? 1) === 0) showLoginOverlay(true);
        } catch (e) { toast(e.message || t("loadFailed"), "err"); }
      },
    });
  }
}

/* ---------------- 登录状态 ---------------- */
let loginPollTimer = null;
function showLoginOverlay(show) {
  // 遮罩背景不透明, 直接显示即可覆盖页面; 不要隐藏 .app (会连同遮罩一起隐藏)
  $("login-overlay").hidden = !show;
  if (show) {
    // 欢迎页显示时轮询登录状态: 独立登录窗登录成功后自动进入面板
    if (loginPollTimer) clearInterval(loginPollTimer);
    loginPollTimer = setInterval(async () => {
      try {
        const st = await api("/api/state");
        if (st.logged_in) {
          clearInterval(loginPollTimer);
          loginPollTimer = null;
          showLoginOverlay(false);
          await loadDashboard();
          renderSettings().catch(() => {});
          if (state.page === "overview") loadOverview(true).catch(() => {});  // 新登录账号卡片即时出现
        }
      } catch (e) { /* ignore */ }
    }, 2000);
  } else if (loginPollTimer) {
    clearInterval(loginPollTimer);
    loginPollTimer = null;
  }
}
async function checkState() {
  try {
    const st = await api("/api/state");
    if (!st.logged_in) { showLoginOverlay(true); return; }
    showLoginOverlay(false);
    if (st.progress && st.progress.running) pollUntilIdle();
    await loadDashboard();
  } catch (e) { console.error("state check failed", e); }
}

/* 登录成功通知 (后端 evaluate_js 触发, 见 main.on_login_success):
   就地刷新数据/顶栏/账户列表, 不依赖整页重载 (同 URL load_url 可能被跳过) */
window.gousageOnLoginSuccess = async function () {
  try {
    const st = await api("/api/state");
    if (st.logged_in) showLoginOverlay(false);  // 欢迎页场景: 直接进入面板
  } catch (e) { /* ignore */ }
  loadDashboard().catch(() => {});
  if (state.page === "settings") renderSettings().catch(() => {});
  else if (state.page === "records") { loadSessions().catch(() => {}); loadRecords().catch(() => {}); }
};

/* ---------------- 事件绑定 ---------------- */
function bindEvents() {
  document.querySelectorAll(".side-item").forEach((btn) => btn.addEventListener("click", () => switchPage(btn.dataset.page)));

  document.querySelectorAll("#home-pills .pill").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#home-pills .pill").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.range = b.dataset.r; loadDashboard();
  }));
  document.querySelectorAll("#stats-pills .pill").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("#stats-pills .pill").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.statsRange = b.dataset.r; loadDashboard();
    loadZcodeSummary();  // ZCode 区块跟随 range 切换
    loadClaudecodeSummary();  // Claude Code 区块跟随 range 切换
  }));
  $("mr-dim").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#mr-dim button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.modelDim = b.dataset.dim;
    if (state.data) chartModel(state.data.models);
  });
  $("dsh-dim").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#dsh-dim button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.dshDim = b.dataset.d;
    if (dshUsageLast) renderDsh(dshUsageLast);  // seg 切换: 复用已拉取数据重渲, 不重新请求
  });
  $("tb-refresh").addEventListener("click", () => startSync("incremental"));
  $("btn-full-sync").addEventListener("click", () => {
    showModal({ title: t("fullSync"), message: t("fullSyncConfirm"), okText: t("startSync"), onOk: () => startSync("full") });
  });
  $("pg-prev").addEventListener("click", () => { if (state.records.page > 1) { state.records.page--; loadRecords(); } });
  $("pg-next").addEventListener("click", () => { state.records.page++; loadRecords(); });
  $("ses-prev").addEventListener("click", () => { if (state.sessions.page > 1) { state.sessions.page--; loadSessions(); } });
  $("ses-next").addEventListener("click", () => { state.sessions.page++; loadSessions(); });
  $("rec-model-filter").addEventListener("change", (e) => { state.records.model = e.target.value; state.records.page = 1; loadRecords(); });

  // 检查更新: 有新版 -> 弹窗 -> 打开浏览器前往 GitHub Releases 下载
  $("btn-check-update").addEventListener("click", async () => {
    const btn = $("btn-check-update");
    const desc = $("set-update-desc");
    const prevText = btn.textContent;
    btn.disabled = true;
    btn.textContent = t("checkingUpdate");
    try {
      const r = await api("/api/update/check");
      if (r.error) throw new Error(r.error);
      if (r.has_update) {
        desc.textContent = `${t("updateFound")} ${r.latest}`;
        showModal({
          title: t("updateFound"),
          message: `<b>${r.latest}</b> (${t("currentVersion")} v${r.current})<br><br>${escapeHtml((r.notes || "").slice(0, 300)) || ""}`,
          okText: t("goDownload"),
          onOk: () => { api("/api/update/open", { method: "POST" }).catch(() => {}); },
        });
      } else {
        desc.textContent = `${t("updateNone")} (v${r.current})`;
        toast(t("updateNone"));
      }
    } catch (e) {
      desc.textContent = `${t("updateFailed")}: ${t("checkUpdateDesc")}`;
      showModal({ title: t("updateFailed"), message: escapeHtml(e.message || ""), okText: t("ok") });
    } finally {
      btn.disabled = false;
      btn.textContent = prevText;
    }
  });

  document.querySelectorAll("#set-interval-pills .pill").forEach((b) => b.addEventListener("click", async () => {
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ sync_interval_sec: Number(b.dataset.v) }) });
    state.settings = await api("/api/settings");
    syncSettingsPills(); restartAutoSync(); toast(`${t("syncIntervalSet")} ${b.textContent}`);
  }));
  document.querySelectorAll("#set-window-pills .pill").forEach((b) => b.addEventListener("click", async () => {
    const v = b.dataset.v === "all" ? null : Number(b.dataset.v);
    await api("/api/settings", { method: "PUT", body: JSON.stringify({ window_days: v }) });
    state.settings = await api("/api/settings");
    syncSettingsPills();
    toast(t("syncRangeUpdated"));
  }));
  document.querySelectorAll("#set-theme-pills .pill").forEach((b) => b.addEventListener("click", () => applyDarkMode(b.dataset.v === "dark")));
  document.querySelectorAll("#set-currency-pills .pill").forEach((b) => b.addEventListener("click", () => applyCurrency(b.dataset.v)));
  document.querySelectorAll("#set-lang-pills .pill").forEach((b) => b.addEventListener("click", () => applyLang(b.dataset.v)));
  $("set-auto-sync").addEventListener("change", (e) => {
    state.settings.auto_sync = e.target.checked;
    api("/api/settings", { method: "PUT", body: JSON.stringify({ auto_sync: e.target.checked }) }).catch(() => {});
    restartAutoSync();
  });
  // 账户总览面板开关: 控制侧边栏入口显隐 (关闭时停留在总览页则退回首页)
  $("set-overview-panel").addEventListener("change", (e) => {
    state.settings.show_accounts_panel = e.target.checked;
    api("/api/settings", { method: "PUT", body: JSON.stringify({ show_accounts_panel: e.target.checked }) }).catch(() => {});
    applyOverviewPanel(e.target.checked);
  });
  // 账户操作已合并进「OpenCode 账户」卡片内的账号行 (relogin/logout 为行级动作)

  // 多用户: 顶栏切换器 + 设置页账户列表
  $("tb-login").addEventListener("click", () => toggleUserMenu());
  document.addEventListener("click", (e) => {
    const menu = $("user-menu");
    if (menu && !menu.hidden && !e.target.closest(".user-switch")) toggleUserMenu(false);
  });
  $("btn-add-user").addEventListener("click", async () => {
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login("add"); return; }
    try {  // 浏览器环境兜底
      await api("/api/accounts/add", { method: "POST", body: "{}" });
      toast(t("loginNote"));
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
  });
  // 添加 BAI 账号: pywebview 打开 BAI 登录页; 浏览器兜底走 /api/accounts/add source=bai
  $("btn-add-bai").addEventListener("click", async () => {
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login("add_bai"); return; }
    try {  // 浏览器环境兜底
      await api("/api/accounts/add", { method: "POST", body: JSON.stringify({ source: "bai" }) });
      toast(t("loginNote"));
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
  });
  // 添加 CommandCode 账号: pywebview 打开 commandcode.ai 登录页; 浏览器兜底走 /api/accounts/add source=commandcode
  $("btn-add-commandcode").addEventListener("click", async () => {
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login("add_commandcode"); return; }
    try {  // 浏览器环境兜底
      await api("/api/accounts/add", { method: "POST", body: JSON.stringify({ source: "commandcode" }) });
      toast(t("loginNote"));
    } catch (e) { toast(e.message || t("loadFailed"), "err"); }
  });
  $("users-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const row = e.target.closest(".user-row");
    if (!row) return;
    onUserRowAction(Number(row.dataset.id), btn.dataset.act).catch((err) => toast(String(err.message || err), "err"));
  });
  $("btn-login").addEventListener("click", async () => {
    startLoginWatch();
    const a = await pywebviewApi();
    if (a && a.open_login) { a.open_login(); return; }  // 弹出独立登录窗口
    // 浏览器环境兜底: 跳转授权页
    $("btn-login").disabled = true;
    $("btn-login").textContent = t("loginBtn") + "…";
    await api("/api/relogin", { method: "POST" });
  });
  $("btn-manage-data").addEventListener("click", () => {  // 不登录先看本地数据: 关遮罩 -> 设置页账号列表
    showLoginOverlay(false);
    switchPage("settings");
    const list = $("users-list");
    if (list) {
      list.scrollIntoView({ behavior: "smooth", block: "center" });
      list.classList.remove("users-list-flash");
      void list.offsetWidth;  // 强制 reflow, 重复点击也能重放动画
      list.classList.add("users-list-flash");
      setTimeout(() => list.classList.remove("users-list-flash"), 1100);
    }
  });
  $("btn-quit-app").addEventListener("click", async () => {
    const a = await pywebviewApi();
    if (a) a.quit();
  });
  // 渠道 tab (bindEvents 内追加)
  document.addEventListener("click", (e) => {
    const b = e.target.closest("#channel-tabs .pill");
    if (!b) return;
    switchChannel(b.dataset.ch);
  });
  $("report-metric").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#report-metric button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.reportMetric = b.dataset.m; loadReportAll();
  });
  bindTitlebar();
}

function switchChannel(ch) {
  state.channel = ch;
  document.querySelectorAll("#channel-tabs .pill").forEach((x) => x.classList.toggle("active", x.dataset.ch === ch));
  loadDashboard();
}

const CH_COLOR = { opencode: "var(--ch-opencode)", bai: "var(--ch-bai)", commandcode: "var(--ch-commandcode)",
  zcode: "var(--ch-zcode)", claudecode: "var(--ch-claudecode)", dsh: "var(--ch-dsh)" };   // 新R5 N18: 扩齐六渠道, 防分段同色

async function loadReportAll(quiet = false) {
  try {
    const range = state.range;
    const [w, rows, ov, zq] = await Promise.all([
      api(`/api/report/windows`),
      api(`/api/report/channels?range=${range}`),
      api(`/api/accounts/overview`),                    // R1: 摘要条数据并入同一并发 (T9 renderQuotaBar)
      api(`/api/zcode/quota`).catch(() => null),        // 问题5: ZCode 额度并入配额条, 失败不出卡
    ]);
    renderWindows(w, rows.rows.some((r) => r.estimated));
    renderQuotaBar(ov.accounts, zq);
    renderChannelTable(rows.rows);
    $("report-scope").textContent = t("scopeHint").replace("{n}", w.channel_count).replace("{m}", w.account_count);
    // 估算徽章: 仅 指标=费用 且 含估算渠道(bai/zcode/claudecode)时显示 (新R5 N24: 注释随 R6 est 集合更新)
    $("report-est").hidden = !(state.reportMetric === "cost" && rows.rows.some((r) => r.estimated));
    const daily = await api(`/api/report/daily?range=${range}&metric=${state.reportMetric}`);
    chartReportStack(daily);
    chartReportDonut(daily);
    if (range === "today" || range === "yesterday") {
      $("report-hourly").closest(".card").hidden = false;    // R2: 藏整卡, 不留空壳标题
      const hSpan = $("hourly-title").querySelector("[data-i18n]");   // 标题随档位切换 (data-i18n 同步改, 保持 applyLang 一致)
      if (hSpan) { hSpan.textContent = t(range === "yesterday" ? "yesterday" : "todayTrend"); hSpan.setAttribute("data-i18n", range === "yesterday" ? "yesterday" : "todayTrend"); }
      chartReportHourly(await api(`/api/report/hourly?date=${range}`));
    } else {
      $("report-hourly").closest(".card").hidden = true;
    }
  } catch (e) { if (!quiet) toast(t("loadFailed") + ": " + e); }   // R1: 现有 key 为 loadFailed
}

function renderQuotaBar(accounts, zdata = null) {
  const byCh = {};
  for (const a of accounts) {
    (byCh[a.source] = byCh[a.source] || []).push(a);
  }
  const cards = Object.keys(byCh).map((ch) => {
    const list = byCh[ch];
    // 同步归并 (spec v10): 时间取最陈旧 min; 任一失败 -> 红点
    const times = list.map((a) => a.last_sync_at).filter(Boolean).sort();
    const failed = list.some((a) => a.last_sync_status && a.last_sync_status !== "ok");
    const foot = `${list.length}${t("accountsUnit")}${times.length ? ` · ${fmtAgo(times[0])}` : ""}${failed ? ' <span class="sync-fail" title="同步失败">⚠</span>' : ""}`;
    let main;
    if (ch === "opencode") {
      // 窗口百分比不可聚合 -> 最紧张账号 max% (spec v5)
      const pct = Math.max(0, ...list.map((a) => (a.quota && a.quota.windows || []).reduce((m, x) => Math.max(m, x.label === "5h Rolling" ? (x.used || 0) : 0), 0)));
      main = `<div class="qb-bar"><div class="qb-bar-fill" style="width:${Math.min(100, pct).toFixed(1)}%"></div></div>
        <div class="qb-sub">${t("rolling")} 5h · <b>${Math.max(0, pct).toFixed(0)}%</b></div>`;
    } else if (ch === "bai") {
      // 积分余额跨账号合计 (新R1)
      const pts = list.reduce((s, a) => s + (((a.quota && a.quota.windows || [])
        .find((x) => x.unit === "points" || x.points_balance != null) || {}).points_balance || 0), 0);
      main = `<div class="qb-val">${t("quotaPointsBalance").replace("{n}", fmtInt(pts))}</div>`;
    } else if (ch === "commandcode") {
      // USD 剩余额度跨账号合计 (与 renderUsageBlocks USD 分支同字段)
      const rem = list.reduce((s, a) => s + (((a.quota && a.quota.windows || [])
        .filter((x) => x.unit === "USD")
        .reduce((u, x) => u + ((Number(x.total) || 0) - (Number(x.used) || 0)), 0)) || 0), 0);
      main = `<div class="qb-val">${fmtUsd(rem)}</div><div class="qb-sub">${t("remaining")}</div>`;
    } else {
      main = `<div class="qb-val">${list.length}</div><div class="qb-sub">${t("accountsUnit")}</div>`;
    }
    return `<div class="qb-card">
      <div class="qb-head"><span class="qb-dot" style="background:${chColor(ch)}"></span><span class="qb-name" style="color:${chColor(ch)}">${ch}</span></div>
      ${main}
      <div class="qb-foot">${foot}</div>
    </div>`;
  });
  if (zdata && zdata.success) {   // Task 8 接入 ZCode 额度; 本任务先支持入参
    const wins = zdata.windows || [];
    const segs = wins
      .filter((x) => x.label === "5h Rolling" || x.label === "Weekly")
      .map((x) => `${(QUOTA_LABEL[x.label] || (() => x.label))()} ${(Number(x.used) || 0).toFixed(0)}%`);
    cards.push(`<div class="qb-card">
      <div class="qb-head"><span class="qb-dot" style="background:${chColor("zcode")}"></span><span class="qb-name" style="color:${chColor("zcode")}">zcode</span>${zdata.level ? `<span class="zcode-badge">${escapeHtml(zcodeLevelText(zdata.level))}</span>` : ""}</div>
      <div class="qb-sub">${segs.join(" · ") || t("zcodeNoData")}</div>
      <div class="qb-foot">GLM Coding Plan</div>
    </div>`);
  }
  $("quota-bar").innerHTML = cards.join("");
}

function fmtAgo(iso) {  // 相对时间: 简化复用 fmtDateTime + 差值分钟
  const ms = Date.now() - new Date(iso.replace(" ", "T")).getTime();
  const m = Math.max(0, Math.round(ms / 60000));
  return m < 60 ? `${m}min` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;
}

function renderWindows(w, hasEst = false) {
  const cell = (key, label, sub) => `<div class="wb-cell" data-win="${key}"><div class="wb-l">${label}</div>
    <div class="wb-v">${fmtTokens(w[key].tokens)}</div><div class="wb-v2">${fmtMoney(w[key].cost)}</div>
    <div class="wb-s${w.compare.spike && key === "today" ? " spike" : ""}">${sub}</div></div>`;
  const cmp = w.compare.insufficient_sample ? t("sampleInsufficient")
    : (w.compare.pct == null ? "" : `<span class="${w.compare.pct >= 0 ? "up" : "down"}">${w.compare.pct >= 0 ? "↑" : "↓"}${Math.abs(w.compare.pct)}%</span> ${t("vsSame")}`);
  $("windows-bar").innerHTML =
    cell("today", t("today"), cmp) + cell("yesterday", t("yesterday"), "") +   // 新R1: 昨日格副行为空 (规格布局)
    cell("7d", t("d7"), w["7d"].tokens ? `${t("dailyAvg")} ${fmtTokens(Math.round(w["7d"].tokens / 7))}` : "") +
    cell("30d", t("d30"), w["30d"].tokens ? `${t("dailyAvg")} ${fmtTokens(Math.round(w["30d"].tokens / 30))}` : "");
  // 标注行 (占满整行): 数据起点 + 费用估算徽章, 有内容才追加
  const notes = [];
  if (w.data_since) notes.push(`${t("dataSince")} ${w.data_since}`);
  if (hasEst) notes.push(`<span class="est-badge" title="${t("estimateTip")}">${t("estimateBadge")}</span>`);
  if (notes.length) $("windows-bar").insertAdjacentHTML("beforeend", `<div class="wb-since">${notes.join(" · ")}</div>`);
  // 点击格 -> 页头 pill 联动 (spec v4/v5 单向映射)
  document.querySelectorAll("#windows-bar .wb-cell").forEach((c) => c.addEventListener("click", () => {
    const map = { today: "today", yesterday: "yesterday", "7d": "7d", "30d": "30d" };
    const r = map[c.dataset.win];
    const btn = document.querySelector(`#home-pills .pill[data-r="${r}"]`);
    if (btn) btn.click();
  }));
}

let cStack = null, cDonut = null;

function chColor(ch) {
  const v = CH_COLOR[ch];
  return v ? getComputedStyle(document.documentElement).getPropertyValue(v.replace(/var\(|\)/g, "").trim()) || "#4f8ef7" : "#4f8ef7";
}

function chartReportStack(d) {
  const canvas = $("report-stack");
  if (cStack) cStack.destroy();
  cStack = new Chart(canvas, {
    type: "bar",
    data: {
      labels: d.labels,
      datasets: Object.keys(d.series).map((ch) => ({
        label: ch, data: d.series[ch], backgroundColor: chColor(ch), borderRadius: 2, barPercentage: 0.8,
      })),
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 10 } },
        y: { stacked: true, grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => d.metric === "cost" ? fmtMoney(v) : d.metric === "requests" ? fmtInt(v) : fmtTokens(v) } },
      },
    },
  });
  cStack.resize();
}

function chartReportDonut(d) {
  const canvas = $("report-donut");
  if (cDonut) cDonut.destroy();
  const chs = Object.keys(d.series);
  const totals = chs.map((ch) => d.series[ch].reduce((a, b) => a + b, 0));
  const grand = totals.reduce((a, b) => a + b, 0);
  const centerText = { id: "centerText", afterDraw(chart) {   // 环形图中心总量 (spec v8, P0)
    const { ctx, chartArea } = chart;
    if (!chartArea) return;
    ctx.save();
    ctx.font = "600 16px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillStyle = cssVar("--text1") || "#111";
    const v = d.metric === "cost" ? fmtMoney(grand) : d.metric === "requests" ? fmtInt(grand) : fmtTokens(grand);
    ctx.fillText(v, (chartArea.left + chartArea.right) / 2, (chartArea.top + chartArea.bottom) / 2);
    ctx.restore();
  } };
  cDonut = new Chart(canvas, {
    type: "doughnut",
    plugins: [centerText],
    data: { labels: chs, datasets: [{ data: totals, backgroundColor: chs.map(chColor), borderWidth: 2, borderColor: cssVar("--card") }] },
    options: {
      responsive: false, maintainAspectRatio: false, cutout: "62%",
      onClick: (_e, els) => { if (els.length) switchChannel(chs[els[0].index]); },  // 扇区->渠道 tab (spec v4)
      plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } } },
    },
  });
  cDonut.resize();
}

let cHourly = null;

function chartReportHourly(d) {
  const canvas = $("report-hourly");
  if (cHourly) cHourly.destroy();
  const chs = Object.keys(d.series);
  cHourly = new Chart(canvas, {
    type: "bar",
    data: { labels: d.labels.map((h) => `${h}`), datasets: chs.map((ch) => ({ label: ch, data: d.series[ch], backgroundColor: chColor(ch), borderRadius: 2, barPercentage: 0.9 })) },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: chs.length > 1, labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 12 } },
        y: { stacked: true, grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtTokens(v) } },
      },
    },
  });
  cHourly.resize();
}

function renderChannelTable(rows) {
  if (!rows.length) {
    $("report-table").innerHTML = `<tr><td colspan="8" class="empty-cell">${t("reportEmpty")}</td></tr>`;
    return;
  }
  $("report-table").innerHTML = rows.map((r) => `<tr>
    <td style="color:${chColor(r.channel)}">${r.channel}${r.estimated ? ` <span class="est-badge" title="${t("estimateTip")}">${t("estimateBadge")}</span>` : ""}</td>
    <td class="num">${fmtTokens(r.tokens)}</td><td class="num">${fmtTokens(r.input)}</td><td class="num">${fmtTokens(r.output)}</td>
    <td class="num">${fmtTokens(r.cache_read)}</td><td class="num">${fmtInt(r.requests)}</td><td class="num">${fmtMoney(r.cost)}</td>
    <td>${r.channel === "dsh" ? t("dataSinceToday") : (r.data_since || "—")}</td></tr>`).join("");   // R6: dsh 仅今日
}

/* ---------------- 自动同步 ---------------- */
let autoSyncTimer = null;
function restartAutoSync() {
  if (autoSyncTimer) clearInterval(autoSyncTimer);
  if (state.settings.auto_sync === false) return;
  const sec = Math.max(30, Number(state.settings?.sync_interval_sec) || 300) * 1000;
  autoSyncTimer = setInterval(() => {
    const prog = state.data && state.data.progress;
    if (!prog || !prog.running) startSync("incremental");
  }, sec);
}

/* ---------------- 图表辅助 ---------------- */
function cssVar(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim() || "#8a94a8";
}
function rerenderCharts() {
  if (!state.data) return;
  if (!document.getElementById("page-home").hidden) chartToday(state.data.today_trend);
  if (!document.getElementById("page-stats").hidden) {
    chartModel(state.data.models);
    chartTrend(state.data.trend);
    if (zcodeSummaryLast) chartZcodeTrend(zcodeSummaryLast.daily7);  // ZCode 趋势随主题重绘
    if (claudecodeSummaryLast) chartClaudecodeTrend(claudecodeSummaryLast.daily7);  // Claude Code 趋势随主题重绘
  }
}

/* 窗口尺寸变化: 长防抖(250ms)后执行一次轻量 chart.resize()
   (只处理可见页图表 — hidden 页面容器尺寸为 0, resize() 会死循环卡死) */
function safeResize(chart) {
  if (!chart || !chart.canvas) return;
  const box = chart.canvas.parentElement;
  if (box && box.clientWidth > 0 && box.clientHeight > 0) chart.resize();
}
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (!document.getElementById("page-home").hidden) safeResize(cToday);
    if (!document.getElementById("page-stats").hidden) {
      safeResize(cModel);
      safeResize(cTrend);
      safeResize(cZcodeTrend);  // ZCode 趋势图窗口缩放跟随
      safeResize(cClaudecodeTrend);  // Claude Code 趋势图窗口缩放跟随
    }
    if (!document.getElementById("page-overview").hidden) safeResize(cOvTrendChart);
  }, 250);
});

/* ---------------- 启动 ---------------- */
let APP_VERSION = "";  // 后端版本号 (app/__init__.py), 唯一版本源
(async function init() {
  let dark = false, cur = "CNY", l = "zh";
  try {
    dark = localStorage.getItem("gousage-dark") === "1";
    cur = localStorage.getItem("gousage-currency") || "CNY";
    l = localStorage.getItem("gousage-lang") || "zh";
  } catch (e) { /* ignore */ }
  try { const v = await api("/api/version"); APP_VERSION = v.version || ""; } catch (e) { /* ignore */ }
  applyLang(l);
  applyDarkMode(dark);
  applyCurrency(cur);
  bindEvents();
  try { state.settings = await api("/api/settings"); } catch (e) { /* ignore */ }
  syncSettingsPills();
  $("set-auto-sync").checked = state.settings.auto_sync !== false;
  $("set-overview-panel").checked = state.settings.show_accounts_panel === true;
  applyOverviewPanel(state.settings.show_accounts_panel === true);
  await checkState();
  restartAutoSync();
})();
