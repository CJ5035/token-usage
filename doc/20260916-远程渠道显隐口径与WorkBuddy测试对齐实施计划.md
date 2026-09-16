# 远程渠道显隐口径与 WorkBuddy 测试对齐实施计划

- 日期：2026-09-16
- 背景：`main` 合并远程 `9c22773`（界面优化五项，含 D1 渠道显隐口径）与本地 WorkBuddy 系列（`41e62d1..90078ff` 共 8 个提交）
- 状态：自动合并无文本冲突，但全量测试 840 通过 / **2 失败**（均为 WorkBuddy），需要修复

## 一、冲突分析

远程 `9c22773` 的 D1 口径（20260915）：`list_channel_summary` 的 SQL 增加
`WHERE TRIM(token) != ''` —— **token 为空 = 退出登录 = 不显示渠道页签、不计入账号数**，
并同步更新了其已知 3 处测试（test_report_api / test_empty_state / test_db_lock）。

WorkBuddy 系列的两个测试写于该口径之前，依赖旧行为「空 token 的 opencode 种子行也计数」：

1. `tests/test_workbuddy_db.py::test_workbuddy_channel_order_and_summary`
   - 夹具只建 WorkBuddy 账号；opencode 种子行（token 空）被新口径过滤
   - `channels[0]` 期望 `opencode`，实际 `zcode`（zcode/claudecode 为恒显占位）
2. `tests/test_workbuddy_sync.py::test_workbuddy_counts_in_report_scope`
   - `account_count = sum(accounts for opencode/bai/commandcode/workbuddy)`（server.py:1641）
   - opencode 被过滤后只剩 WorkBuddy 的 1，期望 2

产品代码本身无 bug：WorkBuddy 账号 token 非空（session），正常计数与显示；
纯测试夹具与新口径不匹配。

## 二、修复方案

两个测试各加一行「已登录 opencode 账号」种子（`db.add_account("opencode-token", "oc")`，
source 默认 opencode），断言不变 —— 既保留原测试意图（WorkBuddy 与 opencode 并存计数/排序），
又对齐 D1 口径（只有已登录账号才显示）。**不改任何产品代码。**

## 三、验证标准

1. `python -m pytest tests/ -q` 全量通过（≥842 通过、0 失败）
2. `node --check app/web/app.js` 语法通过
3. 修复以独立提交落在合并提交之后（不重写合并提交）

## 四、风险

低。仅测试夹具加种子行，不影响产品逻辑；远程 D1 行为与其 9 个新测试全部保留。
