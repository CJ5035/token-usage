# ZCode 缓存子集口径修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修正 GoGauge ZCode 区块的 token 聚合与费用估算公式——ZCode 源库 `input_tokens` 为全量输入（cache_read ⊆ input），现行公式把缓存命中重复计入总量与费用，导致总 TOKEN 虚增 ~93%、命中率显示 ~48%（实际 ~94%）、估算费用虚增 4~5 倍。

**Architecture:** 三处后端修改（聚合列 `_ZCODE_AGG_COLS`、导入侧费用入参、历史 cost_raw 一次性回填）+ 测试夹具重写为真实子集语义。前端与其他数据源（BAI/Claude Code/CommandCode）零改动。

**Tech Stack:** Python 3.12 + sqlite3 + pytest（无新依赖）

**Spec:** [doc/20260904-bug-diagnosis-zcode-token-mismatch.md](20260904-bug-diagnosis-zcode-token-mismatch.md)（"复诊与结论反转"章节 + "修复方案 v2"，本计划逐条落实该方案）

## Global Constraints

- Python 解释器：`python`（不可用时用 `D:\.pyenv\pyenv-win\versions\3.12.10\python.exe`）；禁止 `py`、裸 `pip`
- **不自动签入**：本计划所有任务不含 `git commit`；全部完成且用户确认后由用户执行提交
- 不修改 `app/bai_api.py`、`app/claudecode_api.py`、commandcode 相关聚合（它们的互斥语义公式正确）
- 不修改 `zcode_api.estimate_cost_raw` 函数本体（BAI 侧共用；只在 zcode 调用侧改入参）
- 注释用中文，风格与现有代码一致（说明代码无法自明的约束，不写"修改了什么"）
- 每个任务结束必须 `python -m pytest` 对应测试全绿才算完成
- 测试隔离：走 `tmp_db` fixture（临时目录 + monkeypatch），绝不读本机真实 ZCode/GoGauge 库

---

### Task 1: 聚合公式修正（`_ZCODE_AGG_COLS` + 2 处 ORDER BY）+ 测试夹具重写

**Files:**
- Modify: `app/db.py:1520-1535`（`_ZCODE_AGG_COLS` 及其上方注释）
- Modify: `app/db.py:1727`（`zcode_provider_stats` 的 ORDER BY）
- Modify: `app/db.py:1768`（`zcode_model_stats` 的 ORDER BY）
- Modify: `app/db.py:2515-2530`（`channel_totals` 的 zcode 内联聚合 SELECT）
- Test: `tests/test_zcode_sync.py`（夹具 `_zcode_row` 默认值、`test_first_full_import`、`test_four_layer_aggregates`）
- Test: `tests/test_report_api.py`（`_seed_local` 造数、`test_report_hourly_and_totals_local_dispatch` 断言）

**Interfaces:**
- Consumes: 现有 `zcode_totals / zcode_daily / zcode_provider_stats / zcode_model_stats`（全部经 `_ZCODE_AGG_COLS` 取数，签名不变）与 `channel_totals` 的 zcode 分支（db.py:2515-2530 内联 SELECT）
- Produces: 新口径聚合值——`total_input_tokens = SUM(input + cache_write)`、`uncached_input_tokens = SUM(input - cache_read)`；`hit_rate`（db.py:1775 的 `hit/(hit+miss)` 与 `_totals_from_row` db.py:2492）随 miss 修正自动变为 `cache_read/input`。**Task 2/3 依赖本任务的夹具子集语义。**

- [ ] **Step 1: 重写测试夹具为真实子集语义（先改测试）**

`tests/test_zcode_sync.py` 的 `_zcode_row` 默认值改为（旧值：input=50, cache_read=200, computed=365——违反子集关系且 computed 为全字段之和）：

```python
def _zcode_row(row_id, started_ms=1000, **overrides):
    """构造一行 model_usage 记录.

    真实子集语义: input_tokens 为全量输入 (cache_read ⊆ input),
    computed_total = input + cache_creation + output (不含 reasoning 单列).
    默认值对应新口径 cost_raw=38250, 旧口径(修复前导入)=53250.
    """
    values = {
        "id": row_id, "started_at": started_ms, "session_id": "sess-1",
        "provider_id": "p1", "model_id": "glm-5.3", "status": "success",
        "input_tokens": 200, "output_tokens": 100, "reasoning_tokens": 10,
        "cache_creation_input_tokens": 5, "cache_read_input_tokens": 150,
        "computed_total_tokens": 305, "duration_ms": 1000,
        "time_to_first_token_ms": 200,
    }
    values.update(overrides)
    return values
```

