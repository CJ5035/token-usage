# 诊断报告 EVOLUTION-6：暗色主题系统性重构（底色换中性纯黑灰 + 遗漏修补）【v3】

- **日期**：2026-09-05
- **维度**：UI 一致性（暗色主题完整性与配色方案）
- **预估等级**：P2（损伤 5.5/10）
- **状态**：静态证据确认 + 截图 zoom 实证 + **用户已决策配色方向**
- **初扫勘误**：静态探针曾报"select 无暗色样式（截图 07 全部模型亮白底）"——经放大截图核实**不成立**（`.select` 使用 `var(--card)/var(--text)` token 且生效正常，低分辨率截图误判），已从问题清单撤销。

## 用户决策记录（2026-09-05）

用户提出"很多暗色主题都是黑色为主"，经三方案对比（微紫压饱和 / 中性纯黑灰 / 保持现底色），**用户选定「中性纯黑灰」**：GitHub/Material 风格，灰阶完全去紫，品牌紫（`--primary: #9d7cf8`）仅保留在主按钮/强调色/`--primary-soft`。

## 问题现象（暗色模式三类遗漏）

### ① `.badge.ok` 无暗色覆盖——亮薄荷绿底刺眼

`style.css:336`：

```css
.badge.ok { background: #e8f7ef; color: #16a34a; border-color: transparent; }
```

无对应 `html[data-theme="dark"] .badge.ok` 覆盖。**对照组证明这是遗漏而非设计**：同族 `.badge.no` 用 `var(--danger-soft)` 且暗色有覆盖（style.css:55）；`.src-badge`（style.css:340）、`.ub-hint`（style.css:456）也都有 dark 覆盖——唯独 `.badge.ok` 漏了。

使用点：`app.js:1778` 设置页账号列表 `<span class="badge ok ur-badge">当前</span>`——暗色下设置页出现一块亮薄荷绿实底徽标，与整体深色强烈冲突。

### ② `--text3` 暗色对比度不足（3.2:1 < 4.5:1）

`style.css:45`：暗色块内 `--text3: #6f6a87`，在 `--card: #1d1a26` 上对比度约 **3.2:1**，低于 WCAG AA 小字要求的 4.5:1。而它承载大量 11-12px 关键信息：`.wb-l`（KPI 标签）、`.kpi-l`、表格 `th`、`.sd`（数据目录）、`.tc-l`、`.hint`。

**截图实证**（`.probe/ui-shots/zoom-cardtitle-dark.png`，由 07-records-dark.png 放大）：记录页暗色下「会话用量」卡片标题与背景几乎融合，需仔细辨认才能读出；表头「Key 名称/会话」同样发灰。

### ③ 涨跌/警示色硬编码绕过 token

`style.css:478-479、496`：

```css
.wb-s .up { color: #16a34a; }  .wb-s .down { color: #dc2626; }
.sync-fail { color: #dc2626; }
```

绕过 `--green`/`--red` token：主题调色时失联；暗色深底上这两个值的对比度也未经验证。另 `.plan-badge.lite`（style.css:299）为死代码（PLAN_BADGE 未被引用）但同样硬编码。

## ④ 暗色底色方案整体调整（用户已决策：中性纯黑灰）

**现状问题**：当前暗色灰阶全部带紫调（hue≈254°/sat 14% 贯穿 bg/card/border/text2/text3/muted/hover/grid），画面发"雾"；叠加 --text3 对比度不足（②）放大灰蒙感。当前底色明度其实已深（#14121a，L≈9%），观感"不黑"主要来自紫调而非明度。

**目标 token 对照表**（用户已确认方向，具体值实施时以对比度实测校准）：

