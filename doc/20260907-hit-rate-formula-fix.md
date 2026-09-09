# 缓存命中率口径修正实施文档

**日期**: 2026-09-07
**问题**: 缓存命中率公式口径错误，结果系统性偏高（本程序 97.0% vs cc-switch 86.5%）
**前置**: `doc/20260907-cache-hit-rate-fix-plan.md`（已补齐各聚合函数的 hit_rate 字段，字段缺失问题已解决）
**状态**: ⏳ 待用户确认

## 问题结论

现行公式 `hit_rate = cache_read / (cache_read + input)` 把**缓存写入（cache_write）排除在分母外**。
缓存写入也是输入流量，且是"未命中才写入"的部分，排除后命中率系统性虚高。

**目标口径（与 cc-switch / Anthropic 通行语义一致）**：

```
hit_rate = cache_read / (cache_read + input + cache_write) × 100
```

语义：**全部输入流量中从缓存读取的比例**，即 `命中 / 总输入`。

## 各渠道数学等价性验证

统一实现 `hit / (hit + miss + cw)` 后，各渠道因 `input` 字段语义不同但结果等价：

| 渠道 | miss (uncached_input_tokens) 定义 | 分母 hit+miss+cw 化简 | = 总输入 |
|------|-----------------------------------|----------------------|----------|
| commandcode (usage_records) | `SUM(input)` | input + read + write | ✓ |
| claudecode | `SUM(input)` | input + read + write | ✓ |
| zcode | `SUM(input - cache_read)`（input 含 read） | input + write | ✓ |
| codex | `SUM(MAX(input - cache_read, 0))`（input 含 read） | input + write | ✓ |
| charts_buckets | `tokens_in - cache_read` | 同上 | ✓ |

实测对照（开发库 09-03 数据，当日有 cache_write=722k）：
- 旧口径 99.05% → 新口径 94.65%
- 无 cache_write 的日期（09-01、09-02）新旧口径结果相同（不受影响）

## 修改清单

### 1. `app/db.py` — 15 处公式（核心修改）

统一改为：

```python
hit = int(row["cache_hit_tokens"] or 0)
miss = int(row["uncached_input_tokens"] or 0)
cw = int(row["cache_write_tokens"] or 0)
hit_rate = (hit / (hit + miss + cw) * 100) if (hit + miss + cw) > 0 else 0.0
```

| # | 行号 | 函数 |
|---|------|------|
| 1 | 1053 | `_charts_totals_dict` |
| 2 | 1072 | `_charts_daily_dict` |
| 3 | 1474 | `model_stats` |
| 4 | 1520 | `daily_stats` |
| 5 | 1599 | `totals` |
| 6 | 1842 | `zcode_totals` |
| 7 | 1877 | `zcode_daily` |
| 8 | 1922 | `zcode_provider_stats` |
| 9 | 1969 | `zcode_model_stats` |
| 10 | 2183 | `claudecode_totals` |
| 11 | 2217 | `claudecode_daily` |
| 12 | 2255 | `claudecode_channel_stats` |
| 13 | 2292 | `claudecode_model_stats` |
| 14 | 2952 | `_totals_from_row`（channel_totals 三表分派复用） |
| 15 | 3457 | `_codex_hit_rate`（codex 全家族复用，改签名传 cache_write） |

注：`uncached_input_tokens` **字段定义不变**（前端"未命中"副文案、字段语义均不动），只改 hit_rate 分母。

### 2. `app/db.py` — 3 处 docstring 同步

- 行 1098 `charts_aggregate`：`cache_read / (cache_read + uncached_input)` → 新口径
- 行 1944 `zcode_model_stats`：`hit/(hit+miss)*100` → 新口径
- 行 2942 `_totals_from_row`：`hit/(hit+miss) 口径` → 新口径

### 3. `CLAUDE.md` 行 48 — 口径约定更新

```
hit_rate = cache_read / (cache_read + input)
```
改为
```
hit_rate = cache_read / (cache_read + input + cache_write)
```
"改聚合口径需同步三处"的描述同步更新为全渠道聚合函数（本文档清单）。

### 4. 测试断言 — 2 处期望值更新

| 文件:行 | 旧值 | 新值 | 数据 |
|---------|------|------|------|
| `tests/test_report_api.py:349` | `33.33` | `31.25` | 10/(10+20+2)×100，z_cw=2 |
| `tests/test_zcode_sync.py:380` | `45.45` | `41.67` | 50/(50+60+10)×100，cw=10 |

其余 0 值断言（空表/无缓存数据）不受影响，无需改动。

### 5. 前端 `app.js` — 无需修改

hit_rate 全部来自后端字段，前端无本地计算；"命中 X · 未命中 Y"副文案引用的
`cache_hit_tokens`/`uncached_input_tokens` 字段含义不变。

## 不修改的内容（明确排除）

- `uncached_input_tokens` 字段定义（各渠道维持现状）
- `total_input_tokens` 字段定义
- `doc/20260907-cache-hit-rate-fix-plan.md` 已落地的 7 个函数字段补齐（本次只改其公式）
- 数据集差异问题（请求数 253 vs 299，命中差 1.3M）——另有成因，需单独排查，不在本次范围

## 实施步骤

1. ⏳ 本文档经用户确认
2. ⏳ 修改 `app/db.py` 15 处公式 + 3 处 docstring
3. ⏳ 更新 `CLAUDE.md` 行 48
4. ⏳ 更新 2 处测试断言
5. ⏳ 编译：`python -m py_compile app/db.py`
6. ⏳ 全量测试：`python -m pytest -q`
7. ⏳ 数据实测：验证 09-03 数据从 99.05% → 94.65%

## 预期效果

- claudecode 渠道"今天"命中率显示从 97.0% 降至约 87%，与 cc-switch 86.5% 基本对齐
- 残余小差异来自两侧数据集不同（本程序少 46 条记录），属采集侧问题，另案处理
- 全渠道（commandcode/zcode/claudecode/codex/首页汇总）命中率口径统一为"命中/总输入"

## 风险评估

- **影响面**：仅 hit_rate 数值变化，字段名/结构不变，向后兼容
- **回滚**：单点公式回退即可
- **历史数据**：公式在查询侧计算，不落库，无需数据迁移
