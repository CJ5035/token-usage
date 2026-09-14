# 浅色 Slate/Indigo 配色方案实施计划

> **For agentic workers:** 按任务顺序执行，步骤用 `- [ ]` 跟踪。每步含可验证命令。

**Goal:** 将 GoGauge 亮色主题从"晨雾紫"整体替换为用户选定的 Slate/Indigo 配色（页面/文本/品牌/渠道 14 个给定值 + 派生令牌补齐），暗色主题逐像素不变。

**Architecture:** 纯令牌替换 —— 渠道色与语义色已全部走 CSS 变量（`app/web/app.js:2779` 的 `CH_COLOR` 引用 `var(--ch-*)`），因此只需改 `style.css` 的 `:root` 块、2 处硬编码渐变、`app.js` 4 处兜底 hex、`app/main.py` 3 处窗口底色 hex；不改任何选择器规则与 JS 逻辑。TDD 顺序：先把测试锚点重定标到新值（红），再改实现（绿）。

**Tech Stack:** 原生 CSS 变量 / vanilla JS / Python 3.12.10（pyenv-win，`python`）/ pytest。

**Spec（用户给定量，逐字）:**

```css
/* 页面 */
--bg-0: #F8FAFC;  --bg-1: #FFFFFF;  --bg-2: #F1F5F9;  --border: #E2E8F0;
/* 文本 */
--text-1: #0F172A;  --text-2: #475569;  --text-3: #94A3B8;
/* 品牌主色 */
--brand: #4F46E5;
/* 渠道图表颜色 */
--c-zcode: #4F46E5;  --c-dsh: #64748B;  --c-commandcode: #0891B2;
--c-claudecode: #D97706;  --c-codex: #E11D48;  --c-bai: #7C3AED;
```

## Global Constraints

- **暗色主题不动**：`html[data-theme="dark"]` 块及一切 dark 断言保持现状。
- **hex 一律小写**（style.css 现有约定；测试解析器按原文比对）。
- 方案未给 opencode 渠道色 → 取 Tailwind blue-600 **`#2563eb`**（与 slate/indigo 同族，与 zcode/commandcode 拉开）。
- 品牌派生令牌按 indigo 标度补齐：`--primary-strong`/hover = **indigo-700 `#4338ca`**，`--primary-soft` = **indigo-50 `#eef2ff`**。
- 非渠道图表令牌（`--chart-input/output/reasoning/cache/cost/extra`、`--account-2..6`）、语义色（`--up/--down/--danger/--blue/--green/--purple/--cyan/--amber/--red`）、tooltip 三令牌**保持不变**。
- 不为浅色新增对比度门禁：`--text3 #94a3b8` 与现状 `#938ea8` 同级（装饰性弱文本），非回归。
- 遵守仓库规则：修改后执行编译/测试验证；**不自动签入**，人工确认后才 commit。
- Python 用 `python`（pyenv-win 3.12.10）；禁止 `py`/`python.exe` 绝对路径。

## 令牌映射表（:root 亮色，唯一事实源）