- [ ] **Step 2: 更新 `test_first_full_import` 的存储列断言**

`tests/test_zcode_sync.py:133-142` 改为：

```python
    assert r["input_tokens"] == 200
    assert r["output_tokens"] == 100
    assert r["reasoning_tokens"] == 10
    assert r["cache_write_tokens"] == 5            # ← cache_creation_input_tokens
    assert r["cache_read_tokens"] == 150
    assert r["total_tokens"] == 305                # ← computed_total_tokens (input+cache_creation+output)
    assert r["duration_ms"] == 1000
    assert r["ttft_ms"] == 200                     # ← time_to_first_token_ms
    # 旧导入口径(双算): (200*1 + 100*3 + 150*0.2 + 5*0.5)*100 = 53250 —— Task 2 修正后应为 38250
    assert r["cost_raw"] == 53250
```

同测试中 u3 的 `computed_total_tokens=355` 改为 `305`（与默认 token 一致的子集语义值），对应断言 `r3["total_tokens"] == 355` 改为 `== 305`。

- [ ] **Step 3: 按 Task 1 终值更新 `test_four_layer_aggregates` 聚合断言（费用断言暂留旧值）**

`tests/test_zcode_sync.py:304-376` 中：
- r1 的 `computed_total_tokens=390` 改为 `310`（= input 100 + cache_creation 10 + output 200；390 是全字段之和的错误语义），其上方注释 `# cost_raw = (100*1 + 200*3 + 50*0.2 + 10*0.5)*100 = 71500` 暂保留（Task 2 改）。
- totals 断言改为：

```python
    t = db.zcode_totals("all")
    assert t["request_count"] == 3
    assert t["total_input_tokens"] == 140          # (100+10) + (20+0) + (10+0)  [input+cache_write]
    assert t["uncached_input_tokens"] == 80        # (100-50) + 20 + 10  [input-cache_read]
    assert t["total_reasoning_tokens"] == 30
    assert t["cache_hit_tokens"] == 50
    assert t["cache_write_tokens"] == 10
    assert t["total_output_tokens"] == 260         # 200 + 40 + 20
    assert t["total_tokens"] == 400                # 310 + 60 + 30
    assert t["total_cost_usd"] == 0.000785         # 旧导入口径 (71500+7000)/1e8 —— Task 2 修正后 0.000735
```

- provider stats 断言改为：

```python
    assert p1["total_input_tokens"] == 120         # (100+10) + (10+0)
    assert p1["uncached_input_tokens"] == 60       # (100-50) + 10
```

（p1 的 cost/tps/ttft 断言 Task 1 不动；排序键改为新口径后 p1=340 > p2=60，顺序不变。）

- model stats 断言改为：

```python
    assert m1["hit_rate"] == 45.45                 # 50/(50+60)*100 = cache/input
    assert m1["total_input_tokens"] == 120
    assert m2["hit_rate"] == 0.0                   # 0/(0+20)*100
```

（`_speed_rows` 全部行 cache=0、computed=input+output，天然符合子集语义，不需要改。）

- [ ] **Step 4: 跑测试确认新口径断言失败**

Run: `python -m pytest tests/test_zcode_sync.py -v`
Expected: `test_first_full_import`、`test_four_layer_aggregates` FAIL（140≠190 等）；其余测试 PASS。

- [ ] **Step 5: 修改 `app/db.py` 聚合列与注释**

`app/db.py:1520` 附近，注释整体替换为：

```python
# 公共聚合列. 口径: zcode 源库 input_tokens 为全量输入 (cache_read ⊆ input,
# 与 usage_records/claudecode_usage 的 "input 与 cache 互斥" 语义不同),
# 参照 _CHARTS_AGG_COLS: total_input = input + cache_write (缓存写为独立加数);
# 未命中输入 = input - cache_read; total_tokens 即源库 computed_total (官方口径)
```

`_ZCODE_AGG_COLS`（db.py:1525-1535）前两处聚合表达式改为：

```python
_ZCODE_AGG_COLS = """
               COUNT(*) AS request_count,
               COALESCE(SUM(input_tokens + cache_write_tokens), 0) AS total_input_tokens,
               COALESCE(SUM(input_tokens - cache_read_tokens), 0) AS uncached_input_tokens,
               COALESCE(SUM(reasoning_tokens), 0) AS total_reasoning_tokens,
               COALESCE(SUM(cache_read_tokens), 0) AS cache_hit_tokens,
               COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
               COALESCE(SUM(output_tokens), 0) AS total_output_tokens,
               COALESCE(SUM(total_tokens), 0) AS total_tokens,
               SUM(cost_raw) AS total_cost_raw"""
```

