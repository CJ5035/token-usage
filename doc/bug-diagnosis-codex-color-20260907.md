# Bug 诊断报告：Codex 渠道配色与 commandcode 撞色（观感差）

- **日期**：2026-09-07
- **状态**：已修复（品红方案，2026-09-07 实施并回归通过）
- **严重级别**：P3 轻微（纯视觉，无功能影响）
- **报告人**：Codex Agent（Bug Diagnosis Skill）

---

## 问题描述

用户反馈：统计图表中 Codex 渠道的配色"太丑"，希望更换。截图（暗色主题）显示 Codex
的图例圆点、堆叠柱、环形图扇区均为青绿色，与 commandcode 的绿色几乎无法区分。

## 环境信息

- 分支/版本：main（工作区，T5 已合入 Codex 渠道）
- 相关模块：`app/web/style.css`（定义）、`app/web/app.js`（消费）
- 复现步骤：打开首页或统计页（暗色主题），观察任意图表中 commandcode 与 Codex 的颜色

---

## 可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | Codex 渠道色与 commandcode 渠道色同属绿色系，色相相邻导致撞色 | 高（实锤） | 暗色主题两值 RGB 欧氏距离仅 **39**（#2dd4bf vs #34d399）；亮色主题距离 70（#0f766e vs #10b981）。同图渲染时用户无法区分，观感上"两坨绿"，即"丑"的来源 |
| 2 | 对比度不达标导致观感差 | 低（已排除） | WCAG 实测：亮 #0f766e 对白卡 5.47:1、暗 #2dd4bf 对暗卡 9.34:1，均 ≥4.5 达标。可读性没问题，问题是撞色 |

结论：**不是"选了个难看的颜色"，而是"选了个与现有调色板冲突的颜色"**。style.css:2436
处注释"扩齐六渠道, 防分段同色"的初衷，恰恰被 T5 新增的 Codex 青绿色破坏了。

## 现有调色板与空缺色相

| 渠道 | 亮色 | 暗色 | 色相 |
|------|------|------|------|
| opencode | #4f8ef7 | #6ba3ff | 蓝 ~215° |
| bai | #f59e0b | #f59e0b | 琥珀 ~38° |
| commandcode | #10b981 | #34d399 | 翡翠绿 ~160° |
| zcode | #6366f1 | #818cf8 | 靛蓝 ~239° |
| claudecode | #fb7185 | #fb7185 | 玫红 ~350° |
| dsh | #64748b | #94a3b8 | 石板灰 |
| **codex（现值）** | **#0f766e** | **#2dd4bf** | **青绿 ~175° ← 与翡翠绿相邻** |

空缺色相区：**紫红/品红区 ~250°–330°**（zcode 239° 与 claudecode 350° 之间）。

## 候选色评估（实测数据）

| 候选 | 亮色 card 对比度 | 暗色 card 对比度 | 与现有 6 渠道最小 RGB 距离 | 结论 |
|------|----------------|----------------|--------------------------|------|
| **方案A：品红 fuchsia（亮 #c026d3 / 暗 #e879f9）** | **4.71 ✓** | **7.06 ✓** | **≥105** | **推荐**：落在唯一空缺色相区，全渠道可区分，双主题 WCAG 达标 |
| 方案B：青 cyan（亮 #0891b2 / 暗 #22d3ee） | 3.68 ✗ | 9.62 ✓ | 87（对 commandcode） | 备选：仍偏绿色系，与 commandcode 区分度不足；亮色对比度不达标；且是 zcode 被替换前的旧色 |
| 否决：violet #8b5cf6 | 4.23 | 4.10 | 49（对 zcode） | 与靛蓝撞色 |
| 否决：orange #f97316 | 2.80 | 6.20 | 45（对 bai） | 与琥珀撞色 |
| 否决：teal-500 #14b8a6 | 2.49 | 6.98 | 44（对 commandcode） | 换汤不换药 |
| 否决：OpenAI 品牌绿 #10a37f | — | — | <50（对 commandcode） | 品牌归品牌，撞色更严重 |

## 验证动作

- **位置**：`app/web/style.css:37`（亮色 `--ch-codex: #0f766e`）、`app/web/style.css:68`（暗色 `--ch-codex: #2dd4bf`）
- **具体操作**：浏览器 DevTools 中将两值临时改为候选色，观察首页堆叠柱/环形图/24h 图、统计页明细表
- **预期结果**：换成方案A后，Codex 在所有图表中与 commandcode 一眼可分

## 调用链与依赖分析

```
app/web/style.css:37,68        --ch-codex 定义（亮/暗两个主题块）
  → app/web/app.js:2435  CH_COLOR.codex = "var(--ch-codex)"
    → app.js:2619  chColor() 解析 CSS 变量实际值（Chart.js 需要）
      → 堆叠柱状图 report-stack / 环形图 donut / 24h 图（图表分段色）
      → app.js:2541  配额条圆点+渠道名（内联 style）
      → app.js:2728  渠道明细表渠道名文字色（需 ≥4.5 对比度）
```

改动点收敛在 style.css 两行 CSS 变量，JS 零改动（主题切换 rerenderCharts 走 EVOLUTION-4
缓存重渲机制，自动生效）。