| 令牌 | 现值 | 新值 | 来源 |
|---|---|---|---|
| `--bg` | `#f7f6f4` | `#f8fafc` | bg-0 |
| `--card` | `#ffffff` | `#ffffff` | bg-1（不变） |
| `--border` | `#eae7f2` | `#e2e8f0` | border |
| `--muted` | `#f1eff6` | `#f1f5f9` | bg-2 |
| `--titlebar` | `#ffffff` | `#ffffff` | bg-1（不变） |
| `--sidebar` | `#fbfaf8` | `#ffffff` | bg-1（白侧栏 + 边框分隔，Linear 式） |
| `--hover` | `#f3f0fb` | `#f1f5f9` | bg-2 |
| `--grid` | `#efedf5` | `#f1f5f9` | bg-2（浅于 border） |
| `--shadow` | `rgba(30,20,60,…)` 紫调 | `0 1px 2px rgba(15,23,42,0.05), 0 6px 20px rgba(15,23,42,0.06)` | text-1 中性化 |
| `--text` / `--text1` | `#221f33` | `#0f172a` | text-1 |
| `--text2` | `#5f5b73` | `#475569` | text-2 |
| `--text3` | `#938ea8` | `#94a3b8` | text-3 |
| `--primary` | `#7c5cf6` | `#4f46e5` | brand |
| `--primary-strong` | `#6a46ea` | `#4338ca` | indigo-700（派生） |
| `--primary-soft` | `#f2eefe` | `#eef2ff` | indigo-50（派生） |
| `--grad-brand` | `linear-gradient(135deg,#8b5cf6,#5b8def)` | `linear-gradient(135deg, #4f46e5, #2563eb)` | brand→opencode 蓝 |
| `--button-primary-bg` | `#7c5cf6` | `#4f46e5` | brand |
| `--button-primary-hover` | `#6a46ea` | `#4338ca` | indigo-700 |
| `--focus-ring` | `#7c5cf6` | `#4f46e5` | brand |
| `--surface-popover` | `#ffffff` | `#ffffff` | 不变 |
| `--border-popover` | `#eae7f2` | `#e2e8f0` | border |
| `--account-1` | `#7c5cf6` | `#4f46e5` | brand（account-1 锚定主色） |
| `--ch-opencode` | `#4f8ef7` | `#2563eb` | 补齐决策 |
| `--ch-bai` | `#f59e0b` | `#7c3aed` | c-bai |
| `--ch-commandcode` | `#10b981` | `#0891b2` | c-commandcode |
| `--ch-zcode` | `#6366f1` | `#4f46e5` | c-zcode |
| `--ch-claudecode` | `#c2410c` | `#d97706` | c-claudecode |
| `--ch-dsh` | `#64748b` | `#64748b` | c-dsh（不变） |
| `--ch-codex` | `#c026d3` | `#e11d48` | c-codex |

其余 `:root` 令牌（`--blue/--green/--purple/--cyan/--amber/--red/--danger/--danger-soft/--up/--down/--chart-*/--account-2..6/--refresh-hover-text/--danger-*/--button-primary-text/--chart-tooltip-*/--radius/--font-*`）**不变**。

---

### Task 1: 测试锚点重定标（先红）

**Files:**
- Modify: `tests/test_dark_theme.py`（`test_codex_channel_color_recolored_20260907` 的 root 断言 + `_ROOT_THEME_EXPECTED` 5 值）
- Modify: `tests/test_empty_state.py`（`test_root_channel_color_vars_unchanged` 2 行）
- Modify: `tests/test_i18n_consistency.py`（`test_root_channel_colors_unchanged` 5 行，dsh 行不变）
- Modify: `tests/test_theme_rerender.py:157`（兜底 hex）
- Modify: `tests/test_theme_preferences.py:142-155`（4 处 `#f7f6f4`）

**Interfaces:**
- Consumes: 上方映射表（唯一事实源）。
- Produces: 5 个测试文件的新锚点值；Task 2/3 的实现以使这些测试转绿为准。

- [ ] **Step 1: 改 `tests/test_dark_theme.py`**

`test_codex_channel_color_recolored_20260907` 的 docstring 末尾追加 `；20260911 浅色重定标 slate/indigo（dark 不变）`，root 三行改为：

```python
    assert root["--ch-codex"] == "#e11d48"
    assert dark["--ch-codex"] == "#d946ef"
    assert root["--ch-claudecode"] == "#d97706"
    assert dark["--ch-claudecode"] == "#d97757"
    assert root["--ch-bai"] == "#7c3aed"
    assert dark["--ch-bai"] == "#facc15"
```

`_ROOT_THEME_EXPECTED` 改 5 个值（其余 20 个不动）：