（其余 6 行不变。）

- [ ] **Step 6: 修改两处内联排序键**

`app/db.py:1727`（zcode_provider_stats）与 `app/db.py:1768`（zcode_model_stats）的

```python
        ORDER BY (SUM(input_tokens + cache_read_tokens + cache_write_tokens)
                  + SUM(output_tokens)) DESC
```

均改为：

```python
        ORDER BY (SUM(input_tokens + cache_write_tokens)
                  + SUM(output_tokens)) DESC
```

⚠️ `app/db.py:2044/2075` 的同型 ORDER BY 属于 claudecode 渠道/模型统计（互斥语义，公式正确），**不要改**。
⚠️ `app/db.py:2197/2460`（报表趋势的 zcode tokens 表达式 `input+output+reasoning`）与 `app/db.py:2253`（cost）在子集语义下**本就正确**（input 已是全量输入），**不要改**。

- [ ] **Step 7: 修正报表页 channel_totals 的 zcode 内联聚合**

`app/db.py:2515-2530`（`channel_totals` 的 `channel == "zcode"` 分支）中两行改为：

```python
            f" SUM(z.input_tokens + z.cache_write_tokens) total_input_tokens,"
            f" SUM(z.input_tokens - z.cache_read_tokens) uncached_input_tokens,"
```

该分支没有独立 hit_rate 列——`_totals_from_row`（db.py:2481-2503）由行内 `cache_hit_tokens` / `uncached_input_tokens` 推导 hit_rate，修正 uncached 后自动变为 cache/input。

同步更新 `tests/test_report_api.py`：

`_seed_local`（tests/test_report_api.py:54-70）签名加 `z_cr=0, z_cw=0`，INSERT 的 `cache_read_tokens`/`cache_write_tokens` 改用这两个参数，`total_tokens` 改为 `z_in + z_cw + z_out`（子集语义一致性）：

```python
def _seed_local(iso, z_in=30, z_out=50, c_in=20, c_out=40, z_cr=0, z_cw=0):
    """本地镜像渠道造数 (R6): zcode_usage/claudecode_usage 各 1 行, 直 INSERT (表结构 db.py:190/216)."""
    conn = db.get_db()
    conn.execute(
        "INSERT INTO zcode_usage (id, started_at, provider_id, provider_name, model_id, status,"
        " input_tokens, output_tokens, reasoning_tokens, cache_write_tokens, cache_read_tokens,"
        " total_tokens, cost_raw, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("z1", iso, "prov-1", "Provider1", "glm-4", "ok", z_in, z_out, 0, z_cw, z_cr,
         z_in + z_cw + z_out, (z_in + z_out) * 100_000, "2026-09-01T09:00:00"),
    )
    # claudecode 段不变 (c_in/c_out/cache 0)
```

（claudecode 段保持原样；其余 `_seed_local` 调用方不传新参 → 默认 0，行为不变。）

`test_report_hourly_and_totals_local_dispatch`（tests/test_report_api.py:340-352）造数加缓存维度并更新断言：

```python
    _seed_local(iso=_today_iso(10), z_in=30, z_out=50, c_in=20, c_out=40, z_cr=10, z_cw=2)
    h = db.report_hourly("today")
    assert sum(h["series"]["zcode"]) == 80 and sum(h["series"]["claudecode"]) == 60   # in+out+reason, 与缓存无关
    t = db.channel_totals("today", "zcode")
    assert t["request_count"] == 1 and t["total_input_tokens"] == 30 + 2      # input+cache_write
    assert t["uncached_input_tokens"] == 30 - 10                              # input-cache_read
    assert t["hit_rate"] == 33.33                                             # 10/(10+20)*100
    assert t["total_cost_usd"] == pytest.approx(80 * 100_000 / 1e8)
```

- [ ] **Step 8: 跑测试确认全绿**

Run: `python -m pytest tests/test_zcode_sync.py tests/test_report_api.py -v`
Expected: 全部 PASS（费用断言此刻仍为旧口径值 53250/0.000785，属预期；报表 hourly/series 的 80/60 与缓存无关、不受影响）。

---

### Task 2: 导入侧费用估算修正（缓存命中不再双计费）

