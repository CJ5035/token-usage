# Codex 用量修复实施计划：移除今日行 KPI + 渠道色换品红

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 统计页「Codex 本地用量」区块移除固定按今日聚合的今日行 KPI（消除双行重复）；Codex 渠道色从青绿换成品红（亮 `#c026d3` / 暗 `#e879f9`），消除与 commandcode 翡翠绿的撞色。

**Architecture:** 纯前端静态资源改动（index.html / app.js / style.css）。后端 `/api/codex/summary` 契约保持原样（`today` 字段继续返回，前端不再消费），服务端零改动。渠道色仍走 `--ch-codex` CSS 变量单一定义源，JS 取色链路（`CH_COLOR` → `chColor()`）不动。

**Tech Stack:** Python 3.12（pytest 契约测试）、原生 JS + CSS 变量、`node --check`（JS 语法门禁）。

**Spec:**
- `doc/bug-diagnosis-codex-duplicate-kpi-20260907.md`（今日行重复根因与 DB 实测）
- `doc/bug-diagnosis-codex-color-20260907.md`（撞色根因与候选色实测）

## Global Constraints

- **后端零改动**：`app/server.py`、`app/db.py` 不动；`/api/codex/summary` 返回键集合不变（`tests/test_codex_server.py:128-131` 的契约断言不得修改）。今日行的"固定按今日聚合"仅从**展示层**移除。
- **范围假设（已与用户确认方向）**：用户决定"不需要固定按今日聚合的今日行"= 今日行整体移除（所有 range 档位都不显示），而非仅 range=今日 时隐藏。
- **配色成对修改**：亮/暗两个主题块的 `--ch-codex` 必须同一批次改掉，注释沿用 style.css 既有 `原 X → Y (原因)` 惯例。
- **验证门禁**：定向 pytest 全绿 + `node --check app/web/app.js` 通过；收尾跑全量 `python -m pytest tests/ -q`（基线 459 passed，本计划允许新增断言不允许破坏既有）。
- **不自动签入**：提交步骤必须等用户人工确认后执行。
- 外科手术式修改：不碰无关代码、不重构、不调整无关格式。

---

### Task 1: 移除 Codex 统计区块「今日行」KPI

**Files:**
- Modify: `tests/test_codex_ui_contract.py:21-24`（契约测试先行）
- Modify: `app/web/index.html:162`（删今日行容器）
- Modify: `app/web/app.js:1260,1269-1270,1280,1294-1295`（`renderCodexSummary` 内 todayKpis 全部 5 行引用）
- Modify: `app/web/style.css:487`（删除因本改动而失效的孤儿选择器）
- Modify: `scripts/check_codex_ui.cjs:123-124`（T8 浏览器验收脚本同步删今日行断言，否则 locator 超时失败）

**Interfaces:**
- Consumes: 无。
- Produces: `renderCodexSummary` 只渲染一个 KPI 容器 `#codex-kpis`（数据源 `data.totals`）；契约测试不再要求 `codex-today-kpis` 且显式断言其不存在。Task 3 的全量回归依赖本任务产出的测试绿态。

- [ ] **Step 1: 修改契约测试（写失败测试）**

`tests/test_codex_ui_contract.py` 的 `test_codex_stats_nodes`（第 21-24 行）改为：

```python
    expected = {"codex-stats", "codex-kpis",
                "codex-prov-head", "codex-prov-body", "codex-model-head",
                "codex-model-body", "codex-trend-chart", "codex-missing", "codex-error"}
    assert expected <= p.ids
    assert "codex-today-kpis" not in p.ids   # 今日行已移除: range=今日时与总量行必然重复 (20260907)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_codex_ui_contract.py::test_codex_stats_nodes -v`
Expected: FAIL —— `"codex-today-kpis" not in p.ids` 断言失败（元素还在 index.html 里）。

- [ ] **Step 3: 删除 index.html 今日行容器（第 162 行）**

```html
<!-- 原 (index.html:161-162) -->
        <div class="kpi-row" id="codex-kpis"></div>
        <div class="kpi-row" id="codex-today-kpis"></div>
<!-- 改为 -->
        <div class="kpi-row" id="codex-kpis"></div>
```

- [ ] **Step 4: 删除 app.js 中 renderCodexSummary 的 todayKpis 全部 5 行引用（4 处编辑）**

执行前先 Read `app/web/app.js` 的 `renderCodexSummary`（约 1254-1295 行）确认精确缩进，然后逐处 Edit：

① 删除 const 声明（第 1260 行）：

```js
// 原
  const kpis = $("codex-kpis");
  const todayKpis = $("codex-today-kpis");
  const tables = box.querySelector(".codex-table-scroll");
// 改为
  const kpis = $("codex-kpis");
  const tables = box.querySelector(".codex-table-scroll");
```