```python
    "--button-primary-bg": "#4f46e5",
    "--button-primary-hover": "#4338ca",
    "--border-popover": "#e2e8f0",
    "--focus-ring": "#4f46e5",
    "--account-1": "#4f46e5",
```

- [ ] **Step 2: 改 `tests/test_empty_state.py`**

`test_root_channel_color_vars_unchanged` docstring 改为 `""":root 渠道配色 20260911 slate/indigo 基线 (commandcode 青 / zcode 靛蓝)."""`，断言改为：

```python
    assert "--ch-commandcode: #0891b2" in root
    assert "--ch-zcode: #4f46e5" in root
```

- [ ] **Step 3: 改 `tests/test_i18n_consistency.py`**

`test_root_channel_colors_unchanged` 的六行元组改为（注释同步更新）：

```python
        "--ch-opencode: #2563eb;",
        "--ch-bai: #7c3aed;",
        "--ch-commandcode: #0891b2;",
        "--ch-zcode: #4f46e5;",
        "--ch-claudecode: #d97706;",   # 20260911: 品牌橙 → amber-600 (slate/indigo 方案)
        "--ch-dsh: #64748b;",
```

- [ ] **Step 4: 改 `tests/test_theme_rerender.py:157`**

```python
    assert 'CH_COLOR[ch] || "#2563eb"' in src
```

- [ ] **Step 5: 改 `tests/test_theme_preferences.py:142-155`**

4 处 `"#f7f6f4"` 全部改为 `"#f8fafc"`（含 `("neon", ...)` 损坏值回退行与最终 assert）。

- [ ] **Step 6: 运行确认红**

Run: `python -m pytest tests/test_dark_theme.py tests/test_empty_state.py tests/test_i18n_consistency.py tests/test_theme_rerender.py tests/test_theme_preferences.py -x -q`
Expected: FAIL（实现还是旧值；首个失败应为 `test_codex_channel_color_recolored_20260907` 的 `AssertionError: assert '#c026d3' == '#e11d48'`，或因用例执行顺序而异的同类色值不等）

- [ ] **Step 7: Commit（人工确认后）**

```bash
git add tests/test_dark_theme.py tests/test_empty_state.py tests/test_i18n_consistency.py tests/test_theme_rerender.py tests/test_theme_preferences.py
git commit -m "test: re-anchor light palette to slate/indigo 20260911"
```

---

### Task 2: style.css :root 令牌替换 + 2 处硬编码渐变（转绿）

**Files:**
- Modify: `app/web/style.css:2-70`（`:root` 块，按映射表 26 处改值）
- Modify: `app/web/style.css:283`、`app/web/style.css:291`（`.ub.c-rolling` 两处紫渐变）
- Modify: `app/web/style.css` dark 块第 92/95/97 行**仅注释**（旧亮值引用失效，令牌值不动）
- Test: `tests/test_dark_theme.py`、`tests/test_empty_state.py`、`tests/test_i18n_consistency.py`

**Interfaces:**
- Consumes: Task 1 的新锚点。
- Produces: `:root` 新令牌值；选择器规则与 dark 令牌值不变；`:root` 渠道 7 行与 dark 块 3 条渠道注释按 Step 3 指定文本整行替换（事实修正，非顺手清理）。

- [ ] **Step 1: 替换 `:root` 令牌值**

按"令牌映射表"逐行改 26 个值（`--card/--titlebar/--surface-popover/--ch-dsh` 值不变不动）。注意 `--text` 与 `--text1` 两行都要改。`--shadow` 整行替换为：

```css
  --shadow: 0 1px 2px rgba(15, 23, 42, 0.05), 0 6px 20px rgba(15, 23, 42, 0.06);
```

`--grad-brand` 整行替换为：

```css
  --grad-brand: linear-gradient(135deg, #4f46e5, #2563eb);
```

文件头注释 `/* GoGauge 正式版 - 晨雾紫 + Data-Dense Dashboard */` 改为 `/* GoGauge 正式版 - Slate/Indigo (20260911) + Data-Dense Dashboard */`。

