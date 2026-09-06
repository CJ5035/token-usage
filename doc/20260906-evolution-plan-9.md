# EVOLUTION-9 实施计划：tooltip/i18n 一致性修复（统一 title 机制 + 顶栏刷新提取 + 冗余重渲消除）

- **问题编号**：问题 9（第三轮候选 #3）
- **依据**：`doc/evolution-diagnosis-9.md` v3（门禁1 三轮通过，streak=2）
- **版本**：v2（门禁2 第 1 轮修订：验收⑦扩四视角取证、断言锚函数域、单一调用点、键数盘点、整段平移封口、node --check 门、亮暗顺带；对照表见 `doc/evolution-votes-9-plan.md`）
- **改动原则**：最小化——三条修复线（统一 title 机制 / syncTopBar 提取 / applyCurrency 跳过）；**所有位置以符号名 + grep 锚定定位，不以区间端点为准**（两轮间 HEAD 曾漂移实证）

## 1. 改动文件与内容

### 1.1 `app/web/index.html`（11 处属性改造）

硬编码 `title=` 改为 `data-i18n-title=`（元素 id 为锚）：

| 元素 id | 现值 | 接线键 |
|---|---|---|
| tb-theme（:20） | 切换主题 | themeToggle（新） |
| tb-refresh（:21） | 刷新 | refresh（复用现有 data-i18n 键） |
| tb-user-count（:25） | 已登录用户数 | userCountTip（复用现有，:1507 已在用） |
| tb-min（:29） | Minimize | minimize（新） |
| tb-close（:30） | Close | close（新） |
| side-item home（:37） | Home | navHome（新；若 I18N 已有页面标题键语义吻合可复用，计划实施时盘点） |
| side-item stats（:40） | Stats | navStats（新/复用同上） |
| side-item records（:43） | Records | navRecords（新/复用） |
| side-overview（:47） | Accounts Overview | navAccountsOverview（新/复用） |
| side-item settings（:50） | Settings | navSettings（新/复用） |
| side-item about（:53） | About | navAbout（新/复用） |

保留：:24 tb-login 的 data-i18n-title="userSwitchTip"（已有）、:72 report-est 的 data-i18n-title="estimateTip"（接线后生效）。

### 1.2 `app/web/app.js`

**A. syncI18nTitles() 新增 + 接线**：

```js
function syncI18nTitles() {   // EVOLUTION-9: title/徽标随语言切换 (诊断 R1/R2)
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  const est = $("report-est");
  if (est) est.textContent = t("estimateBadge");   // 徽标文本「估」→ 估算/Est.
}
```

- 调用点：**仅 applyLang 内一处**（静态 data-i18n 遍历之后；init :2541 经由 applyLang 自动覆盖，勿在 init 另加调用）。
- app.js:1502/1507 手动补偿**保留不动**（幂等双写同值）。

**B. syncTopBar(data) 提取（诊断 §5-2）**：

- 从 renderAll 提取顶栏刷新段（tb-sync/tb-login/tb-user-count/tb-updated 四元素写点，:1498-1510 一带）为 `function syncTopBar(data)`，renderAll 原位改为调用 `syncTopBar(data)`（renderAll 行为零变化）。
- applyLang 的 `renderAll(state.data)` 调用（:356）替换为：
  ```js
  if (state.data) {
    syncTopBar(state.data);   // EVOLUTION-9: 顶栏即时换语言 (同值回写, 值不变前缀换语言)
    renderSettings();
    loadRecords().catch(() => {});
  }
  ```
- **以整段逐行平移实现**（不改写任何语句；段内三个局部常量 accLabel/uc/st 无段外引用，已核实安全）。**效果**：renderUsageBlocks/renderCcSummary/renderOverview 写穿三行随 renderAll 不再被 applyLang 调用自然消除；progress 横幅与 renderSettingsSyncProgress 段**不纳入** syncTopBar（切语言恰逢同步进行中为 ≤2.5s pollUntilIdle 自愈瞬态，留档验收）。
- **EVOLUTION-7 兼容**：applyLang 内 updateStatsScopeHint() 调用保留原位（syncTopBar 不碰 hint）。

