# 实施计划：用量统计页面与总览渠道颜色统一同步

- **日期**：2026-09-09
- **目标**：将「用量统计」页面的渠道展示颜色与「用量统计总览」页面的官方 CSS 变量（`var(--ch-*)`）完全对齐，支持亮/暗主题自适应。
- **关联缺陷**：`doc/bug-diagnosis-channel-color-mismatch-20260909.md`

---

## 1. 变更范围与改动点

### 1.1 核心文件
- `F:\GitHubs\opencode-go-gauge\app\web\app.js`

### 1.2 具体改动方案
将 `app.js` 第 293-294 行的静态硬编码 `SOURCE_COLOR` 改为直接引用 `style.css` 定义的 CSS 变量：

```javascript
// 修改前 (app.js:293-294)
const SOURCE_COLOR = { opencode: "#5b8def", bai: "#4fc3f7", commandcode: "#9a6ff0",
  zcode: "#34b37e", claudecode: "#e8a33d", codex: "#6b7488", dsh: "#8d6e63" };

// 修改后
const SOURCE_COLOR = {
  opencode: "var(--ch-opencode)",
  bai: "var(--ch-bai)",
  commandcode: "var(--ch-commandcode)",
  zcode: "var(--ch-zcode)",
  claudecode: "var(--ch-claudecode)",
  codex: "var(--ch-codex)",
  dsh: "var(--ch-dsh)"
};
```

---

## 2. 影响范围与组件核对

| 页面组件 | 对应代码位置 | 使用方式 | 兼容性评估 |
| :--- | :--- | :--- | :--- |
| **顶部数据源占比条** | `app.js:1058` | `style="flex:${pct};background:${SOURCE_COLOR[s.source_id] \|\| '#6b7488'}"` | 完全兼容 DOM inline style |
| **图例圆点** | `app.js:1063` | `style="background:${SOURCE_COLOR[s.source_id] \|\| '#6b7488'}"` | 完全兼容 DOM inline style |
| **各渠道卡片微型占比条**| `app.js:1086` | `style="width:${pct}%;background:${SOURCE_COLOR[s.source_id] \|\| '#6b7488'}"`| 完全兼容 DOM inline style |
| **展开明细柱状图** | `app.js:1151` | `style="width:${pct}%;background:${color}"` | 完全兼容 DOM inline style |

---

## 3. 验证步骤与测试用例

1. **语法检查**：
   执行 `node --check app/web/app.js` 确保无 JS 语法错误。
2. **自动化测试套件回归**：
   运行 `pytest tests/test_stats_sources.py` 与 `pytest tests/test_theme_rerender.py` 验证数据与渲染逻辑。
3. **视觉与一致性验证**：
   - 打开「用量统计」页面，验证 zcode 为蓝紫色、commandcode 为翡翠绿、bai 为金黄色、claudecode 为品牌橙、codex 为梅子紫。
   - 切换深色模式/浅色模式，确认颜色自动切换为深色模式微调高亮值（与总览完全一致）。
