# Bug 诊断报告：单渠道配额卡片未铺满页面宽度（仅占左侧约 1/3）

- **日期**：2026-09-06
- **状态**：已确认（根因定位，未修改代码）
- **严重级别**：P3 轻微（UI 布局问题，无功能影响）
- **报告人**：ZCode Agent（Bug Diagnosis Skill）

---

## 问题描述

首页（用量统计总览）选中单渠道 tab（如 `commandcode`）时，顶部配额区域
（账号 UUID 标题 + 滚动/每周/每月三张额度卡片）只占据页面左侧约 1/3 宽度，
右侧大片空白；而下方的"账期汇总"、"用量概览"卡片均为通栏全宽，对比明显。

用户疑问：这个渠道用量是否没有铺满整个页面？——**确认没有铺满**，仅占约 1/3。

## 环境信息

- 项目：GoGauge（opencode-go-gauge）
- 相关模块：首页单渠道配额渲染（前端）
- 复现步骤：首页 → 渠道 pill 选择 `commandcode`（仅 1 个账号）→ 观察顶部配额区宽度
- 复现条件关键点：**该渠道下已登录账号数为 1**（截图 `f8d265c9-…` 单账号）

---

## 第一步：可能原因分析

| # | 原因 | 概率 | 理由 |
|---|------|------|------|
| 1 | `.usage-blocks` 容器的 3 列 grid 把每个账号分组 `.acct-quota` 当作一个单元格，单账号时只占 1/3 列宽 | **高** | DOM 结构与 CSS 完全吻合：`#usage-blocks` 定义 `repeat(3, 1fr)`（style.css:207），`renderQuotaSingle` 只塞入 1 个 `.acct-quota` 子项（app.js:701），grid 子项默认占 1 列 → 1/3 宽，与截图比例一致 |
| 2 | `.acct-quota-body` 内部 3 列嵌套导致宽度塌缩 | 低 | 内部 grid `repeat(3, 1fr)`（style.css:517）是相对父容器宽度的，父容器 1/3 宽才是因；三张卡在截图内确实横排，说明内部布局本身正常 |
| 3 | 主题（暗色）或窗口缩放引起的响应式断点 | 低 | `.usage-blocks` 无媒体查询断点，任何宽度下都是固定 3 列；亮色主题同样会复现 |

## 第二步：验证动作

### 针对原因 1：grid 列宽限制（根因）

- **验证方式**：CSS 临时修改（或 DevTools 检查）
- **位置**：`app/web/style.css:509`（`.acct-quota` 规则处）
- **具体操作**：临时加一行
  ```css
  .acct-quota { grid-column: 1 / -1; }
  ```
- **预期结果**：配额区（UUID + 三张卡）立即通栏铺满整行 → 原因 1 成立；
  若仍不满宽，则需检查 `.page` 容器或外层布局（备查 `style.css` 中 `.page` 的 padding/max-width）。

### 佐证验证：多账号对照

- **操作**：给 commandcode 再登录 1 个账号，切回该渠道 tab。
- **预期结果**：出现两个 `.acct-quota`，各占 1/3 并排（合计 2/3，右侧仍留白）→
  直接证明"每个账号分组被当作 1 个 grid 单元格"。

## 第三步：调用链与依赖分析

### 完整调用路径

```
用户点击渠道 pill "commandcode"            [index.html:65 #channel-tabs]
  → switchChannel("commandcode")           [app/web/app.js:2139]
    → 渠道概览数据到达后渲染分发             [app/web/app.js:551-552]
      → chAccounts = accounts.filter(source === state.channel)
      → renderQuotaSingle(chAccounts)       [app/web/app.js:693]
        → box = $("usage-blocks")           [app/web/app.js:694]
        → box.innerHTML = 每账号一个 .acct-quota 分组块   [app/web/app.js:701-702]
        → renderUsageBlocks(a.quota, $("#aq-<id>"))       [app/web/app.js:703 → 621]
                                            ← 卡片渲染正常，问题不在此
CSS 层（问题所在）:
  .usage-blocks { display:grid; grid-template-columns: repeat(3, 1fr); }   [app/web/style.css:207]
  .acct-quota  { margin-bottom: 10px; }   ← 未声明跨列，默认只占 1 列    [app/web/style.css:509]
  .acct-quota-body { display:grid; grid-template-columns: repeat(3, 1fr); } [app/web/style.css:517]
```

