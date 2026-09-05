# 实施计划：单渠道配额区铺满整行（每账号独占一行）

- **日期**：2026-09-06
- **状态**：待确认
- **关联诊断**：[bug-diagnosis-quota-panel-not-full-width-20260906.md](bug-diagnosis-quota-panel-not-full-width-20260906.md)
- **确认方案**：每账号独占一行（账号分组通栏，内部三张额度卡保持横排）

---

## 改动内容

仅 1 处，1 行 CSS：

**文件**：`app/web/style.css:509`

```css
/* 改前 */
.acct-quota { margin-bottom: 10px; }

/* 改后 */
.acct-quota { grid-column: 1 / -1; }
```

> margin-bottom 一并移除：改为纵向独占一行后，账号分组间距由 `.usage-blocks`
> 的行 gap 12px（style.css:207）提供；保留 margin-bottom 会叠加成 22px，
> 与页面其他区块统一的 12px 间距不一致。

## 改动说明

- `.acct-quota` 声明跨满 `#usage-blocks` 的全部 3 列（`grid-column: 1 / -1`），
  单账号时配额区（账号名 + 滚动/每周/每月三张卡）通栏铺满整行；
  多账号时每个账号独占一行，纵向排列。
- 内部 `.acct-quota-body` 的 3 列横排（style.css:517）不动，卡片布局不变。
- `#usage-blocks` 的 `repeat(3, 1fr)`（style.css:207）不动——"全部渠道" tab
  直接放 3 张额度卡仍依赖它。
- `.acct-name` 在 `#cc-grid` 中的跨列规则（style.css:521）不受影响。

## 验证步骤

1. **回归测试**：`python -m pytest tests/ -x -q` —— 全量通过
   （已确认 tests/ 与 app 后端均无 `acct-quota`/`usage-blocks` 引用，预期无回归；
   CSS 为静态资源，无需编译）
2. **手工 UI 验证**（用户执行或启动应用后确认）：
   - 首页 → 单渠道 `commandcode`（1 个账号）：配额区铺满整行，右侧无空白
   - 有多账号的渠道（如有）：每个账号独占一行，内部三卡横排正常
   - "全部渠道" tab：顶部三张额度卡布局不变

## 影响范围

| 场景 | 改动前 | 改动后 |
|------|--------|--------|
| 单渠道 1 个账号 | 占左侧 1/3，右侧空白 | 通栏铺满 ✅ |
| 单渠道 2 个账号 | 并排各占 1/3，留白 1/3 | 每账号独占一行 |
| 单渠道 ≥3 个账号 | 每行 3 个并排 | 每账号独占一行 |
| "全部渠道" tab | 3 张卡各 1/3 铺满 | 不变 |
| zcode/claudecode/dsh 无账号 | 整块隐藏 | 不变 |

## 不做的事

- 不改 `renderQuotaSingle`（app.js）——DOM 结构无需变动
- 不引入响应式断点 / auto-fit 方案——已确认采用"每账号独占一行"