**C. app.js renderQuotaBar 内 `title="同步失败"`（:2270）**：改 `title="${t("syncFailTip")}"`。

**D. applyCurrency 设置页跳过（诊断 §5-3，:467-475）**：

现结构（:465-466 保留）：
```js
document.querySelectorAll("#set-currency-pills .pill").forEach(...active/localStorage...);
// :467 if (!state.data) return; 之后 :468-475 重渲块
```
改为：货币 pill active/localStorage 更新后，**设置页上下文直接 return**（跳过 :468-475 重渲块）——货币最终一致由 switchPage 回页重载保证。实现形式（在块首加 `if (state.page === "settings") return;` 或等价早退）计划实施时按实际代码取最自然形态；:472-475（loadRecords/zcode/claudecode 分派）一并跳过（均不在设置页可见，回页重载兜底）。

### 1.3 I18N 新增键（zh/en 各约 7-10 个，以实施盘点为准）

已盘点确定需新增（grep 零命中）：themeToggle/minimize/close/navHome/navRecords/navAccountsOverview/syncFailTip（7 个）。
可复用现有键：refresh、userCountTip、estimateBadge、estimateTip、navStats←statsTitle、navSettings←settingsTitle、navAbout←aboutTitle（复用则不新增；实施时若语义/文案不合适可改为新增独立键，10 键上限口径与测试第 4 条一致）。
zh 文案：切换主题/最小化/关闭/首页/用量统计/使用记录/账户总览/设置/关于/同步失败（nav* 若复用现有页面标题键则以现有文案为准）。
en：Toggle theme/Minimize/Close/Home/Usage Stats/Records/Accounts Overview/Settings/About/Sync failed。
插入位置按 I18N 既有分组习惯。

### 1.4 `tests/test_i18n_consistency.py`（新增，约 80 行，源码静态断言）

1. **硬编码 title 清零断言**：index.html 中 `title="` 的非 data-i18n-title 硬编码**仅允许**既有合法残留清单之外为零——具体锚定：上述 11 个元素 id 均含 `data-i18n-title=`；全文 grep `title="切换主题"|title="Minimize"|title="Home"` 等旧值零命中。
2. **机制存在断言**：app.js 含 `function syncI18nTitles`、含 `[data-i18n-title]` 遍历、applyLang 内含 `syncTopBar(`、含 `syncI18nTitles()`。
3. **renderAll 解耦防退化锚**：applyLang 函数体内**不再出现** `renderAll(` 调用（锚定 applyLang 函数体片段，勿全文件反向匹配）。
4. **I18N 契约**：10 个新键 zh/en 双语存在；estimateBadge/estimateTip/userCountTip/refresh 键存在（复用锚）。
5. **applyCurrency 断言**：函数体（锚定 `#set-currency-pills` 处理段）在 pill 更新后、重渲块前含 settings 上下文早退（锚定实际实现文本）。
6. **回归锚**：renderAll 函数仍存在且首行仍为 `state.data = data`；手动补偿保留（**锚函数域**：`userSwitchTip`/`userCountTip` 在 renderAll/syncTopBar 函数域内、`syncFailTip` 在 renderQuotaBar 函数域内、「同步失败」硬编码全文件零命中——勿按行号锚定，提取后行号必漂移）。

## 2. 不改动清单

- renderAll 自身逻辑（仅提取，行为零变化）、rerenderCharts/EVOLUTION-4 缓存、seq 守卫（EVOLUTION-5）、:1502/:1507 手动补偿
- records 页 loadRecords/loadSessions 行为、总览页 loadOverview（回页重载覆盖，诊断 §7）；applyLang 保留的 loadRecords() 写穿同族（网络请求+隐藏记录容器，回页重载兜底）——**留档备选池**，本批不处理
- db.py/server.py 零改动
- 空态三套写法/.wb-v/overflow-y:overlay（备选池）
- tb-login/report-est 既有 data-i18n-title 属性（接线后自然生效）

