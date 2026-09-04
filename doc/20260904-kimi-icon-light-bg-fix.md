# Kimi 模型图标白底看不清修复

- 日期：2026-09-04
- 状态：**已确认（用户选定方案二）**：浅色主题用深色 K，深色主题保持白 K
- 范围：`app/web/icons/kimi-color.svg`（新增）+ `app/web/app.js` `modelIcon()`，不改 Python

## 0. Dedupe Ticket

- Intent signature: 新增 Kimi 图标浅色主题变体 kimi-color.svg（深色 K 字），白底下可见
- Queries: `ls app/web/icons/`；`grep -n "kimi" app/web/app.js`；codegraph explore "modelIcon kimi svg"
- Top matches: `app/web/icons/kimi.svg`、`app/web/icons/gpt-color.svg`、`grok-color.svg`、`mimo-color.svg`、`app/web/app.js:1249 modelIcon()`
- Decision: **new**（kimi-color.svg 无现成文件；机制复用现有 `-color` 主题切换，无新抽象）

## 1. 问题

浅色主题（白背景）下，kimi-k3 前的 Kimi 图标几乎看不见。

根因：`kimi.svg` 主 "K" 图形为 `fill="#fff"`（白色，适配深色背景），仅左上角小块为
品牌蓝 `#1783FF`。图标以 `<img>` 引用、无法继承文字颜色，白底上白色 K 隐形。

## 2. 方案（用户已选定）

**新增 `kimi-color.svg`（K 字用 `#221f33`，与浅色主题正文色 `--text` 一致），接入
现有 `-color` 主题切换机制，方向与 gpt/grok/mimo 相反：**

- `kimi.svg`（原版，白 K）：深色主题使用，不动。
- `kimi-color.svg`（深色 K）：浅色主题使用，新增。
- 切换在 `modelIcon()`（app/web/app.js:1257）实现，gpt/grok/mimo 仍为"深色切
  color"，kimi 为"浅色切 color"。

对比过的落选方案：
1. K 字改品牌蓝（单文件，但深色模式白 K 变蓝 K，用户不选）；
2. CSS filter（`<img>` 引入的 SVG 无法单路径改色，会连带蓝色角）；
3. `currentColor`（`<img>` 上下文解析为黑色，深色主题不可见）。

## 3. 改动点

1. 新增 `app/web/icons/kimi-color.svg`：与 `kimi.svg` 相同，仅主 K 字 path 的
   `fill="#fff"` → `fill="#221f33"`。
2. `app/web/app.js:1257`：

```diff
-  const themed = dark && ["gpt", "grok", "mimo"].includes(name) ? `${name}-color` : name;
+  // kimi 白 K 仅适配深色背景, 浅色主题切 color 变体; gpt/grok/mimo 相反, 深色主题切 color 变体
+  const themed = dark
+    ? (["gpt", "grok", "mimo"].includes(name) ? `${name}-color` : name)
+    : (name === "kimi" ? "kimi-color" : name);
```

## 4. 影响与刷新时机

- `modelIcon()` 5 处调用（统计页模型榜/使用记录/会话表等）自动生效，`kimi-k3` 首段
  基名即 `kimi`，无需改映射表。
- 主题切换：`applyDarkMode()` → `refreshIcons()`（app.js:427）重建统计页图标，其余
  页面图标随下次数据刷新更新 —— 与 gpt/grok/mimo 现有行为一致，不在本次范围。

## 5. 验证

1. `node --check app/web/app.js`（JS 语法）
2. Python 解析校验 kimi-color.svg 为合法 XML、fill 值正确
3. `git status` 确认仅上述两文件变动；无 Python 改动，不跑 pytest