② 删除 missing 分支两行（第 1269-1270 行）：

```js
// 原
    kpis.innerHTML = "";
    todayKpis.hidden = true;
    todayKpis.innerHTML = "";
    tables.hidden = true;
// 改为
    kpis.innerHTML = "";
    tables.hidden = true;
```

③ 删除可见分支一行（第 1280 行）：

```js
// 原
  kpis.hidden = false;
  todayKpis.hidden = false;
  tables.hidden = false;
// 改为
  kpis.hidden = false;
  tables.hidden = false;
```

④ 删除渲染行（第 1294-1295 行，注释一并删除）：

```js
// 原
  kpis.innerHTML = cards(data.totals || {}).join("");     // 总量行 ← totals
  todayKpis.innerHTML = cards(data.today || {}).join(""); // 今日行 ← today
// 改为
  kpis.innerHTML = cards(data.totals || {}).join("");
```

- [ ] **Step 5: 删除 style.css 孤儿规则（第 487 行）**

本改动使 `.codex-stats` 内不再有第二个 `.kpi-row`，该选择器永不匹配（自己制造的孤儿，按规约清除）：

```css
/* 原 (style.css:486-487) */
.codex-stats .kpi-row { grid-template-columns: repeat(6, minmax(0, 1fr)); }
.codex-stats .kpi-row + .kpi-row { margin-top: 0; }
/* 改为 */
.codex-stats .kpi-row { grid-template-columns: repeat(6, minmax(0, 1fr)); }
```

- [ ] **Step 6: 同步修改 T8 浏览器验收脚本（scripts/check_codex_ui.cjs:123-124）**

今日行删除后 `#codex-today-kpis` 定位不到元素会使脚本超时失败，断言行删除、ok() 文案同步收敛：

```js
// 原 (第 123-124 行)
      assert.match(await page.locator("#codex-today-kpis").innerText(), /130/);
      ok("stats range today: totals/today both 130");
// 改为
      ok("stats range today: totals 130");
```

- [ ] **Step 7: 跑测试确认通过 + JS 语法门禁**

Run: `python -m pytest tests/test_codex_ui_contract.py tests/test_codex_server.py -v`
Expected: PASS（ui_contract 全绿；codex_server 契约未动应保持绿，验证后端契约确实零影响）。

Run: `node --check app/web/app.js && node --check scripts/check_codex_ui.cjs`
Expected: 无输出（语法通过）。

---

### Task 2: Codex 渠道色换品红

**Files:**
- Modify: `tests/test_dark_theme.py`（冻结断言豁免 + 新值锚定测试，TDD 先行）
- Modify: `app/web/style.css:37`（亮色）、`app/web/style.css:68`（暗色）

**Interfaces:**
- Consumes: 无（与 Task 1 独立，可并行执行）。
- Produces: `--ch-codex` 亮 `#c026d3` / 暗 `#e879f9`。所有图表/图例/明细表经 `CH_COLOR`（app.js:2435）自动取到新色，JS 零改动。

> **背景（Review 2 实证）**：`tests/test_dark_theme.py` 有两处 HEAD 基准冻结断言——
> `test_root_tokens_unchanged_from_head` 冻结 `:root` 全部既有 token 值（`_ROOT_ADDED_ALLOWED`
> 只豁免"新增声明"，`--ch-codex` 在 HEAD 已存在，改值必 FAIL）；`test_dark_untouched_tokens_
> unchanged_from_head` 的 dark 换值集合只含 `_DARK_EXPECTED ∪ {--up, --down}`，dark 改值必 FAIL。
> 故本任务必须先更新冻结测试并锚定新值。

- [ ] **Step 1: 更新 test_dark_theme.py（写失败测试）**

三处修改：

① 模块级新增常量（放在 `_ROOT_ADDED_ALLOWED` 之后，约第 48 行）：

```python
# 20260907 Codex 渠道色换品红 (与 commandcode 撞色修复, 用户指定): :root/dark 改值豁免 + 新值锚定
_ROOT_RECOLOR_ALLOWED = {"--ch-codex"}
```

② `test_dark_untouched_tokens_unchanged_from_head`（约第 146 行）换值集合加入 `--ch-codex`：

```python
# 原
    changed = set(_DARK_EXPECTED) | {"--up", "--down"}
# 改为
    changed = set(_DARK_EXPECTED) | {"--up", "--down", "--ch-codex"}   # --ch-codex: 20260907 换品红
```

③ `test_root_tokens_unchanged_from_head`（约第 183 行）冻结循环豁免换值 token，并在文件末尾追加新锚定测试：