**Files:**
- Modify: `app/db.py:1573-1575`（`import_zcode_usage` 内 `estimate_cost_raw` 调用）
- Test: `tests/test_zcode_sync.py`（`test_first_full_import` 与 `test_four_layer_aggregates` 的费用断言切到终值）

**Interfaces:**
- Consumes: Task 1 的夹具子集语义；`zcode_api.estimate_cost_raw(model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, models)` 签名不变
- Produces: 新导入行的 `cost_raw` 按未命中输入计价（Task 3 的回填函数复用同一口径）

- [ ] **Step 1: 费用断言切到新口径终值（先改测试）**

`tests/test_zcode_sync.py` `test_first_full_import`：

```python
    # 手算: 未命中输入 200-150=50 → (50*1 + 100*3 + 150*0.2 + 5*0.5)/1e6*1e8 = 38250
    # (缓存命中 150 只按缓存读价 0.2 计一次, 不再随全额 input 重复计费)
    assert r["cost_raw"] == 38250
```

`test_four_layer_aggregates`：
- r1 上方注释改为 `# cost_raw = (50*1 + 200*3 + 50*0.2 + 10*0.5)*100 = 66500  [未命中输入 100-50=50]`
- totals：`assert t["total_cost_usd"] == 0.000735         # (66500+0+7000)/1e8`
- provider：`assert p1["total_cost_usd"] == 0.000735        # (66500+7000)/1e8`

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_zcode_sync.py::test_first_full_import tests/test_zcode_sync.py::test_four_layer_aggregates -v`
Expected: FAIL（实际 cost 仍为 53250/71500 旧口径）。

- [ ] **Step 3: 修改 `app/db.py:1573` 调用入参**

```python
        # ZCode 源库 input_tokens 已含缓存命中 (cache_read ⊆ input):
        # 输入按未命中部分 (input-cache_read) 计价, 缓存读/写另按各自单价,
        # 避免缓存命中先随全额 input 计费、再按缓存价重复计费
        cost_raw = estimate_cost_raw(
            model_id, input_tokens - cache_read, output_tokens, cache_read, cache_write, pricing_models
        )
```

- [ ] **Step 4: 跑测试确认全绿**

Run: `python -m pytest tests/test_zcode_sync.py -v`
Expected: 全部 PASS。

---

### Task 3: 历史 cost_raw 一次性回填 + 启动接线

**Files:**
- Modify: `app/db.py`（在 `save_zcode_watermark` 之后新增常量与函数；该函数实际位于 db.py:1608-1614）
- Modify: `app/server.py:722-727`（`_sync_zcode_local` 开头接线）
- Test: `tests/test_zcode_sync.py`（文件末尾新增 3 个测试）

**Interfaces:**
- Consumes: `_raw_payload(conn) / _write_payload(conn, data)`（settings 白名单外键机制，参照 `_ZCODE_WATERMARK_KEY` 先例）；`estimate_cost_raw`（Task 2 已对齐口径）
- Produces: `db.maybe_recompute_zcode_cost_raw(pricing_models: list[dict] | None = None) -> int`（返回重算行数；标记位已置或定价表缺失/为空时返回 0 且不置标记）与常量 `db._ZCODE_COST_RECALC_KEY = "zcode_cost_recalc_v1"`

- [ ] **Step 1: 写回填测试（先写测试）**

`tests/test_zcode_sync.py` 末尾追加：

```python
# ---------------------------------------------------------------------------
# 9. 历史 cost_raw 一次性回填 (缓存子集口径修复)
# ---------------------------------------------------------------------------


def test_recompute_cost_raw_backfill(tmp_db, zcode_source):
    _append_zcode_rows(zcode_source, [_zcode_row("u1", 1000)])
    assert _sync() == 1
    # 模拟修复前导入的历史脏数据: 旧公式按全额 input 计费
    # (200*1 + 100*3 + 150*0.2 + 5*0.5)*100 = 53250
    db.get_db().execute("UPDATE zcode_usage SET cost_raw = 53250 WHERE id = 'u1'")
    db.get_db().commit()

    assert db.maybe_recompute_zcode_cost_raw(PRICING) == 1
    r = db.get_db().execute(
        "SELECT cost_raw FROM zcode_usage WHERE id = 'u1'"
    ).fetchone()["cost_raw"]
    assert r == 38250                     # 未命中输入 (200-150) 按输入价, 缓存只按缓存价

    # 幂等: 标记位已置, 二次调用 0 行
    assert db.maybe_recompute_zcode_cost_raw(PRICING) == 0
    assert db._raw_payload(db.get_db()).get(db._ZCODE_COST_RECALC_KEY) == 1