## 3. 实施备注

1. **符号名锚定**：所有定位以元素 id/函数名 + grep 为准，行号仅参考（两轮间漂移实证）。
2. syncTopBar 提取时**逐行平移**，不改写任何语句（含 renderSyncBanner? ——注意：renderSyncBanner/renderSettingsSyncProgress（:1511-1512 一带）**留在 renderAll 内不提取**，applyLang 不再触达它们——切语言恰逢同步的瞬态由 pollUntilIdle 自愈）。
3. nav* 键若复用现有页面标题键（如 statsTitle），tooltip 文案与页面标题同文案可接受（更一致）；实施时以 I18N 现状盘点定。
4. syncI18nTitles 中 report-est 文本设置**不影响 hidden 态**（hidden 时写文本无副作用）。
5. applyCurrency 早退形态以实际代码最自然者为准则（if early-return），勿重构周边。
6. 全部新键/en 文案以既有 en 翻译风格（简短、Title Case 导航）为准。

## 4. 验收清单

| # | 条目 | 方式 |
|---|---|---|
| ① | 切语言后停留设置页：顶栏 tooltip（主题/刷新/最小化/关闭/用户数）即时切换；**亮暗各拍一张** | 实拍 + DOM title 断言 |
| ② | 切语言后侧栏导航 tooltip 即时切换（Home/Stats/…） | DOM 断言 |
| ③ | 中文 UI 无英文 tooltip、英文 UI 无中文 tooltip（12 处全量） | DOM 遍历断言（静态测试锚定）+ 实拍抽查 |
| ④ | 估算徽标：英文 UI 显示「Est.」、tooltip 显示 estimateTip 文案；中文「估算」；**亮暗各拍一张**；布局观察留档（.est-badge inline-flex 自适应，「估」→「估算」增宽 ~10px 无挤压，且与本就显示 t("estimateBadge") 的其余 4 处徽标统一，消除「估」vs「估算」不一致） | 实拍 + DOM |
| ⑤ | 配额卡同步失败 ⚠ tooltip 随语言（静态断言覆盖） | pytest |
| ⑥ | 切语言后顶栏 tb-updated 值不变、tb-sync/tb-login 文案换语言 | DOM 断言（同值不变式） |
| ⑦ | 切语言后**依次切回首页 all/单渠道、统计、记录、总览四视角：语言与口径一致**（switchPage 回页重载兜底机制的取证——本计划最高风险假设） | 实拍留档 |
| ⑧ | applyCurrency 切货币后设置页无重渲异常、切回统计页货币正确 | 实拍 |
| ⑨ | `node --check app/web/app.js` 语法门 + 静态断言全过 + 全量 pytest 通过 | node + pytest |

## 5. 回滚方案

- git 单提交（信息 `product-evolution: 问题9 tooltip/i18n一致性修复`），异常 `git revert <commit>`。
- 改动 2 个源文件 + 1 个新测试文件，无逻辑重写（提取+属性改造），回滚无残留。

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| syncTopBar 提取遗漏/多提语句 | 逐行平移纪律 + 备注明确 renderSyncBanner 段不提取；验收 ⑥ 回归 |
| data-i18n-title 属性改造影响 CSS/JS 选择器 | 已核实 style.css/app.js 无 [title] 选择器；元素 id 未变，JS 定位安全 |
| nav* 复用键语义不符 | 实施时 I18N 盘点，宁可新增键也不勉强复用 |
| applyCurrency 早退误伤（:472-475 中有非重渲逻辑） | 已核实 :472-475 均为重渲/分派（loadRecords/zcode/cc），回页重载兜底；验收 ⑧ |
| 切语言恰逢同步进行中横幅瞬态 | ≤2.5s 自愈（pollUntilIdle），验收矩阵留档 |