- [ ] **Step 2: 替换 2 处硬编码渐变**

`style.css:283` 与 `style.css:291` 的 `linear-gradient(90deg, #a78bfa, #7c5cf6)` → `linear-gradient(90deg, #818cf8, #4f46e5)`（indigo-400→600，沿用原"浅→深"结构）。

- [ ] **Step 3: 修正换值后事实失效的注释（否则 Task 4 残留扫描必然命中旧 hex）**

`:root` 渠道 7 行整行替换为（值 + 注释同步，行尾对齐风格照旧）：

```css
  --ch-opencode: #2563eb;       /* 20260911 slate/indigo 方案: blue-600 (方案未给, 同族补齐) */
  --ch-bai: #7c3aed;            /* 20260911 slate/indigo 方案: violet-600 (用户给定) */
  --ch-commandcode: #0891b2;    /* 20260911 slate/indigo 方案: cyan-600 (用户给定) */
  --ch-zcode: #4f46e5;          /* 20260911 slate/indigo 方案: indigo-600 = 品牌主色 (用户给定) */
  --ch-claudecode: #d97706;     /* 20260911 slate/indigo 方案: amber-600 (用户给定) */
  --ch-dsh: #64748b;            /* slate-500, 新旧方案同值 */
  --ch-codex: #e11d48;          /* 20260911 slate/indigo 方案: rose-600 (用户给定) */
```

dark 块**仅改注释、令牌值不动**，3 行整行替换为：

```css
  --ch-bai: #facc15;            /* 20260908: 金黄 yellow-400, 暗档专用 (亮档 20260911 起 #7c3aed) */
  --ch-claudecode: #d97757;     /* 20260908: Claude 品牌陶土橙 (亮档 20260911 起 #d97706; 暗卡 5.57) */
  --ch-codex: #d946ef;          /* 20260908: fuchsia-500 (亮档 20260911 起 #e11d48; 暗卡 5.03) */
```

（dark 块渠道行缩进与 :root 同为 2 空格，按整行替换；`--ch-opencode/--ch-commandcode/--ch-zcode/--ch-dsh` 四行无旧亮值引用，整行不动。）

- [ ] **Step 4: 运行确认绿**

Run: `python -m pytest tests/test_dark_theme.py tests/test_empty_state.py tests/test_i18n_consistency.py -q`
Expected: PASS（含 dark 固定值、dark 对比度、c-slate 反向断言等全部既有用例）

- [ ] **Step 5: Commit（人工确认后）**

```bash
git add app/web/style.css
git commit -m "feat: swap light theme tokens to slate/indigo palette"
```

---

### Task 3: app.js 兜底渠道色 + main.py 窗口底色

**Files:**
- Modify: `app/web/app.js:2892,2903,2977,3094`（4 行共 7 处 `"#4f8ef7"` 字面量：2892×2、2903×2、2977×2、3094×1）
- Modify: `app/main.py:503`（docstring 内 `#f7f6f4`）、`:509`、`:584`、`:767`
- Test: `tests/test_theme_rerender.py`、`tests/test_theme_preferences.py`

**Interfaces:**
- Consumes: Task 1 锚点（兜底 `#2563eb`、窗口底色 `#f8fafc`）。
- Produces: 运行时与测试一致；webview 窗口原生底色 = 新 `--bg`。

- [ ] **Step 1: app.js 7 处 `"#4f8ef7"` → `"#2563eb"`**

行内模板五处（2892 ×2、2903 ×2、3094 ×1）与 `cssVar()` 兜底两处（2977）。用编辑器全局替换 `"#4f8ef7"` → `"#2563eb"`。替换前复核：`grep -c 4f8ef7 app/web/app.js` 预期输出 `4`（4 行；Python `src.count('"#4f8ef7"')` 为 7 处）；替换后预期 `grep -c 4f8ef7` 输出 `0`、`grep -c 2563eb` 输出 `4`（app.js 当前不含 2563eb，替换后恰好 4 行）。

