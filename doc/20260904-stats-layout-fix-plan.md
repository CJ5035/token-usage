# Stats 页排版错乱修复 实施计划

> **For agentic workers:** 按任务顺序执行；步骤使用 checkbox (`- [ ]`) 跟踪。本计划经用户确认后方可动代码；代码修改后**不自动签入**，由人工确认。

**Goal:** 修复 Stats 页「模型用量甜甜圈图 / 用量趋势图」溢出卡片、覆盖 ZCode 本地用量表格的排版错乱，改为内容自然排列、超高滚动的布局。

**Architecture:** 纯 CSS 修复，仅改 `app/web/style.css`。删除 `#page-stats` 的 flex 列容器与 `.two-col` 的 `flex:1; min-height:0` 填满式布局（压塌根因），图表高度回归 chart-box 的 min-height（180/200/220/240px）决定，与下方本地用量卡片解耦。另加一个防回归检查脚本固化"禁止 flex 压塌"约束。

**Tech Stack:** 原生 CSS / Python 3.12（检查脚本）/ pywebview 桌面应用（实机验证）

**Spec:** [doc/20260904-stats-layout-overlap-diagnosis.md](20260904-stats-layout-overlap-diagnosis.md)（诊断报告，含根因链与证据；修复方向 = 报告中"推荐"方案 1）

## Global Constraints

- 回复使用中文；仅做本计划列出的修改，不顺手"优化"无关代码（surgical changes）。
- 文档放 `doc/` 目录，命名 `yyyymmdd-xxxx.md`；本目录文档不签入版本控制（沿用项目约定）。
- Python 解释器：`D:\.pyenv\pyenv-win\versions\3.12.10\python.exe`（`python` 可用时直接用 `python`；禁止 `py` / 裸 `pip`）。
- 代码修改后必须编译/检查通过才算完成：本计划无 Python 业务代码改动，验收 = 检查脚本通过 + CSS 大括号配平 + 实机验证通过。
- 修改后不自动 `git commit`；签入动作由用户人工确认后执行。

## File Structure

| 文件 | 动作 | 职责 |
|------|------|------|
| `app/web/style.css` | 修改（2 处，均在统计页布局区块） | 删除 flex 填满式布局，two-col 回归自然高度 |
| `scripts/check_stats_layout.py` | 新建 | 防回归静态检查：禁止 `#page-stats` flex 容器 / two-col 压塌三件套，校验 CSS 配平 |

不改 `app/web/app.js`：图表创建逻辑（`responsive:false` + 一次性 `resize()`）在布局不再压塌后工作正常，无需补偿调用。

---

### Task 1: 取消 Stats 页填满式 flex 布局 + 防回归检查

**Files:**
- Modify: `app/web/style.css:248-250`（`#page-stats` flex 容器 + `.two-col` 覆盖规则）
- Modify: `app/web/style.css:434-435`（`.zcode-stats` 的 `flex-shrink:0` 与过时注释 — 随 flex 布局一并清除）
- Create: `scripts/check_stats_layout.py`

**Interfaces:**
- Consumes: 无（独立改动）
- Produces: 无代码接口；布局契约 = "`#page-stats` 非 flex 容器；`.two-col` 高度由内容决定；`#page-stats` 保留 `overflow-y:auto` 滚动"，由 `scripts/check_stats_layout.py` 强制

- [ ] **Step 1: 新建防回归检查脚本（先于修复运行，确认能检出当前问题）**

创建 `scripts/check_stats_layout.py`：

```python
"""Stats 页布局防回归检查.

背景 bug (doc/20260904-stats-layout-overlap-diagnosis.md):
#page-stats 固定高 flex 列 + .two-col 的 flex:1/min-height:0,
在新增 ZCode/DSH/Claude Code 本地用量高卡片后把 two-col 压塌至 0 高,
内部图表 (responsive:false) 溢出卡片覆盖下方表格.

检查项:
1. #page-stats 不得是 flex 容器 (内容超高时 flex 列压缩子项);
2. #page-stats .two-col 不得含 flex:1 / min-height:0 / margin-bottom:0;
3. #page-stats 必须保留 overflow-y:auto (超高滚动);
4. style.css 大括号配平.
"""
import re
import sys
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "app" / "web" / "style.css"


def rule_bodies(text: str, selector: str) -> list[str]:
    """取 selector 独立成规则时的声明体 (不匹配 '#page-stats .two-col' 这类后代选择器)."""
    pat = re.compile(re.escape(selector) + r"\s*\{([^}]*)\}")
    return pat.findall(text)


def main() -> int:
    text = CSS.read_text(encoding="utf-8")
    errs: list[str] = []

    for body in rule_bodies(text, "#page-stats"):
        if "display:flex" in body.replace(" ", ""):
            errs.append("#page-stats 不得为 flex 容器 (会压缩子项 two-col)")

    two_col = rule_bodies(text, "#page-stats .two-col")
    if not two_col:
        errs.append("缺少 #page-stats .two-col 规则")
    for body in two_col:
        norm = body.replace(" ", "")
        for bad in ("flex:1", "min-height:0", "margin-bottom:0"):
            if bad in norm:
                errs.append(f"#page-stats .two-col 不得含 {bad} (two-col 压塌来源)")

    scroll_ok = "#page-stats, #page-settings { overflow-y: auto" in text or any(
        "overflow-y:auto" in b.replace(" ", "") for b in rule_bodies(text, "#page-stats")
    )
    if not scroll_ok:
        errs.append("#page-stats 需保留 overflow-y:auto (内容超高时滚动)")

    if text.count("{") != text.count("}"):
        errs.append("style.css 大括号不配平")

    if errs:
        print("FAIL:")
        for e in errs:
            print(" -", e)
        return 1
    print("OK: stats 页布局检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: 运行脚本，确认检出当前问题（红）**

Run: `python scripts/check_stats_layout.py`
Expected: 退出码 1，输出包含 `#page-stats 不得为 flex 容器` 和 `.two-col 不得含 flex:1` 等 FAIL 项（证明检查有效，且当前代码确实带问题签名）