```python
# 原 (test_root_tokens_unchanged_from_head 内)
    for token, value in head.items():
        assert cur.get(token) == value, f":root 变量被改动: {token}: {value!r} -> {cur.get(token)!r}"
# 改为
    for token, value in head.items():
        if token in _ROOT_RECOLOR_ALLOWED:
            continue
        assert cur.get(token) == value, f":root 变量被改动: {token}: {value!r} -> {cur.get(token)!r}"
```

```python
# 文件末尾追加
def test_codex_channel_color_recolored_20260907():
    """20260907 Codex 渠道色换品红: :root #c026d3 / dark #e879f9 (撞色修复, 用户指定)."""
    root = _root_vars(_css())
    dark = _dark_vars(_css())
    assert root["--ch-codex"] == "#c026d3"
    assert dark["--ch-codex"] == "#e879f9"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_dark_theme.py -v`
Expected: 仅新增的 `test_codex_channel_color_recolored_20260907` FAIL（CSS 仍是旧色值 `#0f766e`/`#2dd4bf`），其余用例 PASS（冻结豁免后旧值不再比对）。

- [ ] **Step 3: 修改亮色值（style.css:37）**

```css
/* 原 */
  --ch-codex: #0f766e;          /* T5: Codex 渠道色 (亮) */
/* 改为 */
  --ch-codex: #c026d3;          /* 原 #0f766e: 青绿 → 品红 (与 commandcode 撞色, 用户指定) */
```

- [ ] **Step 4: 修改暗色值（style.css:68）**

```css
/* 原 */
  --ch-codex: #2dd4bf;          /* T5: Codex 渠道色 (暗) */
/* 改为 */
  --ch-codex: #e879f9;          /* 原 #2dd4bf: 青绿 → 品红 (与 commandcode 撞色, 用户指定) */
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_dark_theme.py tests/test_codex_ui_contract.py -v`
Expected: PASS（新锚定测试转绿；冻结断言因豁免保持绿；ui_contract 只锁 `--ch-codex:` 存在性不受影响）。

---

### Task 3: 全量回归、文档收尾与签入

**Files:**
- Modify: `doc/bug-diagnosis-codex-color-20260907.md`（状态行）
- Modify: `doc/bug-diagnosis-codex-duplicate-kpi-20260907.md`（状态行）

**Interfaces:**
- Consumes: Task 1/2 的全部改动已就位。
- Produces: 全量测试绿态 + 已更新的诊断报告状态 + 待人工确认的本地提交。

- [ ] **Step 1: 全量回归（编译门禁等效）**

Run: `python -m pytest tests/ -q`
Expected: 全部 passed（基线 459；本计划新增契约负断言与 Codex 新色锚定测试各 1 处、修改 2 处冻结集合，不删除任何既有断言）。若有失败，修复后重跑至全绿才能进入下一步。

- [ ] **Step 2: 更新两份诊断报告状态**

`doc/bug-diagnosis-codex-color-20260907.md` 第 4 行：

```markdown
<!-- 原 -->
- **状态**：已确认（待用户确认换色方案后实施）
<!-- 改为 -->
- **状态**：已修复（品红方案，2026-09-07 实施并回归通过）
```

`doc/bug-diagnosis-codex-duplicate-kpi-20260907.md` 第 4 行：

```markdown
<!-- 原 -->
- **状态**：已确认（DB 实测复现；待用户确认修复方案后实施）
<!-- 改为 -->
- **状态**：已修复（今日行整体移除，2026-09-07 实施并回归通过）
```

- [ ] **Step 3: 人工验收（用户执行，需重新启动应用）**

源码模式 `python entry.py` 或重新打包后验证：
1. 统计页 → Codex 本地用量：只有**一行** KPI（任意 range 档位，含「今日」档，不再出现第二行）。
2. 首页/统计页图表：Codex 分段、图例圆点、明细表渠道名为品红色，与 commandcode 绿色一眼可分。
3. 亮色/暗色主题各检查一遍（暗色 `#e879f9`、亮色 `#c026d3`）。
4. 切换 range（今日/昨天/7d/30d/全部）与语言（中/英），Codex 区块渲染正常。
5. （可选，T8 门禁）先起夹具服务 `python scripts/serve_codex_fixture.py`，再按脚本头部说明运行 `node scripts/check_codex_ui.cjs <fixture-url>`：统计页 range=today/all 断言通过、无 pageerror。

- [ ] **Step 4: 签入（必须等用户确认后执行）**

```bash
git add app/web/index.html app/web/app.js app/web/style.css tests/test_codex_ui_contract.py tests/test_dark_theme.py scripts/check_codex_ui.cjs
git commit -m "fix: drop codex today kpi row and recolor codex channel to magenta"
# doc/ 下诊断与计划文档是否一并提交由用户决定:
# git add doc/bug-diagnosis-codex-*.md doc/20260907-codex-stats-fix-plan.md
```
