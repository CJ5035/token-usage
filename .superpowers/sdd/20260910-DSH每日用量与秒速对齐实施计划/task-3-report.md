# Task 3 实施报告：接入通用报表

## 完成内容

- `app/server.py` 通过 Task 2 的 `get_dsh_summary(range_)` 消费历史聚合；每个需要 DSH 的响应只读取一次摘要快照。Windows 和 dashboard 使用一次 `all` 摘要派生 today/yesterday/7d/30d，避免重复扫描或读取。
- Windows、渠道明细、dashboard all、日报、小时图、渠道趋势和渠道概览均接入 DSH 范围数据。Windows 合并 `data_since`，保留 DB compare 结果，并新增 `compare.dsh_excluded_from_compare` 与兼容字段 `includes_dsh_today`。
- DSH 请求数与费用保持未知：渠道行和概览使用 `null`，汇总标记 `request_count_exact=false`、`cost_partial=true`，小时桶不伪造 requests。
- 对象响应新增 `dsh_status`，包含 `found`、`scanning`、`stale`、`refresh_error`、`updated_at`、`retry_after_seconds`；小时和趋势端点保持原有 24 桶/数组形状。
- `/api/dsh/usage` 保留旧的 `total` 和 `today` 别名，同时提供 Task 2 的范围摘要和状态字段。
- `db.report_daily` 新增仅服务层可供给的关键字参数 `extra_rows` 与 `unavailable_sources`。SQL 日行与额外日行在选择 day/week/month 粒度前合并；无 SQL 段时也会格式化纯 DSH 日数据。周标签继续使用 Monday-first `%Y-W%W`，且额外行遵守 channel 过滤。

## 测试

- 新增固定四步 DSH 摘要覆盖：today `1550`、yesterday `200`、7d `1780`、平均有效速度 `10`、数据起点为当前固定测试日的 6 天前（本执行环境为 `2026-09-04`）。断言 Windows、channels、dashboard、daily、hourly、overview、trend 一致。
- 覆盖纯 DSH daily、DB/DSH 合并跨度的 all→week 粒度、未知请求/费用语义、24 小时桶形状、状态元数据，以及指定其他渠道的 Windows 请求不读取 DSH。
- 迁移旧的“DSH 只并入 today”断言，更新 Codex/empty-state 夹具为 Task 2 的范围摘要契约。

## 验证

- `pytest -q tests/test_report_api.py tests/test_empty_state.py tests/test_codex_server.py tests/test_zcode_server.py tests/test_claudecode_server.py tests/test_dsh_api.py tests/test_dsh_background.py`：`141 passed, 3 skipped`
- `python -m compileall -q app/server.py app/db.py tests/test_report_api.py tests/test_empty_state.py tests/test_codex_server.py`：通过。
- `git diff --check`：通过。

## 自审

- DB 层没有导入或调用 `dsh_api`；DSH 适配均在 server 层，且不存在第二个日志解析器。
- 所有需要多窗口数据的响应从单个 `all` 摘要派生窗口，避免响应内跨快照不一致。
- `all` 日报粒度使用过滤后的 SQL 和 DSH 原始日行的共同跨度；channel 过滤和 week 标签均有回归断言。

## 关注点

- DSH 费用和请求数没有可用原始口径，因此混合汇总中的数值只代表 DB 已知部分；响应以 `cost_partial` 和 `request_count_exact=false` 明示这一点。

## Fix round 1

- `_dsh_range` 现在以 Task 2 每日聚合的 `tps × seconds` 恢复有效测速分子；不再使用全部 output，因此被 parser 排除的测速样本不会污染跨范围 TPS。
- `/api/report/hourly` 在 DSH 参与时始终从同一次摘要写入 `dsh_status`，包括 found 但选定日期没有 steps/tokens 的空桶响应；`buckets`、`series` 与 24 桶形状保持不变。
- `/api/dsh/usage` 统一读取一次 `all` 摘要，再派生请求 range 和兼容 `today` 字段。因此 `range=yesterday` 仍返回 yesterday totals，同时 `today` 反映同一快照的真实 today，而不增加扫描。

### Fix round 1 验证

- 回归用例将总 output `1000`、有效测速 `seconds=10`、`tps=10` 的拒绝样本场景送入 `/api/dsh/usage?range=yesterday`，断言 today 仍为 `10 tps`，请求只读取一次 `all` 摘要。
- 覆盖 hourly 空用量的完整六字段 `dsh_status`。
- `pytest -q tests/test_report_api.py tests/test_empty_state.py tests/test_codex_server.py tests/test_dsh_api.py tests/test_dsh_background.py`：`125 passed, 3 skipped`。
- `python -m compileall -q app/server.py tests/test_report_api.py` 与 `git diff --check`：通过。
