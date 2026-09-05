# 实施计划 EVOLUTION-6：暗色主题系统性重构（中性纯黑灰 + 遗漏修补）【v4】

- **日期**：2026-09-05（v3：第 2 轮驳回项补齐；v4：第 3 轮 3/3 通过后一行级精确化）
- **依据**：`doc/evolution-diagnosis-6.md` v3.1（门禁1 三轮 3/3 通过；配色方向经用户三方案对比拍板"中性纯黑灰"）
- **等级**：P2（5.5/10）
- **改动范围**：`app/web/style.css`（主体，约 20+ 处，单文件单 CSS 块级替换）、`app/web/app.js`（死代码 2 行）
- **实施顺序硬约束**：**EVOLUTION-4 先落地或与本问题同版本交付**，验收先验证重渲生效——否则"图表跟随新 token"走查会因残留旧色被误判失败

## 改动清单

### 1. 暗色 token 块全量替换（style.css:38-62，`html[data-theme="dark"]`）

按诊断④表执行（13 项换值）：`--bg:#111112`、`--card:#1a1a1c`、`--sidebar:#151516`、`--titlebar:#1a1a1c`、`--border:#2a2a2c`、`--text/--text1:#e8e8ea`、`--text2:#a3a3a8`、`--text3:#8a8a90`（实测 card 上约 5.1:1）、`--muted:#202022`、`--hover:#262628`、`--grid:#242426`、`--primary-soft:#2a2440`（唯一保留紫底）。保持不动：`--primary/--primary-strong`、`--danger-soft`、`--shadow`、渠道色 `--ch-*` 6 项。**亮色 :root 块一行不动**。

### 2. 新增 `--up`/`--down` 语义 token（④表"新增"两行）

```css
:root { --up: #16a34a; --down: #dc2626; }        /* = 现硬编码, 亮色逐像素不变 */
html[data-theme="dark"] {
  --up: <实测校准>;   /* 按最浅承载面 --muted(#202022) 校准 >=4.5:1（--down 现值在 card 上仅约 3.6:1，必须校准） */
  --down: <实测校准>; /* dark 实测值记入修订备查 */
}
```

消费点替换：`.wb-s .up`→`var(--up)`（style.css:478）、`.wb-s .down`→`var(--down)`、`.sync-fail`→`var(--down)`（style.css:496，**CSS 注释写明与涨跌红共用 token**）；`.wb-s.spike`→`var(--amber)`（style.css:479，同值零视觉变化，dark 实测约 5.5:1）；`.kpi.c-slate`（style.css:238 两处 `#64748b`）→`var(--ch-dsh)`（:root 同值亮色不变，dark 自动同步 #94a3b8）。**禁止改用 `var(--green)`/`var(--red)`**（亮色回归，v1 已否决）。

### 3. `.badge.ok` 暗色覆盖（style.css:336 旁新增）

```css
html[data-theme="dark"] .badge.ok { background: <实测软底>; color: var(--up); }
```

文字色与 `--up` dark 值同源；soft 底对比度按软徽标族口径"不低于同族 .badge.no 现状（约 3.8:1）"，不单独强求 4.5:1。亮色规则不动。

### 4. 死代码删除（app.js + style.css 各约 2 行）

`.plan-badge.lite`（style.css:299，1 行）与 `PLAN_BADGE`（app.js:254，全文件零引用，1 行）。

## 不做

- 亮色 :root 块既有声明任何改动（**除新增 --up/--down 两条新声明外**）；`--grad-brand` dark 单独定义（显式决策保留，属强调场景）；独立 SWR/动画类改动（transition 现状保持）；为选中态回退灰阶去紫方向。

## 回滚方案

style.css 块级还原（SDD 快照 diff）；新增 token 与规则独立成段，还原零残留。app.js 仅删除 2 行死代码，还原零风险。

## 测试验证点