## 边缘情况检查

| 维度 | 场景 | 是否有问题 | 说明 |
|------|------|-----------|------|
| 双主题 | 亮色/暗色需分别取值 | 否 | 方案A两值均达标（4.71 / 7.06） |
| 文字色复用 | 渠道明细表用该色渲染文字（app.js:2728） | 否 | 亮 #c026d3 对白卡 4.71 ≥ 4.5 达标 |
| 近邻 UI 色 | --primary #9d7cf8（按钮/强调）、reasoning #a78bfa（token 构成图） | 否 | 与暗色 #e879f9 距离 75/67，且非渠道语义，图例中不会并列 |
| 图表分段相邻 | 堆叠图中 Codex 与相邻渠道分段 | 否 | 方案A与全渠道距离 ≥105（阈值 100） |

## 总结与建议

根因：Codex 渠道色（青绿）与 commandcode 渠道色（翡翠绿）色相相邻，暗色主题下 RGB
距离仅 39，同图不可分。**建议采用方案A：亮 `#c026d3` / 暗 `#e879f9`（品红系）**，仅需改
`app/web/style.css:37,68` 两行。等待用户确认后实施。

---

## 追记（2026-09-07 二次调优，用户确认方案A）

实际渲染观察（暗色主题大面积堆叠）：`#e879f9`（fuchsia-400）高明度+高饱和呈荧光感，与 zcode
靛蓝 #818cf8 上下相邻时粉紫扎堆。colorhunt 等深底配色流行低饱和"梅子/兰紫"调。实测候选后
按用户确认执行方案A：暗色 `#e879f9` → `#d946ef`（fuchsia-500，暗卡对比 5.03 ✓，与最近渠道
距离 105→113 更远），亮色 `#c026d3` 保持不动（白卡 4.71 ✓，白底仅小面积图例点）。
colorhunt 明星色否决证据：青碧 #08d9d6 距 commandcode 75、玫红 #ff2e63 距 claudecode 75、
纯紫 #9d4edd 距 zcode 73（阈值 100），品红区仍是唯一可行色相区。

## 追记二（2026-09-07 三次调优，用户 dislike 玫红感 → 正红方案）

用户反馈品红/梅子紫仍偏"玫红"，要求更红。红区硬约束：claudecode 占亮鲑粉 #fb7185，红区
亮档天然同族。实测：pink-500 #ec4899 距 claudecode 仅 48（两粉同框最弱）、rose-500 #f43f5e
64、red-500 #ef4444 80（明度差拉开，正红 vs 浅粉肉眼可辨）。最终方案：暗 #ef4444 (red-500,
暗卡 4.62 ✓) / 亮 #e11d48 (rose-600, 白卡 4.70 ✓ 距 107)。亮主题刻意避开 --down 语义红
#dc2626 同值冲突；暗主题与 --down #f87171 距离 76, 有 commandcode≈--up 距离 35 的既有先例
兜底（渠道色与语义色近亲在本仓库为已接受现实, 图例/表均有文字标签兜底）。

## 追记三（2026-09-08 终局：三渠道重排落地）

经三轮对比页评审（artifacts/codex-color-compare.html / codex-color-round2.html / bai-color-round3.html
/ dark-theme-full-audit.html），用户拍板终局方案并已实施：

| 渠道 | 亮色 | 暗色 | 说明 |
|------|------|------|------|
| claudecode | `#c2410c`（原 #fb7185） | `#d97757`（原 #fb7185） | Claude 品牌陶土橙；亮用 orange-700 保文字对比 5.18 |
| Codex | `#c026d3`（原 #e11d48） | `#d946ef`（原 #ef4444） | 梅子紫 fuchsia-600/500；claudecode 上橙后紫区唯一空缺 |
| bai | `#f59e0b`（不变） | `#facc15`（原 #f59e0b） | 金黄 yellow-400 仅暗档；品牌橙上位后暗主题距橙 90→113 |

其余渠道（opencode/commandcode/zcode/dsh）不动。

### 全量审计结论（是否需要暗色主题全部重排：不必要）

7×7 两两矩阵（artifacts/dark-theme-full-audit.html）：终局方案暗主题仅剩 3 对 <100——
opencode-zcode 33、zcode-dsh 71、opencode-dsh 82，全部为蓝/靛/灰既有格局且图例/明细表有文字
兜底。四种全量重排试排均无法更好：opencode 动则撞 commandcode 绿（39-98）；zcode 动则撞
reasoning 色 #a78bfa 同值或撞 Codex 紫 86，且 zcode 靛蓝为用户指定色、暗卡文字对比 5.58 达标。
成本收益不成立，留档为已知接受项。

### 同步变更

- tests/test_dark_theme.py：_ROOT_RECOLOR_ALLOWED 扩至 --ch-codex/--ch-claudecode/--ch-bai；
  dark changed 集合同步；锚定测试扩展为三渠道六断言
- tests/test_i18n_consistency.py：test_root_channel_colors_unchanged 基线锚 claudecode 亮值更新
- 回归：全量 548 passed / 0 failed / 3 skipped