### 关键依赖节点

- **上游调用者**：`loadChannelOverview` 渲染分发（app.js:552），仅单渠道 tab 走 `renderQuotaSingle`；
  "全部渠道" tab 走 `renderAll → renderUsageBlocks(data.quota)`（app.js:1437），直接把 3 张 `.ub`
  卡放进 `#usage-blocks`，3 列 grid 恰好每卡 1/3 **全宽**，因此全部渠道 tab 无此问题。
- **历史脉络**：style.css:515-517 注释记录了上一轮修复（内部卡片竖排→横排），
  当时只解决了 `.acct-quota-body` 内部的横排，**未处理外层 `.acct-quota` 只占 1 列的问题**。

### 影响范围评估

若修改 `.acct-quota`（如加 `grid-column: 1 / -1`）：
- 仅影响首页单渠道 tab 的逐账号配额区（`renderQuotaSingle` 一处调用）；
- 多账号（≥2）时从"每行 3 个账号并排"变为"每账号独占一行"，需确认期望交互；
- `.acct-name` 在 `#cc-grid` 中另有跨列规则（style.css:521），不受影响。

## 第四步：边缘情况检查

| 维度 | 场景 | 当前行为 | 是否有问题 | 建议 |
|------|------|----------|------------|------|
| 数据边界 | 单渠道仅 1 个账号 | 配额区只占 1/3 宽，右侧空白 | **是（本次问题）** | `.acct-quota` 跨满整行 |
| 数据边界 | 单渠道 2 个账号 | 各占 1/3，合计 2/3，留白 1/3 | 是（同根因） | 同上 |
| 数据边界 | 单渠道 ≥3 个账号 | 每行恰好 3 个铺满，问题被掩盖 | 否（表象） | 修复后变为纵向逐行，需确认期望 |
| 空值处理 | 本地渠道（zcode/claudecode/dsh）无账号 | `box.hidden = true` 整块隐藏 | 否 | 无需处理（app.js:695-698） |
| 渠道差异 | "全部渠道" tab | 直接放 3 张 `.ub` 卡，正常铺满 | 否 | 不受修复影响 |
| 配额失败 | quota.success = false | `.ub-error` 通栏提示 | 否 | 无需处理 |

## 总结与建议

**结论**：是的，该渠道用量区域确实没有铺满。根因是 `app/web/style.css:207` 给
`#usage-blocks` 写死了 `grid-template-columns: repeat(3, 1fr)`——这个 3 列布局是为
"全部渠道"tab 直接放 3 张卡设计的；单渠道 tab（`renderQuotaSingle`）往里放的是
以账号为单位的 `.acct-quota` 分组块，每个分组被当成 1 个 grid 单元格，于是
单账号时整个配额区（UUID + 三张额度卡）被压缩在左侧 1/3 宽度内。

**建议修复**（最小改动，一行 CSS）：在 `app/web/style.css:509` 的 `.acct-quota` 规则中加
`grid-column: 1 / -1;`，让每个账号分组通栏，内部 `.acct-quota-body` 的 3 列保持不变，
配额区即铺满整行。副作用：多账号时改为"每账号独占一行"（原来是 3 个并排一行），
若想保留多账号并排，可改为给 `#usage-blocks` 用 `repeat(auto-fit, minmax(480px, 1fr))`
一类的自适应列宽方案。按项目规则，待确认方案后再实施修改。
