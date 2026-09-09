# Codex 交付一终审修复实施文档

日期：2026-09-08
来源：Subagent-Driven Development 执行交付一计划（`docs/superpowers/plans/2026-09-06-codex-usage-integration-delivery-1.md`）的最终全分支评审
评审范围：`83b2369..2cb1c37`（交付一全部 8 个提交）；隔离验证 worktree @2cb1c37 全绿（专项 101 passed / 全量 540 passed / node --check OK）
状态：**待用户确认后实施**

## 一、背景与结论

交付一 T1–T5、T7、T8 已全部实施并签入（提交 8be99a6 → 2cb1c37，与本计划各任务提交建议逐字对应）。本次 SDD 运行补做的最终全分支评审结论：**无 Critical，4 项 Important，5 项 Minor，整体 With fixes**。Spec 硬约束（只读采集、总量口径、NULL 语义、事务原子性、summary 固定契约、登录独立性、交付边界）全部落位。

以下修复仅覆盖 Important 全部 4 项 + 同通路的 Minor 1 项；其余 Minor 记录在案不修（见第四节）。

## 二、修复项

### 修复 1：显式 rebuild 标志，堵住"重写后增长"文件的冲突死循环（评审 Issue 1）

**问题**：`app/codex_api.py::_process_file` 在文件增长但前缀指纹不匹配时（前缀被改写）正确判定 restart 从头解析；但 `app/db.py::_codex_is_rebuild` 只覆盖"parser_version 变化 / 变短 / 模式切换 / **同大小**指纹变化"四种情形。文件**变长且前缀改写**时不判重建 → 重放的同 key 行内容已变 → 触发 `CodexUsageConflict` → 批次回滚、offset 不推进 → 每轮扫描都重复该循环，该文件镜像永久停更（无法自愈）。

**方案**：让采集器把"本轮已判定重建"显式带给存储层，不再靠 DB 层从元数据反推：

- `app/codex_api.py`：`FileBatch` 契约增加顶层键 `rebuild: bool`（`_process_file` 中 `restart` 为真即置 True；不落 progress 表，属批次属性）。这是对计划「固定数据契约」中 FileBatch 的显式扩展裁决，FileProgress 不动。
- `app/db.py`：`commit_codex_batch` 的重建判定改为 `batch.get("rebuild") or _codex_is_rebuild(stored, progress)`；保留原元数据推断作为兜底。命中即按现有重建分支同事务删除该文件旧记录后从头写入。
- 兼容：现有测试夹具的 batch 字典不带 `rebuild`，`.get()` 默认 False，行为不变。

### 修复 2：补冲突分支测试（评审 Issue 4）

`tests/test_codex_db.py` 新增两条 DB 级用例（直接构造 batch，不经采集器）：

1. **重写增长重建**：先落文件批次（rows=[s:1] 内容 A，file_size=N、fingerprint=F1）；再提交 `rebuild=True`、file_size>N、fingerprint=F2、rows=[s:1] 内容 B 的批次 → 断言不抛冲突、`codex_totals("all")` 反映内容 B、progress 落库为新游标。
2. **不兼容冲突回滚**：先落 s:1（内容 A）；再提交同 `(session_id,event_mode,event_seq)` 但 token/时间不同、`rebuild` 不设、progress 与已存一致的批次 → 断言抛 `CodexUsageConflict`、`codex_totals` 不变、`codex_file_progress` offset 保持。

### 修复 3：无 turn_context 文件的重放一次性守卫（评审 Issue 2）

**问题**：`_process_file` 的 restart 条件含"文件增长且 `last_model` 为空 → 从头重放"。Spec 实测 296/301 文件无 `turn_context`，其 `last_model` 永远为 None → 每次增长都全文件重放，违反"指纹匹配不从头重扫"的增量快速路径。问题源头是计划 T1 Step 4 文本缺"只放一次"守卫，实现忠实照抄（计划缺陷，本修复即裁决修正）。

**方案**：