| Token | 现值（紫调） | 新值（中性黑灰） | 说明 |
|---|---|---|---|
| --bg | #14121a | **#111112** | 页面底，纯中性 |
| --card | #1d1a26 | **#1a1a1c** | 卡片 |
| --sidebar | #181520 | **#151516** | 侧栏 |
| --titlebar | #1d1a26 | **#1a1a1c** | 顶栏 |
| --border | #2e2a3d | **#2a2a2c** | 边框 |
| --text | #e9e6f5 | **#e8e8ea** | 主文字去紫 |
| --text1 | #e9e6f5 | **#e8e8ea** | 同上 |
| --text2 | #a8a3c0 | **#a3a3a8** | 次文字 |
| --text3 | #6f6a87 | **#8a8a90** | 兼顾②对比度 ≥4.5:1 |
| --muted | #232030 | **#202022** | |
| --hover | #272040 | **#262628** | |
| --grid | #29253a | **#242426** | 图表网格线 |
| --primary-soft | #272040 | **#2a2440** | **唯一保留紫底**（选中态/激活 pill） |
| --primary / --primary-strong | #9d7cf8 / #8b6cf6 | 保持不动 | 品牌紫仅留主色 |
| --danger-soft | #3d2429 | 保持（已中性偏红） | |
| **--up（新增）** | （无） | :root `#16a34a` / dark 实测校准 | 涨跌/成功绿；dark 按最浅承载面校准（见修复方向4） |
| **--down（新增）** | （无） | :root `#dc2626` / dark 实测校准 | 跌/失败红；同上 |
| 渠道色 --ch-*（6 项） | 亮彩 | **保持不动** | 渠道彩点是信息色，不受灰阶去紫影响 |

**联动校验点（实施时必须逐项核对）**：
1. 图表轴/网格/图例色经 `cssVar()` 取 token，token 改后自动跟随——但需 EVOLUTION-4 的重渲修复配合（不重渲则残留旧色）；
2. 所有 soft 底色（est-badge/`.zcode-badge`/徽标类）在新底色上目视校验协调性；
3. 阴影 `--shadow` 保持黑系不变；
4. `badge.ok` 新增暗色覆盖（①）按新底色调值；
5. 硬编码涨跌色 token 化（③）后，`--up`/`--down` dark 值在新底上对比度实测校准（≥4.5:1，实测记入修订备查）；
6. 亮色主题 token 完全不动。

## 用户体验影响

- 暗色用户每日全部页面都会遇到：设置页刺眼徽标（①）、各页小字难读（②，暗色可读性核心短板）、同步失败/涨跌信息在深底上偏暗（③）；
- 修复收益：三类同根（暗色覆盖/对比度/硬编码），一次一揽子修复，改动全部集中在 style.css 数行。

## 修复方向（供阶段3 细化，v2 修订）