- [ ] **Step 2: main.py 3 处 `#f7f6f4` → `#f8fafc`**

`:509`（`_theme_background_color` 返回值）、`:584`、`:767`（两处 `background_color=`），并把 `:503` docstring 中 `light --bg #f7f6f4` 改为 `light --bg #f8fafc`。

- [ ] **Step 3: 编译验证（仓库规则：编译通过才算完成）**

Run: `python -m py_compile app/main.py`
Expected: 无输出（退出码 0）

- [ ] **Step 4: 运行确认绿**

Run: `python -m pytest tests/test_theme_rerender.py tests/test_theme_preferences.py -q`
Expected: PASS

- [ ] **Step 5: Commit（人工确认后）**

```bash
git add app/web/app.js app/main.py
git commit -m "feat: align js fallback and window bg with slate/indigo palette"
```

---

### Task 4: 全量回归 + 目视验证

**Files:** 无新增改动（仅验证）。

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全 PASS。若有意料外失败：只在本计划映射表范围内排查（旧 hex 残留），不做扩大化修复。

- [ ] **Step 2: 残留扫描**

Run: `grep -rn "#7c5cf6\|#6a46ea\|#f2eefe\|#c026d3\|#c2410c\|#10b981\|#6366f1\|#f59e0b\|#f7f6f4\|#eae7f2" app/`
Expected: **唯一允许 1 处命中** —— `app/web/style.css:293` 的 `#f59e0b`（`.ub.c-month .ub-bar-fill` 月度用量条 amber→red 热力语义渐变，非品牌/渠道色，本方案刻意保留不改）；其余 0 命中。

- [ ] **Step 3: 目视验证**

Run: `python entry.py`（或 `build.bat` 后运行）启动应用，浅色下检查：侧栏/卡片/边框层次、主按钮与焦点环靛蓝、七渠道图例色（opencode 蓝 / zcode 靛蓝 / commandcode 青 / claudecode 琥珀 / codex 玫红 / bai 紫 / dsh 灰）、切到暗色确认无变化。

- [ ] **Step 4: Commit（人工确认后）**

无需提交（验证任务）。如目视发现问题，回到对应 Task 修令牌值，不要改选择器。

---

## Self-Review 记录

- **Spec 覆盖**：14 个给定量 → 映射表全覆盖（bg-0/1/2、border、text-1/2/3、brand、6 渠道）；opencode 缺口已显式决策 `#2563eb`；派生品牌令牌决策已列入约束。
- **占位符扫描**：无 TBD/TODO；每步含具体值或命令。
- **类型一致**：测试锚点（Task 1）与实现值（Task 2/3）逐值一致；hex 全小写与 CSS 文件约定一致；dark 值引用（`#d946ef/#d97757/#facc15`）照抄现有断言未动。
- **已知非目标**：暗色主题、选择器结构、非渠道图表令牌、`--text3` 对比度现状（新旧值同级，不新增门禁）；`logo-final.svg`（#1890FF/#06B6D4 独立品牌资产，不随方案更换）。
- **固有特征提示**：新 `--ch-claudecode #d97706` 与既有 `--amber`/`--chart-cost` 同 hex —— 这是用户给定方案的固有重合（渠道色 vs 语义色不同用途 token），不构成冲突，不另行处理。
- **Review 修订记录**：第 1 轮 4 项（app.js 7 处非 6 处、旧 hex 注释致残留扫描矛盾、26 处非 21 处、预期失败信息格式），第 2 轮 1 项（`.ub.c-month` 琥珀渐变未豁免），第 3 轮 2 项（dark 渠道行实为 2 空格缩进、Task 2 Interfaces 与 Step 3 表述矛盾），均已修订。全量基线 653 条通过（Task 4 验收前提成立）。