- `FileProgress` 契约与 `codex_file_progress` 表增加 `model_backfill_done`（bool / INTEGER DEFAULT 0），沿用 `_ensure_table_columns` 迁移机制补列。
- `_process_file`：该 restart 分支追加 `and not known.get("model_backfill_done")`；批次 progress 组装时，若 `known` 存在且本轮解析后仍无模型则置 True（`bool(known is not None and not parsed["last_model"])`，仅在产出批次时落库，语义即"已为该文件做过一次回填重放"）。
- 测试夹具同步：`tests/test_codex_api.py::fresh_progress` 增加 `model_backfill_done=False`；相关构造 progress 的测试补字段。
- `tests/test_codex_api.py` 新增用例：无 turn_context 文件两轮增长，第二轮 batch `rows` 只含新增行（当前实现会从头重出旧行，断言长度即可区分），证明重放只发生一次。

### 修复 4：后台导入完成后前端自动刷新 + revision 计入模型回填（评审 Issue 3 + Minor 5）

**问题**：summary 的 `importing`/`revision` 字段前端零消费；首次进入统计页触发防抖导入后，`auto_sync` 关闭的用户停留在零 KPI 态直到手动交互。计划 T4 要求"T3 返回 revision 变化/后台完成时刷新一次，不能只等待切页"。

**方案（复用既有机制，不新建轮询）**：

- `app/web/app.js`：`loadCodexSummary` 成功路径检测 `d.importing === true` 或 `d.revision` 较上次见到的值变化时，武装一次既有 `pollUntilIdle`（复用 T4 的 2.5s timer 与 idle/失败清理路径；记录 `revision` 见过的值防重复武装）。
- `app/server.py::_sync_codex_local`：revision 递增条件从仅 `inserted > 0` 扩展为"镜像记录或模型归属实际变化"（模型回填计数由 `db.commit_codex_batch`/`_codex_write_rows` 暴露，具体形态按现有代码最小改动）。
- 测试：`tests/test_codex_db.py` 补一条"空模型行后续被补全模型 → model 补上且 revision 计入"；`tests/test_codex_server.py` 补一条 summary 返回 importing=true 时前端武装轮询的结构断言（如可测）；浏览器脚本 `scripts/check_codex_ui.cjs` 顺手把 summary mock 的 `cost_partial` 对齐为 `true`（Minor 9）。

## 三、验证计划

1. 专项：`python -m pytest tests/test_codex_api.py tests/test_codex_db.py tests/test_codex_server.py tests/test_codex_ui_contract.py tests/test_report_api.py -q`
2. 全量：`python -m pytest -q`（基线 540 passed，只增不减）+ `node --check app/web/app.js`
3. 浏览器回归（环境可用时）：`scripts/serve_codex_fixture.py` + `scripts/check_codex_ui.cjs`；不可用则明确报告未验证，不以静态检查冒充。

修复不签入（全局规则：人工确认后才签入）。复审评审包用工作区 diff 限本次修复文件生成（沿用交付二先例），做一次 scoped re-review。

提交建议（获授权后执行）：
```
git add app/codex_api.py app/db.py app/server.py app/web/app.js tests/test_codex_api.py tests/test_codex_db.py tests/test_codex_server.py scripts/check_codex_ui.cjs
git commit -m "fix: codex rebuild flag, backfill guard and import refresh"
```

## 四、不修项（已记录至 ledger，留交付二/观察）

| 评审编号 | 内容 | 处置 |
|---|---|---|
| Minor 6 | `_dashboard_all_payload` 的 today 键仅 range=today 并入 DSH，口径潜在不一致 | 留交付二（前端现只消费 totals） |
| Minor 7 | `read_snapshot` stat/read 竞态可致一轮假性重建（自愈） | 留观察 |
| Minor 8 | records/写入路径每行一次 SELECT 的 N+1（一次性成本） | 留交付二 |
| Minor 9 | 浏览器 mock `cost_partial` 不一致 | 随修复 4 顺手对齐 |

## 五、边界重申

- 不改记录页行为；不实现统一来源路由（交付二 T6）；不新增 Codex 凭证控件。
- 不修改需求文档；本修复不改变交付一已声明的已知边界。
- 涉及文件仅：`app/codex_api.py`、`app/db.py`、`app/server.py`、`app/web/app.js`、`tests/test_codex_api.py`、`tests/test_codex_db.py`、`tests/test_codex_server.py`、`scripts/check_codex_ui.cjs`。