1. 暗色块整体按④对照表换中性纯黑灰 token（一次性替换 `html[data-theme="dark"]` 块；约 20+ 处修改，集中在单文件单 CSS 块）；
2. `.badge.ok` 补暗色覆盖：dark 块内单独覆盖 background/color（按新底色调值，天然零亮色风险；不采用"对齐 .badge.no 改 var(--danger-soft) 写法"以免牵动亮色）；**dark 文字色与 `--up` 的 dark 值同源定义**（避免暗色绿色双源各调各的，后续微调只动 token 一处）；dark soft 底的对比度基准按软徽标族口径"不低于同族 .badge.no 现状（var(--red) on var(--danger-soft) 约 3.8:1）"，不单独强求 4.5:1（避免 10px 软徽标过度设计）；
3. `--text3` 按④表提亮至 #8a8a90（实测对比 ≥4.5:1：card 上约 5.1:1）；
4. **涨跌/警示色 token 化（v2 重写、v3 补基准面，保证亮色零变化）**：**新增 `--up`/`--down` 语义 token**（④表"新增"两行）——`:root` 值 = 现硬编码 `#16a34a`/`#dc2626`（亮色逐像素不变），**dark 值按最浅承载面校准 ≥4.5:1**：`.wb-s` 渲染于 wb-cell（`var(--card)` #1a1a1c），`.sync-fail` 渲染于 qb-card（`var(--muted)` #202022，更浅）——**取较不利者按 --muted 校准**（card 更暗必然达标）；现值 #dc2626 在新 card 上按 WCAG 复算约 3.6:1、muted 上更低，必须校准而非照搬；dark 实测值记入修订备查（预估值均以实施实测为准）；`.wb-s .up`→`var(--up)`、`.wb-s .down`→`var(--down)`、`.sync-fail`→`var(--down)`（**CSS 注释写明 sync-fail 与涨跌红共用 token**，防后续单独改色回归）；**同块遗漏一并纳入**：`.wb-s.spike`（style.css:479 `#d97706`）→`var(--amber)`（同值零视觉变化；dark 未覆盖 --amber，card 基准约 5.5:1 达标）；`.kpi.c-slate`（style.css:238 两处 `#64748b`）→ **直接改 `var(--ch-dsh)`**（:root --ch-dsh 恰为 #64748b，亮色逐像素不变、dark 自动同步 #94a3b8，无需 dark 覆盖写法）；**顺手删除死代码**：`.plan-badge.lite`（style.css:299）与 `PLAN_BADGE`（app.js:254，全文件零引用，约 2 行，零风险）；**禁止直接改用 `var(--green)`/`var(--red)`**（:root 值 #22c55e/#ef4444 会使亮色回归且对比度下降——v1 方案已否决）；
5. `--grad-brand` 显式决策：**保留**（紫蓝渐变视为主强调色延伸，仅用于顶部加载条/进度条填充等强调场景，符合"品牌紫留强调色"的用户决策；dark 不单独定义）；暗色走查确认其观感；
6. **实施顺序硬约束**：问题4（EVOLUTION-4 图表重渲）先落地或与本问题同版本交付，验收先验证重渲生效——否则"图表跟随新 token"走查会因残留旧色被误判失败；
7. **用户预览确认环节**：实施后输出六页暗色截图请用户确认观感后关闭（token 表注明"具体值以对比度实测校准"，最终观感需用户拍板，避免 objectively 达标、subjectively 不满意的二次返工）。

## 验证点

- 暗色全页面走查（首页 all/单渠道、统计、记录、总览、设置、关于）：灰阶无紫调残留、层次清晰；
- 暗色设置页「当前」徽标为软色底、无刺眼感；
- 记录页「会话用量」标题、表头、KPI 标签在暗色下可读（对比度实测 ≥4.5:1）；
- **dark 渲染路径无裸 hex 文本色（收窄后的验证口径）**：豁免清单 = .ub 饰条与进度条渐变（style.css:205-218）、渠道色 `--ch-*`、app.js 数据系列色（COLOR/palette/OV_COLORS）、`--grad-brand`、**带 dark 覆盖的成对 soft 徽标的亮色规则及其 dark 覆盖（.badge.ok/.src-badge/.ub-hint，亮色刻意保留、dark 覆盖含实施后 badge.ok 新增的 dark 底色）**；
- **亮色主题与改前逐像素一致**（新增 --up/--down 的 :root 值=现硬编码保证；badge.ok/spike 零亮色影响、c-slate 改 var 后 :root 同值）；
- **选中态目视项**：pill/seg 选中块（style.css:89、272）在新 muted/card 组合下的辨识度（紫调投影暗色下不可见，靠明度差+primary 文字色）；**目视不足时优先补中性阴影（如 rgba(0,0,0,.4)）或微调 muted，不因选中态回退灰阶去紫方向**；
- `--primary-soft #2a2440` 与 `--primary #9d7cf8` 组合实测校准（计算约 4.68:1；est-badge 10px 与 .zcode-badge 10.5px 两处小字徽标均处于 AA 边缘，一并目视）；
- `.src-badge`（style.css:340）/`.ub-hint`（style.css:456）现有暗色硬编码蓝青在新中性底上的协调性目视校验；
- 滚动条 thumb（var(--border)/var(--text3) 驱动）新明度差下静置可见性走查；
- 图表在暗色下轴/网格/图例色跟随新 token（**以 EVOLUTION-4 重渲先落地/同版本为前提**）。
