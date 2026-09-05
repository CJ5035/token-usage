# zcode 渠道配色更换

- 日期：2026-09-06
- 状态：**待确认**
- 范围：仅 `app/web/style.css` 两行 CSS 变量，不改 JS/Python

## 1. 问题

首页/总览中 zcode 渠道（GLM Coding Plan，本库中用量占比最大的渠道）当前为青色，
在大面积场景（渠道占比环图主扇区、分渠道消耗趋势堆叠柱主系列）下过于亮眼刺目，
与"晨雾紫"整体主题不协调。

当前色值（style.css:34 / :64）：
- 浅色 `--ch-zcode: #06b6d4`（cyan-500）
- 暗色 `--ch-zcode: #22d3ee`（cyan-400）

## 2. 配色约束

新色须与现有五渠道色区分明显（浅/暗两套）：

| 渠道 | 浅色 | 暗色 |
|---|---|---|
| opencode | #4f8ef7 蓝 | #6ba3ff 蓝 |
| bai | #f59e0b 琥珀 | #f59e0b 琥珀 |
| commandcode | #a78bfa 浅紫 | #b79bfd 浅紫 |
| claudecode | #fb7185 玫红 | #fb7185 玫红 |
| dsh | #64748b 石板灰 | #94a3b8 石板灰 |

排除项：蓝系（撞 opencode）、紫系（撞 commandcode 与主题色）、橙系（撞 bai）、
粉红系（撞 claudecode）、青色系（用户明确不喜欢）。

## 3. 候选方案

**方案 A 翡翠绿 emerald（推荐）**：浅 `#10b981`（emerald-500）/ 暗 `#34d399`
（emerald-400）。与五色区分度最高；绿色在大面积图表上柔和不刺眼；Tailwind 标准
色，与现有色板同源（项目大量使用 Tailwind 色值）。

**方案 B 青绿 teal**：浅 `#14b8a6` / 暗 `#2dd4bf`。比 cyan 更绿更沉稳，但仍是青绿
系，与原色差异较小，可能仍不合口味。

**方案 C 靛蓝 indigo**：浅 `#6366f1` / 暗 `#818cf8`。贴近 GLM/Z.ai 品牌蓝紫调，但
与 opencode 蓝、commandcode 紫的区分度下降，图表多系列并排时不易分辨。

## 4. 改动点（按方案 A）

`app/web/style.css`：

```diff
-  --ch-zcode: #06b6d4;
+  --ch-zcode: #10b981;
```
```diff
-  --ch-zcode: #22d3ee;
+  --ch-zcode: #34d399;
```

无 JS/Python 改动：app.js 的 `CH_COLOR`/`chColor()` 均经 `var(--ch-zcode)` 动态取
色，配额卡圆点/名称、渠道表文字、堆叠趋势图、占比环图自动生效。

注意：app.js `COLOR.cache`、`OV_COLORS` 中的 `#06b6d4` 是 Token 构成图"缓存命中"
用色，与渠道色无关，不动；style.css `.ub.c-bai::before` 渐变中的 `#06b6d4` 属于
bai 渠道 KPI 装饰条，不动。

## 5. 验证

1. `grep -n "ch-zcode" app/web/style.css` 确认两处新值落位
2. 刷新页面目视：占比环图/趋势图/配额卡中 zcode 显示为绿色，暗色主题同样清晰
3. 与 opencode 蓝、commandcode 紫、claudecode 玫红并列图例可分辨