1. **静态断言测试**（pytest 源码断言模式，参照 test_network_deblocking）：style.css dark 块含新 token 值（**分层断言：13 项底色类按④表固定 hex；--text3 固定 #8a8a90、若实测校准偏离则断言值随实测修订；--up/--down 仅断言存在于 :root 与 dark 块**）、无 `#6f6a87` 残留；`.wb-s .up`/`.sync-fail`/`.wb-s.spike` 引用 var()；`PLAN_BADGE` 不再存在于 app.js；**`:root` 不可变锚：改前 style.css 的 :root 全部变量值逐项断言不变（尤其 --ch-dsh #64748b），把"亮色逐像素一致"从人工走查升级为程序化保证；sk-line/sk-bar/sk-chart/sk-box 的 background 均引用 var(--muted)**；
2. **对比度程序化校验**（测试内计算 WCAG 比值）：--text3/--up/--down dark 值对 --card/--muted ≥4.5:1（--up/--down 按实测填入后断言）；**badge.ok dark 软底上 var(--up) ≥3.8:1（软徽标族口径，一行断言消除人眼把控缺口）**；
3. **人工走查 + 用户预览确认环节**（硬要求）：实施后输出 **7 张暗色截图（首页 2 张：all + 单渠道；统计、记录、总览、设置、关于各 1 张；落点 `.probe/ui-shots/`，对话内展示）**，外加 1-2 张瞬态组件（**用户菜单展开/确认弹框可稳定展开→截图；toast 瞬态不可截图→口头确认**；面板本体 token 驱动自动跟随、风险低；**注记：toast.ok/.err 左边条用 var(--green)/var(--red) 且 dark 块未定义此二项、继承亮色值，属既有现状非本次引入**）；**总览页截图前置：先在设置开启总览面板开关**（#side-overview 默认 hidden，app.js applyOverviewPanel 控制），防 7 张凑不齐被误判遗漏，请用户确认观感后关闭——**不通过时处置路径：仅做 token 层色值微调后再确认一轮**（块级还原零残留，微调成本低）；
4. 走查明细：
   - 灰阶无紫调残留、bg/sidebar/card 三层层次清晰（bg<sidebar<card<muted<hover<border 明度递进）；
   - **骨架屏加载态目视**（sk-line/sk-bar/sk-chart/sk-box，style.css:165-172 全部随新 --muted #202022；dark shimmer 高光 rgba(255,255,255,.07) 为独立覆盖 style.css:163 不受影响，预期零回归）——记录页/统计页刷新瞬间骨架块与 card 底层次可辨（7 张静态截图拍不到加载瞬间，此项防高频可见面零确认）；
   - 设置页「当前」徽标软底无刺眼感；「会话用量」标题/表头/KPI 标签可读；
   - 亮色主题与改前逐像素一致（回归保证：--up/--down :root=现硬编码、badge.ok/spike/c-slate 零亮色影响）；
   - 选中态（pill/seg，style.css:89/272）辨识度目视（现状紫调阴影 rgba(30,20,60,.12) 暗色下不可见）；不足时优先补中性阴影（**兜底参考值 rgba(0,0,0,.4)**，与 dark --shadow 同族），**慎用微调 muted**（muted 是 sk-*/qb-card/tc 等高频承载面共同底色，动它会牵连已定稿的骨架屏走查结论），**不回退去紫**；
   - `--primary-soft+#9d7cf8` 组合（est-badge 10px / .zcode-badge 10.5px / **.plan-badge 基类 10.5px**——style.css:298，总览页"活跃"徽标 app.js:1580 在用，三处同组合一并目视）目视；
   - `.src-badge/.ub-hint` 暗色硬编码蓝青在新底上协调性；`.ub` 装饰渐变条（style.css:205-215，不在改动面、暗色当前已同值渲染非回归）随首页截图顺带目视；
   - 滚动条 thumb 静置可见性；`--grad-brand` 观感确认；
   - 涨跌/失败色在暗色下的辨识度（--down 校准后）；
   - **亮色回切目视**：暗色确认后切回亮色主题刷新首页目视对照一次（用户预览环节操作指引，把"亮色零回归"从代码层推定延伸到人眼确认）；
   - 图表轴/网格/图例跟随新 token（以 EVOLUTION-4 重渲已落地为前提）。