def test_recompute_cost_raw_empty_table(tmp_db):
    # 空表: 置标记位并返回 0 (保证新版启动后即使无新数据也完成口径切换)
    assert db.maybe_recompute_zcode_cost_raw(PRICING) == 0
    assert db._raw_payload(db.get_db()).get(db._ZCODE_COST_RECALC_KEY) == 1


def test_recompute_cost_raw_skips_without_pricing(tmp_db, zcode_source):
    # 定价表缺失/为空: 不回填、不置标记 (否则 estimate_cost_raw 全返回 0,
    # 会把全部历史 cost_raw 清零并误标"已完成", 不可逆)
    _append_zcode_rows(zcode_source, [_zcode_row("u1", 1000)])
    assert _sync() == 1
    db.get_db().execute("UPDATE zcode_usage SET cost_raw = 53250 WHERE id = 'u1'")
    db.get_db().commit()

    assert db.maybe_recompute_zcode_cost_raw([]) == 0
    r = db.get_db().execute(
        "SELECT cost_raw FROM zcode_usage WHERE id = 'u1'"
    ).fetchone()["cost_raw"]
    assert r == 53250                                     # 原值未动
    assert db._raw_payload(db.get_db()).get(db._ZCODE_COST_RECALC_KEY) is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_zcode_sync.py::test_recompute_cost_raw_backfill tests/test_zcode_sync.py::test_recompute_cost_raw_empty_table tests/test_zcode_sync.py::test_recompute_cost_raw_skips_without_pricing -v`
Expected: FAIL，`AttributeError: module 'app.db' has no attribute 'maybe_recompute_zcode_cost_raw'`

- [ ] **Step 3: 在 `app/db.py` 实现回填函数**

在 `save_zcode_watermark`（db.py:1608-1614）之后新增：

```python
_ZCODE_COST_RECALC_KEY = "zcode_cost_recalc_v1"


def maybe_recompute_zcode_cost_raw(pricing_models: list[dict[str, Any]] | None = None) -> int:
    """一次性按缓存子集口径重算 zcode_usage.cost_raw, 返回重算行数.

    修复前导入的行按全额 input 计费, 缓存命中部分被双算 (input 已含缓存命中,
    cache_read 又单算一次); 此处统一按 estimate_cost_raw(input-cache_read,
    output, cache_read, cache_write) 重算. 幂等: settings 标记位防重入,
    二次调用直接返回 0. 定价表缺失/为空时不更新也不置标记 (防止把历史
    cost_raw 全表清零后误标完成), 待定价可用后随下次同步重跑.
    """
    conn = get_db()
    if _raw_payload(conn).get(_ZCODE_COST_RECALC_KEY):
        return 0
    from .zcode_api import _load_model_pricing, estimate_cost_raw

    models = pricing_models if pricing_models is not None else _load_model_pricing()
    if not models:
        return 0
    rows = conn.execute(
        "SELECT id, model_id, input_tokens, output_tokens,"
        " cache_read_tokens, cache_write_tokens FROM zcode_usage"
    ).fetchall()
    conn.executemany(
        "UPDATE zcode_usage SET cost_raw = ? WHERE id = ?",
        [
            (estimate_cost_raw(
                r["model_id"], r["input_tokens"] - r["cache_read_tokens"],
                r["output_tokens"], r["cache_read_tokens"], r["cache_write_tokens"],
                models,
            ), r["id"])
            for r in rows
        ],
    )
    data = _raw_payload(conn)
    data[_ZCODE_COST_RECALC_KEY] = 1
    _write_payload(conn, data)
    conn.commit()
    return len(rows)
```

（守卫说明：`estimate_cost_raw` 对未收录模型返回 0 是"单行"行为，可接受；但**定价表整体缺失**时若照常回填，会把全表 cost_raw 覆盖成 0 并永久置标记——`if not models: return 0` 挡住的就是这个不可逆场景。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_zcode_sync.py -v`
Expected: 全部 PASS（含既有测试）。

- [ ] **Step 5: 在 `app/server.py` 启动导入路径接线**

`app/server.py:722-727`（`_sync_zcode_local` 的 try 块开头、水位读取之前）插入一行：

```python
    global _zcode_sync_error
    try:
        db.maybe_recompute_zcode_cost_raw()  # 历史 cost_raw 一次性口径回填 (标记位幂等, 二次起空转)
        wm = db.get_zcode_watermark()
```