- [ ] **Step 3: 修改 style.css（2 处）**

修改 1 — `app/web/style.css:248-250`，old_string：

```css
/* 统计页: 底部两卡片弹性拉伸填满剩余空间, 消除底部空白 */
#page-stats { display: flex; flex-direction: column; }
#page-stats .two-col { margin-bottom: 0; flex: 1; min-height: 0; align-items: stretch; grid-template-columns: 1fr 1.6fr; }
```

new_string：

```css
/* 统计页: 内容自然排列, 超高由 overflow-y:auto 滚动;
   不用 flex:1 填满剩余空间 — ZCode/DSH/Claude Code 本地用量卡片会撑高页面,
   flex:1 + min-height:0 会把 two-col 压塌, 内部图表(responsive:false)溢出重叠到下方卡片 */
#page-stats .two-col { align-items: stretch; grid-template-columns: 1fr 1.6fr; }
```

修改 2 — `app/web/style.css:434-435`，old_string：

```css
/* 统计页本地用量区块 (page-stats 为 flex column, 防被 two-col 的 flex:1 压缩) */
.zcode-stats { margin-bottom: 12px; padding-bottom: 12px; flex-shrink: 0; }
```

new_string：

```css
/* 统计页本地用量区块 */
.zcode-stats { margin-bottom: 12px; padding-bottom: 12px; }
```

**明确不改**（保留现状，均不与新布局冲突）：
- `app/web/style.css:251-253`（卡片内 `display:flex column` + chart-box `flex:1`）：块级流下两卡片仍被 grid stretch 等高，图表区随卡片拉伸对齐，视觉受益且稳定；
- `app/web/style.css:103`（`#page-stats` 的 `overflow-y:auto`）：滚动能力是本修复的一部分；
- `app/web/app.js` 全部。

- [ ] **Step 4: 运行脚本，确认通过（绿）+ 脚本自身编译检查**

Run: `python scripts/check_stats_layout.py`
Expected: 退出码 0，输出 `OK: stats 页布局检查通过`

Run: `python -m compileall -q scripts/check_stats_layout.py && echo COMPILE_OK`
Expected: 输出 `COMPILE_OK`

- [ ] **Step 5: 实机验证（启动应用人工核对）**

Run: `python entry.py`，打开 Stats 页，逐项核对：

| # | 检查项 | 预期 |
|---|--------|------|
| 1 | 甜甜圈图、趋势图位置 | 均在各自卡片（模型用量/用量趋势）内部，不覆盖任何表格 |
| 2 | 页面滚动 | 可向下滚动，完整看到 ZCode/DSH/Claude Code 卡片及各自趋势图 |
| 3 | two-col 高度 | 模型用量/用量趋势卡片为正常高度（数百 px，非 0） |
| 4 | range 切换 today/7d/30d/all | 每次切换后图表重建，无重叠 |
| 5 | 窗口缩放 | 图表随 safeResize 适配，无重叠 |
| 6 | 暗色主题切换 | 图表重绘后布局仍正常 |

已知取舍（向用户说明，非缺陷）：本地无数据、3 个本地用量卡片全 hidden 且视口很高时，页面底部可能出现留白（原 `flex:1` 设计即为消除留白，但二者不可兼得，压塌重叠是更严重的问题）。

- [ ] **Step 6: 人工确认后签入（不自动执行）**

⚠️ **签入范围警示**：`app/web/style.css` 当前还携带其他未签入的功能改动（BAI 积分格、CommandCode 账期汇总、zcode-quota 额度卡等 CSS，属进行中的多数据源特性）。整文件 `git add` 会把这些一并卷入本 fix 提交，导致提交信息与 diff 不符。签入前须与用户确认范围，二选一：

- a) 与多数据源特性改动同批签入（提交信息改为特性+修复合并描述）；
- b) 仅选择性暂存本修复涉及的 2 个 hunk（`git add -p app/web/style.css`，交互式选块）。

待用户在实机验证通过后明确指示签入方式，再执行（以 b) 为例）：

```bash
git add scripts/check_stats_layout.py
git add -p app/web/style.css   # 仅选本修复的 2 个 hunk
git commit -m "fix: Stats页取消flex填满式布局, 修复图表溢出覆盖本地用量表格"
```

---

## Self-Review 记录

- **Spec 覆盖**：诊断报告"修复方向 1（推荐）"= 取消填满式 flex 布局 → Task 1 Step 3 两处修改即该方案全部内容；方向 2（unhide 后 safeResize）在布局不压塌后为冗余，按 YAGNI 不实施；方向 3（card overflow:hidden）报告已标记"不建议"。无遗漏。
- **Placeholder 扫描**：脚本完整可运行、CSS old/new 完整、验证项具体，无 TBD/待补。
- **一致性**：检查脚本的 3 条规则与 Step 3 修改后的终态一一对应（`#page-stats` 无 flex、`.two-col` 无压塌三件套、保留 overflow-y:auto）；Step 2（红）→ Step 4（绿）闭环。