说明：放在早退分支 `if not rows: return 0` **之前**，保证无新数据时回填也能完成；位于既有 try 内，异常被现有 except 吞掉，不影响同步主流程。启动路径经 `zcode_import_async()`（server.py:739）与 `sync_usage()`（server.py:669-670）都会走到这里。

- [ ] **Step 6: 跑测试确认全绿**

Run: `python -m pytest tests/test_zcode_sync.py tests/test_zcode_server.py -v`
Expected: 全部 PASS。

---

### Task 4: 全量回归 + 前端/文档收尾核对

**Files:**
- Modify: `doc/20260904-bug-diagnosis-zcode-token-mismatch.md`（状态行更新为"已修复"）
- Verify: 前端无需改动（只核对）

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS（重点确认 claudecode/bai/commandcode 测试无回归——它们语义未动）。

- [ ] **Step 2: 前端零改动核对**

Run: `grep -n "total_input_tokens\|total_reasoning_tokens" app/web/app.js`
Expected: ZCode 区块（app.js:868 KPI、渠道/模型表、daily7 趋势）消费的均为后端聚合字段，后端修正后数值自动正确；确认无前端改动需要提交。

- [ ] **Step 3: 更新诊断文档状态**

`doc/20260904-bug-diagnosis-zcode-token-mismatch.md` 头部状态行改为：

```markdown
- **状态**：已修复（2026-09-05 按修复方案 v2 实施；历史 cost_raw 随新版首次启动自动回填）
```

- [ ] **Step 4: 提请人工确认与提交（项目规则：不自动签入）**

向用户报告测试结果，待确认后建议提交（单 commit）：

```bash
git add app/db.py app/server.py tests/test_zcode_sync.py doc/
git commit -m "fix: ZCode 缓存子集口径修正 - 总TOKEN/命中率/费用不再双算缓存命中 + 历史cost_raw一次性回填"
```

- [ ] **Step 5: 部署与实机验收（人工步骤）**

1. `build.bat` 重建，替换 `D:\绿色版\GoGauge\GoGauge.exe`
2. 启动新版（首次同步时自动回填该实例 gousage.db 的历史 cost_raw）
3. 验收基准（对照官方页面）：
   - ZCode"总 TOKEN 消耗" ≈ `SUM(total_tokens)`（累计 16.9 亿级）+ 推理量（<0.1%）
   - 模型表缓存命中率 ~94%（官方 ~95%）
   - 估算费用回落至修正值（9月4日全天约 $28 / ¥200，而非 $145 / ¥872）
   - 任选窗口："总 TOKEN 消耗" − 推理量 ≈ 官方该窗口 Token 数

---

## Self-Review 记录（v2，经 2026-09-05 review 循环修订）

1. **Spec 覆盖**：修复方案 v2 共 7 条 → 1→Task 1（含 review 补充的 `channel_totals` zcode 分支 db.py:2515-2530）；2→Task 2；3→Task 3（含 review 补充的定价表空守卫）；4→Task 1/2/3 的测试改造 + Task 4 Step 1 全量 pytest；5（前端不动）→Task 4 Step 2 核对；6（部署）→Task 4 Step 5；7（验收）→Task 4 Step 5。无缺口。
2. **位点清单核对**（db.py 全部直查 zcode_usage 的 SQL）：1661/1686/1724/1765 走 `_ZCODE_AGG_COLS`（Task 1 修）；2515-2530 内联（Task 1 Step 7 修）；2197/2460 的 `input+output+reasoning` 与 2253 的 cost 在子集语义下本就正确（勿改，已注明）；2214 仅取日期；1586/1596 仅计数。
3. **占位符扫描**：所有代码步骤含完整代码与精确行号；无 TBD/TODO。
4. **类型一致性**：`maybe_recompute_zcode_cost_raw(pricing_models=None) -> int` 在 Task 3 实现、测试与 server 接线处签名一致；`_ZCODE_COST_RECALC_KEY` 常量名在实现/测试/文档一致；夹具默认值（input=200/cr=150/cw=5/out=100/reason=10/computed=305）贯穿 Task 1/2/3 的所有期望值（205/50/38250/53250/45.45 等）经手算复核；`_seed_local` 新参 `z_cr/z_cw` 默认 0，既有调用方行为不变。
5. **TDD 排序**：每个任务结束测试全绿（Task 1 的费用断言暂留旧口径值并在注释中标明 Task 2 切换，属刻意的两步红绿）。
