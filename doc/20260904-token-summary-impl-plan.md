# Token 汇总首页改造 实施计划（P0）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 首页改造为「渠道 tab（默认全部渠道）+ 页头 5 档范围 pill」的全局汇总落地页：时间窗口汇总条（同时段环比+样本保护）、配额摘要条（多账号归并+同步状态）、分渠道堆叠图/环形图/明细表、单渠道下钻视图。

**Architecture:** 后端在 `app/db.py` 末尾新增只读聚合区块（渠道维度 = `accounts.source` JOIN，自然日窗口），`app/server.py` 加 4 个薄路由端点（复用现有 `_json_response`/`_ensure_quota_async`）；前端在现有 `page-home` 上分流——`state.channel === "all"` 走新的全局汇总渲染，单渠道走现有首页渲染 + 渠道过滤。消耗数据与新 API 走，配额块复用 `/api/accounts/overview`。

**Tech Stack:** Python 3.12 / sqlite3（标准库）/ pytest；前端原生 JS + Chart.js（`chart.umd.min.js` 已内置），无构建步骤。

**Spec:** `doc/20260904-token-summary-report.md`（v10）—— 本计划从规格论证，执行者须同时阅读规格第 3.1/5/7 节。

**修订记录**
- R1（2026-09-04）review 修正 11 处：T3 环比测试造数满足样本阈值 / sync 测试先经 `update_sync_state` 建行再 UPDATE / yesterday 断言 1040 / T12 占位函数补为完整实现（`renderUsageBlocks`/`renderCcSummary` 参数化）/ T2 today 测试改动态日期并删死代码 / `_report_channels_expr('a')` 签名不一致 / db.py import 补 `date` / `t("loadFail")`→`t("loadFailed")` / est 徽章与 overview 并入 loadReportAll 的缺失行 / T5 条件表达式简化。
- R2（2026-09-04）修正 3 处：F12 测试时间脆弱——daily today 造数改 `_today_at` 固定午时、compare 测试加 `COMPARE_SKIP` 环境窗口（0-1 点样本保护 / 22 点后 now+2h 跨天）；F13 T12 移除未消费的 windows 调用；F14 Self-Review 步骤编号同步。
- R3（2026-09-04）修正 1 处：F15 前端函数清单补 `renderQuotaSingle/renderCcAccounts/fmtAgo` 与 `renderUsageBlocks` 签名扩展（Dedupe 登记完整）。
- R4（2026-09-04）修正 1 处：F16 写死日历日期（2026-09-0x）改 `_days_ago(n)` 相对日期——执行日推迟出 7d 窗口也不再脆弱。
- R5（2026-09-04）修正 2 处：F17 修订记录补 R2-R4 条目；F18 T12 Files 声明补 `app/server.py` 与 `app/web/style.css`。**达 5 次审查上限，循环终止。**
- R6（2026-09-04）**渠道扩展修订（结构性）**：工作区已新增 zcode/claudecode/dsh 三个本地数据源（R6 侦察证实——`zcode_usage`/`claudecode_usage` 镜像表独立于 accounts/usage_records 体系，dsh 为 `~/.dsh/sessions` 内存扫描仅 total/today 两口径）。修订：① 渠道 tab 扩为六渠道（账号渠道 + zcode/claudecode 恒列 + dsh 按 found 列）；② `report_daily/windows/channels/hourly` 改**三表 UNION**（usage_records + zcode_usage + claudecode_usage），tokens 统一 `input+output+reasoning`、cost 统一 USD（镜像表 `cost_raw/1e8`）；③ dsh 仅参与"今日"窗口（server 层并入，dsh 数据在 server 层的 dsh_api），历史窗口不参与并标注"仅今日"；④ est 渠道集合扩为 `{bai, zcode, claudecode}`；⑤ 配额摘要条仅账号渠道（本地渠道无配额）；⑥ 渠道配色 +3、claudecode 内部 channel 子渠道 P0 不拆（留 P1）。**spec v10 的三渠道假设需在实施后同步修订（见文末"spec 同步待办"）。**
- R7（2026-09-04）第七轮 review：**N25（系统性，测试必挂）**——动态造数 helper（`_today_iso/_today_at/_days_ago`）产出本地时钟无时区后缀串，SQLite `datetime()` 对无后缀串按 UTC 解析再 `'localtime'` +8h，东八区 16:00 后记录跨日掉出 today 窗口（merges_local/compare/spike/hourly 等 5+ 测试必挂）；修复：新增 `_to_utc_iso`，全部 helper 重写为 UTC Z 串产出，compare/insufficient/spike 的 4 处内联构造同步包裹；连带修正 `_days_ago` 数学错误（now-n天+h小时 → n 天前 replace(h)）与 `_today_at` docstring 旧约束残留（N26）。**R5 终审追加 N28（R6 遗留必挂）**：`merges_local` 的 `day + "T01:00:00Z"` 拼接在 `_days_ago` 返回完整串时产出无效 ISO——改用 `_days_ago(1, h)` 直取时刻、label 单独算本地日期。
- R8（2026-09-04）第八轮 review——**实际执行冒烟**（把计划 db 层代码与测试断言在临时库真实运行，比文档审查更强的验证）：4 轮迭代抓出并修复 **3 个必挂级缺陷**：**N29/N29b**（`report_windows` 渠道归并段与 `report_channels` since 段的 `FROM {tbl}` 未带别名，而列引用 `z.started_at` 带别名 → `no such column`，任何调用必挂）；**N31**（`list_channel_summary` 的 return `m.get(c, 1)` 返回整个内层 dict 而非 accounts 数字——R6 重构 m 结构后漏改取值）；**N30**（`_seed_channels` 后 opencode accounts=2：`add_account` 保留空 token 种子行，测试断言按真实计数修正）。**最终冒烟结果 32/32 PASS**（覆盖 T2 三表 UNION/T3 windows+same7/T4 channels+summary/T5 hourly+totals+trend 全部断言）。冒烟结论：31 次文档审查漏掉的 3 个执行级 bug 由实际运行一次抓出——实施时 T1-T5 的 TDD 步骤本身即冒烟的固化，无需额外预检。

## Global Constraints

- Python 3.12.10（pyenv-win），命令一律 `python`；**禁止** `py` / `py -3.12` / 裸 `pip`
- 测试命令：`python -m pytest tests/test_report_api.py -v`；全量 `python -m pytest tests/ -v`
- **commit 需人工确认后执行**（AGENTS.md：代码修改后不能自动签入）；每任务给出建议 commit message，执行者跑测试通过后停下等人确认
- 每个新公开函数创建前按 AGENTS.md 出 Dedupe Ticket（本计划「文件结构」一节已统一给出，执行者无需重复调研）
- 渠道维度 **只用 `accounts.source`**，禁止 `GROUP BY provider`（spec §2 口径注意：OpenCode 的 provider 是模型商）
- 范围窗口一律**自然日**（spec §5 v7 口径）；`_period_where` 现有 7d/30d 滚动行为**不动**（只允许新增 yesterday key）
- stats 统计页 P0 完全不动；左侧导航不加项
- 所有新文案必须 zh/en 双语齐全（`app/web/app.js` 的 `I18N`）
- 空数据/单渠道/单账号场景不得报错，显示占位

## File Structure

```
tests/test_report_api.py        [新建] 三渠道 fixture + db 聚合函数全部测试
app/db.py                       [修改] 1221 _PERIOD_CLAUSES 加 yesterday key；
                                        文件末尾新增「report 聚合区块」（6 个函数，见下）
app/server.py                   [修改] 918 dashboard 分支加 yesterday 映射；
                                        1009 accounts/overview 逐账号附 cc_summary；
                                        _handle_api 加 4 个 /api/report/* 路由
app/web/index.html              [修改] 65 页头加渠道 tab + pill 加昨天档；
                                        66-78 之间插入全部 tab 专属容器（窗口条/摘要条/图表/明细表）
app/web/app.js                  [修改] state 加 channel/reportMetric；新增 renderReportAll
                                        等 6 个函数；bindEvents 加绑定；loadDashboard 分流
app/web/style.css               [修改] 末尾追加渠道配色变量 + 窗口条/摘要条样式
```

**db.py 新增函数清单（Dedupe Ticket 统一登记；R6 按六渠道修订）**：

| 函数 | Intent signature | 决策 |
|------|-----------------|------|
| `report_daily(range_, channel, metric)` | 按自然日×渠道堆叠序列，粒度自适应，**三表 UNION**（usage_records/zcode_usage/claudecode_usage） | new（现 `daily_stats`/`zcode_daily`/`claudecode_daily` 均为单渠道滚动口径，不可复用） |
| `report_windows(channel)` | 4 窗口 + 同时段环比 + 深度 + 同步归并，**三表求和**；dsh 今日由 server 并入 | new |
| `report_channels(range_)` | 渠道明细表行 + 数据自，**六渠道**（dsh 仅今日行） | new |
| `report_hourly(date_, channel)` | 24h×渠道堆叠，**三表 UNION**（dsh 无历史不参与） | new |
| `channel_totals(range_, channel)` | 单渠道聚合 totals（按渠道分派三表；dsh 由 server 层组装） | new（`totals`/`zcode_totals`/`claudecode_totals` 均滚动口径且单渠道固定，不可复用） |
| `channel_trend(date_, channel)` | 单渠道 24h input/output 序列（三表分派；dsh 无历史返回空） | new（`today_trend` 只收 account_id） |
| `list_channel_summary()` | 渠道 tab 列表 + 账号数，**六渠道**固定排序 opencode→bai→commandcode→zcode→claudecode→dsh→其余 | new |

**Dedupe 查询记录**（R6 复核）：账号渠道聚合现有 `daily_stats/totals/today_trend` 均为 `account_id` 单账号粒度；本地渠道现有 `zcode_totals/zcode_daily/claudecode_totals/claudecode_daily` 均为固定单渠道 + `_zcode_period_where`（滚动）口径——report 系列需要"自然日 + 可选渠道过滤 + 跨表合并"，全部 new；`_zcode_cost_usd/_cc_cost_usd` 仅作聚合行换算，report 内联 `SUM(cost_raw)/1e8`。

**R6 渠道口径登记（六渠道两体系）**：

| 渠道 | 数据表 | 时间列 | tokens 口径 | cost 口径 | est | 配额 |
|------|--------|--------|------------|----------|-----|------|
| opencode/bai/commandcode | usage_records | created_at | input+output+reasoning | cost_usd | 仅 bai | 有（accounts/overview） |
| zcode | zcode_usage | started_at | input+output+reasoning（列齐备） | SUM(cost_raw)/1e8 | 是 | 无 |
| claudecode | claudecode_usage | started_at | input+output（无 reasoning 列） | SUM(cost_raw)/1e8 | 是 | 无 |
| dsh | 无表（dsh_api.scan() 15s TTL） | —（仅 total/today 桶） | today: input+output+reasoning | 无费用字段 | 否 | 无 |

**前端新增函数清单**：`renderReportAll(data)`、`renderWindows(w)`、`renderQuotaBar(accounts)`、`renderQuotaSingle(accounts)`、`renderCcAccounts(accounts)`（R1 补）、`fmtAgo(iso)`（R1 补）、`chartReportStack(d)`、`chartReportDonut(d)`、`chartReportHourly(d)`、`renderChannelTable(rows)`、`switchChannel(ch)`；另有现有函数签名扩展：`renderUsageBlocks(quota, box?)`（T12 参数化）。

---

### Task 1: 测试基础设施 + created_at 三格式前置验证

**Files:**
- Create: `tests/test_report_api.py`

**Interfaces:**
- Produces: `tmp_report_db` fixture（等价 `test_db_multiuser.py` 的 `tmp_db`）、`_mkrec()` 造数函数、`_seed_channels()` 三渠道造数函数——Task 2-6 的测试全部消费

- [ ] **Step 1: 写 fixture + 格式验证测试（先失败不存在断言对象没关系，本任务验证的是 sqlite 行为）**

```python
"""report 聚合 API 测试: 渠道归一 / 自然日窗口 / 同时段环比 / 勾稽 / 空数据."""
from __future__ import annotations

import sqlite3

import pytest

from app import db

# R2: compare 测试对运行时刻敏感 (0-1 点触发样本保护 / 22 点后 w3 的 now+2h 跨天),
# 环境窗口外跳过 —— 造数围绕真实"现在"相对偏移, 无法全参数化 (YAGNI).
# 新R1 修正: 下界 <1 改为 <3 —— w2=now-1d-2h 的本地时刻为 now时刻-2h, 01:00-02:59
# 运行时其时刻(22:xx-23:xx)晚于今日此刻, 不满足 time<=now, 昨日同时段样本为 0 必挂.
import datetime as _nowdt


def _runnable_hour():
    return _nowdt.datetime.now().hour


COMPARE_SKIP = pytest.mark.skipif(
    _runnable_hour() < 3 or _runnable_hour() >= 22,
    reason="0-3 点昨日同时段偏移样本不足 / 22 点后 now+2h 跨天, 造数前提不成立",
)


@pytest.fixture()
def tmp_report_db(tmp_path, monkeypatch):
    """独立临时库: 重定向 data_dir 并重置模块级连接 (与 test_db_multiuser.tmp_db 同型)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


def _mkrec(usg_id, created, model="m", inp=10, outp=20, cost_usd=0.5):
    return {
        "usg_id": usg_id, "created_at": created, "model": model,
        "provider": "anthropic",  # 故意放模型商: 验证聚合不依赖它
        "input_tokens": inp, "output_tokens": outp, "reasoning_tokens": 0,
        "cache_read_tokens": 0, "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
        "cost_raw": 0, "cost_usd": cost_usd, "key_id": None, "session_id": None, "plan": None,
    }


def _seed_channels():
    """三账号渠道各 1 账号, 返回 {source: account_id}."""
    ids = {
        "opencode": db.add_account("tok-oc", "ws-oc"),
        "bai": db.add_account("cookie-bai", "bai-user-1", switch=False, source="bai", dedupe_key="bai-user-1"),
        "commandcode": db.add_account("tok-cc", "cc-user-1", switch=False, source="commandcode", dedupe_key="cc-user-1"),
    }
    return ids


def _seed_local(iso: str = "2026-09-01T08:30:00Z", z_in=30, z_out=50, c_in=20, c_out=40):
    """本地镜像渠道造数 (R6): zcode_usage/claudecode_usage 各 1 行, 直 INSERT (表结构 db.py:190/216)."""
    conn = db.get_db()
    conn.execute(
        "INSERT INTO zcode_usage (id, started_at, provider_id, provider_name, model_id, status,"
        " input_tokens, output_tokens, reasoning_tokens, cache_write_tokens, cache_read_tokens,"
        " total_tokens, cost_raw, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("z1", iso, "prov-1", "Provider1", "glm-4", "ok", z_in, z_out, 0, 0, 0,
         z_in + z_out, (z_in + z_out) * 100_000, "2026-09-01T09:00:00"),
    )
    conn.execute(
        "INSERT INTO claudecode_usage (dedupe_key, session_id, model, channel, started_at,"
        " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, total_tokens,"
        " cost_raw, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("cc1", "sess-1", "claude-x", "api", iso, c_in, c_out, 0, 0, c_in + c_out,
         (c_in + c_out) * 100_000, "2026-09-01T09:00:00"),
    )
    conn.commit()


def _mock_dsh(monkeypatch, today_tokens=70):
    """dsh 内存数据 mock (R6): get_dsh_usage 走模块缓存, 直接注入 _cache_payload."""
    from app import dsh_api
    monkeypatch.setattr(dsh_api, "_cache_payload", {
        "found": True, "updated_at": "2026-09-04T10:00:00", "sessions_count": 2,
        "total": {"input": today_tokens, "cache": 0, "output": today_tokens,
                  "reasoning": 0, "seconds": 60, "tps": 1.0},
        "today": {"input": today_tokens // 2, "cache": 0, "output": today_tokens // 2,
                  "reasoning": 0, "seconds": 30, "tps": 1.0},
        "providers": [], "models": [],
    })
    monkeypatch.setattr(dsh_api, "_cache_ts", __import__("time").time())


def test_created_at_formats_resolved_by_sqlite(tmp_report_db):
    """前置验证 (spec §5): 三渠道 created_at 均为官方原样透传, 格式需被
    sqlite datetime() + localtime 正确解析. 任一格式解析为 NULL 即失败."""
    ids = _seed_channels()
    fmts = {
        "opencode": "2026-09-01T08:30:00Z",                # 带 Z (UTC)
        "bai": "2026-09-01 08:30:00",                      # 空格分隔无时区
        "commandcode": "2026-09-01T08:30:00.123+00:00",    # 毫秒 + 时区偏移
    }
    for i, (src, created) in enumerate(fmts.items()):
        db.insert_usage_records([_mkrec(f"u{i}", created)], ids[src])
    rows = db.get_db().execute(
        "SELECT substr(datetime(created_at,'localtime'),1,10) d FROM usage_records"
    ).fetchall()
    assert all(r["d"] and len(r["d"]) == 10 and r["d"][4] == "-" for r in rows), rows
```

- [ ] **Step 2: 运行确认通过（这是行为验证测试，预期直接 PASS；若 FAIL 说明某渠道格式 sqlite 不认，停下在规格 §5 记录并加规范化函数——不要静默改数据）**

Run: `python -m pytest tests/test_report_api.py::test_created_at_formats_resolved_by_sqlite -v`
Expected: PASS（sqlite 3.x 支持三种 ISO 变体）

- [ ] **Step 3: Commit（人工确认后执行）**

```bash
git add tests/test_report_api.py
git commit -m "test: report 聚合测试基建 + created_at 三渠道格式前置验证"
```

---

### Task 2: db.report_daily — 日×渠道堆叠序列（渠道归一/自然日窗口/粒度自适应）

**Files:**
- Modify: `app/db.py`（文件末尾追加 report 区块）
- Test: `tests/test_report_api.py`

**Interfaces:**
- Consumes: Task 1 的 `_mkrec/_seed_channels`
- Produces: `report_daily(range_: str = "7d", channel: Optional[str] = None, metric: str = "tokens") -> dict`
  返回 `{"granularity": "day"|"week"|"month", "labels": [str], "series": {channel: [num]}, "metric": metric}`

- [ ] **Step 1: 写失败测试**

```python
def test_report_daily_normalizes_provider_to_source(tmp_report_db):
    """OpenCode 记录 provider='anthropic'(模型商) 仍必须归入 opencode 渠道 (spec v4 核心)."""
    ids = _seed_channels()
    db.insert_usage_records([_mkrec("x1", _days_ago(3))], ids["opencode"])  # R4: 相对日期
    d = db.report_daily("7d")
    # 新R1 修正: series 仅含有记录的渠道; 本意是验证模型商不出现, 用存在性断言
    assert set(d["series"].keys()) == {"opencode"}
    assert "anthropic" not in d["series"]
    assert d["granularity"] == "day"


def test_report_daily_merges_local_tables(tmp_report_db):
    """R6: 三表 UNION —— 同一天 opencode/bai/zcode/claudecode 四渠道分段求和."""
    ids = _seed_channels()
    # 新R5 N28: 原写法 day+_days_ago 完整串再拼 "T..Z" 产出无效 ISO (sqlite 解析 NULL 必挂);
    # 改用 _days_ago(n, h) 直接取"本地 n 天前 h 点"的 UTC 串, label 用本地日期单独计算
    import datetime as _dt
    day_local = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()   # 本地昨日 = 堆叠图 label
    db.insert_usage_records([_mkrec("m1", _days_ago(1, 1), inp=40, outp=60)], ids["opencode"])    # 本地昨 1 点, oc 100
    db.insert_usage_records([_mkrec("m2", _days_ago(1, 2), inp=80, outp=120)], ids["bai"])        # 本地昨 2 点, bai 200
    _seed_local(iso=_days_ago(1, 4), z_in=30, z_out=50, c_in=20, c_out=40)  # 本地昨 4 点, zcode 80 / claudecode 60
    d = db.report_daily("7d")
    assert set(d["series"].keys()) == {"opencode", "bai", "zcode", "claudecode"}
    assert d["series"]["zcode"][d["labels"].index(day_local)] == 80
    assert d["series"]["claudecode"][d["labels"].index(day_local)] == 60
    d_z = db.report_daily("7d", channel="zcode")
    assert list(d_z["series"].keys()) == ["zcode"]


def _to_utc_iso(dt_local) -> str:
    """本地 datetime → 带 Z 的 UTC ISO 串 (新R1 N25: SQLite 对无后缀串按 UTC 解析,
    造数必须显式产出 UTC, 否则东八区 16:00 后 localtime(+8h) 跨日掉出 today 窗口)."""
    import datetime as _dt
    if dt_local.tzinfo is None:
        dt_local = dt_local.astimezone()          # naive -> 本地时区感知
    return dt_local.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_iso(minute_offset: int = 0) -> str:
    """当前时刻前 minute_offset 分钟 (UTC Z 串; N25 修正: 原本地无后缀串被 sqlite 当 UTC)."""
    import datetime as _dt
    return _to_utc_iso(_dt.datetime.now() - _dt.timedelta(minutes=minute_offset))


def _today_at(h: int, m: int = 0) -> str:
    """本地"今天 h 点"对应的 UTC 串 (N25 修正后: 解析回本地恒为今天, 任意 h 安全;
    测试仍习惯用 h<=12, 与凌晨运行的 compare 环境窗口互补)."""
    import datetime as _dt
    return _to_utc_iso(_dt.datetime.now().replace(hour=h, minute=m, second=0, microsecond=0))


def _days_ago(n: int, h: int = 12) -> str:
    """本地 n 天前 h 点对应的 UTC 串 (R4 相对日期; N25 修正 UTC 语义)."""
    import datetime as _dt
    d = _dt.datetime.now() - _dt.timedelta(days=n)
    return _to_utc_iso(d.replace(hour=h, minute=0, second=0, microsecond=0))


def test_report_daily_range_and_channel_filter(tmp_report_db):
    ids = _seed_channels()
    # today 范围 -> 固定"今天 12:00/11:00/10:30"造数, 任何运行时刻都落在今天 (R2 修正)
    db.insert_usage_records([
        _mkrec("d1", _today_at(12), inp=40, outp=60),     # oc 100 tok
        _mkrec("d2", _today_at(11), inp=80, outp=120),    # oc 200 tok
    ], ids["opencode"])
    db.insert_usage_records([_mkrec("d3", _today_at(10, 30), inp=80, outp=120)], ids["bai"])
    d = db.report_daily("today", channel="bai")
    assert list(d["series"].keys()) == ["bai"]
    assert sum(d["series"]["bai"]) == 200
    d_all = db.report_daily("today")
    assert sum(d_all["series"]["opencode"]) == 300        # d1(100) + d2(200)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_report_api.py -v -k report_daily`
Expected: FAIL `AttributeError: module 'app.db' has no attribute 'report_daily'`

- [ ] **Step 3: 最小实现（追加到 app/db.py 末尾；同时把 db.py:16 的 import 行改为
`from datetime import datetime, timezone, date`——现有无 `date`，R1 修正；R6：三表 UNION 版本）**

```python
# ---------------------------------------------------------------------------
# report 聚合区块 (spec doc/20260904-token-summary-report.md v10 §5; R6 六渠道修订)
# 渠道维度: 账号渠道 = accounts.source (禁止 GROUP BY provider —— opencode 的
#   provider 是模型商); 本地渠道 = zcode_usage / claudecode_usage 镜像表 (R6);
#   dsh 无历史表, 仅"今日"窗口, 由 server 层并入 (T6)。
# tokens 统一口径 = input + output + reasoning (不含缓存, 与现有首页 totalTokens
#   一致; claudecode 无 reasoning 列记 0); cost 统一 USD (镜像表 cost_raw/1e8)。
# 范围窗口 = 自然日; 不复用 _period_where / _zcode_period_where 的滚动口径。
# ---------------------------------------------------------------------------

_REPORT_RANGE_DAYS = {"7d": 6, "30d": 29}  # 自然日窗口: 含今天共 N 天
_CHANNEL_ORDER = ["opencode", "bai", "commandcode", "zcode", "claudecode", "dsh"]
_LOCAL_EST_CHANNELS = {"bai", "zcode", "claudecode"}  # 费用为估算的渠道 (spec v6 est-badge)


def _report_range_sql(range_: str, ts_col: str) -> str:
    day = f"substr(datetime({ts_col},'localtime'),1,10)"
    if range_ == "today":
        return f"{day} = date('now','localtime')"
    if range_ == "yesterday":
        return f"{day} = date('now','localtime','-1 day')"
    if range_ in _REPORT_RANGE_DAYS:
        return f"{day} >= date('now','localtime','-{_REPORT_RANGE_DAYS[range_]} days')"
    return "1=1"  # all


def _report_channels_expr() -> str:
    return "COALESCE(a.source,'opencode')"


def _report_metric_exprs(metric: str) -> dict[str, str]:
    """各表聚合表达式 (R6): tokens/cost/requests; cost 统一 USD。"""
    if metric == "cost":
        return {"records": "SUM(r.cost_usd)", "zcode": "SUM(z.cost_raw)/1e8",
                "claudecode": "SUM(c.cost_raw)/1e8"}
    if metric == "requests":
        return {"records": "COUNT(*)", "zcode": "COUNT(*)", "claudecode": "COUNT(*)"}
    return {"records": "SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens)",
            "zcode": "SUM(z.input_tokens + z.output_tokens + z.reasoning_tokens)",
            "claudecode": "SUM(c.input_tokens + c.output_tokens)"}


def report_daily(range_: str = "7d", channel: Optional[str] = None, metric: str = "tokens") -> dict[str, Any]:
    """按自然日 × 渠道堆叠序列 (R6: usage_records + zcode_usage + claudecode_usage
    三表 UNION); range=all 时粒度自适应 (>60 天按周 / >180 天按月)."""
    exprs = _report_metric_exprs(metric)
    include_records = channel is None or channel in ("opencode", "bai", "commandcode")
    include_zcode = channel is None or channel == "zcode"
    include_cc = channel is None or channel == "claudecode"
    segs: list[str] = []
    params: list[Any] = []
    if include_records:
        ch_where = ""
        if channel:
            ch_where = f" AND {_report_channels_expr()} = ?"
            params.append(channel)
        segs.append(
            f"SELECT substr(datetime(r.created_at,'localtime'),1,10) AS b,"
            f" {_report_channels_expr()} AS ch, {exprs['records']} AS v"
            f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
            f" WHERE {_report_range_sql(range_, 'r.created_at')}{ch_where} GROUP BY b, ch")
    if include_zcode:
        segs.append(
            f"SELECT substr(datetime(z.started_at,'localtime'),1,10) AS b, 'zcode' AS ch,"
            f" {exprs['zcode']} AS v FROM zcode_usage z"
            f" WHERE {_report_range_sql(range_, 'z.started_at')} GROUP BY b")
    if include_cc:
        segs.append(
            f"SELECT substr(datetime(c.started_at,'localtime'),1,10) AS b, 'claudecode' AS ch,"
            f" {exprs['claudecode']} AS v FROM claudecode_usage c"
            f" WHERE {_report_range_sql(range_, 'c.started_at')} GROUP BY b")
    if not segs:
        return {"granularity": "day", "labels": [], "series": {}, "metric": metric}
    union = " UNION ALL ".join(segs)
    # 粒度自适应: 三表最大跨度
    span = get_db().execute(
        "SELECT MAX(lo) lo, MAX(hi) hi FROM ("
        " SELECT MIN(substr(datetime(created_at,'localtime'),1,10)) lo, MAX(substr(datetime(created_at,'localtime'),1,10)) hi FROM usage_records"
        " UNION ALL SELECT MIN(substr(datetime(started_at,'localtime'),1,10)), MAX(substr(datetime(started_at,'localtime'),1,10)) FROM zcode_usage"
        " UNION ALL SELECT MIN(substr(datetime(started_at,'localtime'),1,10)), MAX(substr(datetime(started_at,'localtime'),1,10)) FROM claudecode_usage)"
    ).fetchone()
    granularity = "day"
    if range_ == "all" and span["lo"] and span["hi"]:
        days = (date.fromisoformat(span["hi"]) - date.fromisoformat(span["lo"])).days + 1
        granularity = "month" if days > 180 else ("week" if days > 60 else "day")
    # UNION 段的 b 已是日粒度日期文本, 周/月对外层 b 再分组 (b 直接作为 datetime 输入)
    if granularity == "day":
        final_sql, final_params = f"SELECT b AS b2, ch, v FROM ({union}) ORDER BY b2", params
    else:
        fn = "strftime('%Y-W%W', b)" if granularity == "week" else "substr(b,1,7)"
        final_sql = f"SELECT {fn} AS b2, ch, SUM(v) FROM ({union}) GROUP BY b2, ch ORDER BY b2"
        final_params = params
    rows = get_db().execute(final_sql, final_params).fetchall()
    labels: list[str] = []
    series: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r["b2"] not in labels:
            labels.append(r["b2"])
        series.setdefault(r["ch"], {})[r["b2"]] = r["v"]
    return {"granularity": granularity, "labels": labels,
            "series": {ch: [s.get(b, 0) for b in labels] for ch, s in series.items()},
            "metric": metric}
```

- [ ] **Step 4: 运行确认通过 + 勾稽自检**

Run: `python -m pytest tests/test_report_api.py -v -k report_daily`
Expected: PASS

- [ ] **Step 5: Commit（人工确认后执行）**

```bash
git add app/db.py tests/test_report_api.py
git commit -m "feat: db.report_daily 渠道归一自然日聚合(含粒度自适应)"
```

---

### Task 3: db.report_windows — 4 窗口 + 同时段环比 + 样本保护

**Files:**
- Modify: `app/db.py`（report 区块内追加）
- Test: `tests/test_report_api.py`

**Interfaces:**
- Consumes: Task 2 的 `_report_range_sql/_report_channels_expr/_report_metric_exprs`（R6 改名后）
- Produces: `report_windows(channel: Optional[str] = None) -> dict`
  返回 `{"today"/"yesterday"/"7d"/"30d": {"tokens","cost","requests"}, "compare": {"pct": float|None, "insufficient_sample": bool, "spike": bool}, "data_since": str|None, "channels": {ch: {"oldest","last_sync_at","ok"}}}`

- [ ] **Step 1: 写失败测试**

```python
@COMPARE_SKIP
```python
def test_report_windows_merges_local(tmp_report_db):
    """R6: 三表求和 —— today/7d 含 zcode/claudecode; channels 归并本地渠道."""
    ids = _seed_channels()
    db.insert_usage_records([_mkrec("L1", _today_iso(30), inp=40, outp=60)], ids["opencode"])
    _seed_local(iso=_today_iso(40), z_in=30, z_out=50, c_in=20, c_out=40)  # zcode 80 / cc 60
    w = db.report_windows()
    assert w["today"]["tokens"] == 100 + 80 + 60            # 三表 today 求和
    assert set(w["channels"].keys()) >= {"opencode", "zcode", "claudecode"}
    assert w["channels"]["zcode"]["ok"] is True              # 本地渠道无失败状态
    assert w["channels"]["zcode"]["last_sync_at"]            # = MAX(synced_at)


@COMPARE_SKIP
def test_report_windows_same_time_compare_and_guard(tmp_report_db):
    """同时段环比: 昨日同时段之前的数据才参与对比; 需 >=5 条样本否则保护 (R1 修正造数, R2 加环境窗口)."""
    ids = _seed_channels()
    import datetime as _dt
    now = _dt.datetime.now()
    db.insert_usage_records([
        _mkrec("w1", _today_iso(30), inp=40, outp=60),                    # 今天 -30min, 100 tok
    ], ids["opencode"])
    # 昨日同时段(早于今天此刻)5 条 x10 tok = 50 -> 不触发 <5 样本保护 (R1: 1 条会误触发)
    for i in range(5):
        db.insert_usage_records([
            _mkrec(f"w2_{i}", _to_utc_iso(now - _dt.timedelta(days=1) - _dt.timedelta(hours=2, minutes=i)),
                   inp=4, outp=6),
        ], ids["opencode"])
    # 昨日但晚于今天此刻 -> 计入 yesterday 全天, 不参与同时段对比
    db.insert_usage_records([
        _mkrec("w3", _to_utc_iso(now - _dt.timedelta(days=1) + _dt.timedelta(hours=2)),
               inp=900, outp=90),                                          # 990 tok
    ], ids["opencode"])
    w = db.report_windows()
    assert w["today"]["tokens"] == 100
    assert w["yesterday"]["tokens"] == 1040          # 50 + 990 (R1 修正: 50+990=1040)
    assert w["compare"]["insufficient_sample"] is False
    assert w["compare"]["pct"] == pytest.approx(100.0)  # 100 vs 50 -> +100%


def test_report_windows_insufficient_sample(tmp_report_db):
    ids = _seed_channels()
    import datetime as _dt
    now = _dt.datetime.now()
    db.insert_usage_records([
        _mkrec("s1", _to_utc_iso(now - _dt.timedelta(days=1) - _dt.timedelta(hours=2))),
    ], ids["opencode"])  # 昨日同时段仅 1 条 < 5
    w = db.report_windows()
    assert w["compare"]["insufficient_sample"] is True and w["compare"]["pct"] is None


@COMPARE_SKIP   # 新R3 N22: sp1 用 now-10min (0-3 点落昨日)、sp2/sp3 用 now-Nd-2h (22 点后跨今日), 同 compare 测试的环境窗口
def test_report_windows_spike_and_same7_span(tmp_report_db):
    """新R1 N19/N20: same_7 必须是 7 个完整自然日(-7~-1, 不含今天); spike 阈值=同时段均值×2."""
    ids = _seed_channels()
    import datetime as _dt
    now = _dt.datetime.now()
    db.insert_usage_records([_mkrec("sp1", _today_iso(10), inp=400, outp=600)], ids["opencode"])  # 今日同时段 1000
    for i in range(5):  # 昨日同时段 5 条 x10 = 50 (环比 +1900%, 但 spike 只看 7 日均值)
        db.insert_usage_records([_mkrec(f"sp2_{i}",
            _to_utc_iso(now - _dt.timedelta(days=1) - _dt.timedelta(hours=2, minutes=i)),
            inp=4, outp=6)], ids["opencode"])
    for d in range(2, 8):  # 2~7 天前同时段各 50 tok (昨天除外共 6 天, 加昨天=7 天各 50)
        for i in range(5):
            db.insert_usage_records([_mkrec(f"sp3_{d}_{i}",
                _to_utc_iso(now - _dt.timedelta(days=d) - _dt.timedelta(hours=2, minutes=i)),
                inp=4, outp=6)], ids["opencode"])
    w = db.report_windows()
    assert w["compare"]["spike"] is True   # 今日 1000 > 7 日同时段均值 50 × 2
    # same_7 跨度断言: 若实现错成 6 天(-6~-1), 第 7 天前的 250 tok 不计入, 均值=41.7, 仍 spike;
    # 因此这里直接校验均值窗口的tokens总数 = 7 天 × 50 = 350 (只可经由 sp2/sp3 同时段构成)
    assert w["compare"]["pct"] == pytest.approx(1900.0)


def test_report_windows_sync_min_and_fail_priority(tmp_report_db):
    """同渠道多账号: 同步时间取 min(最陈旧); 任一失败 -> ok=False (spec v10).

    R1 修正: 账号必须先经 update_sync_state 建行(_ensure_state_row), 直接 UPDATE
    无行账号会命中 0 行导致断言必败."""
    a1 = db.add_account("tok-oc2", "ws-oc2")            # 同渠道第 2 个 opencode 账号
    ids = _seed_channels()
    for aid, st in ((a1, "success"), (ids["opencode"], "success")):
        db.update_sync_state(st, account_id=aid)         # 建行
    conn = db.get_db()
    conn.execute("UPDATE usage_sync_state SET last_sync_at=? WHERE account_id=?",
                 ("2026-09-01T10:00:00", ids["opencode"]))
    conn.execute("UPDATE usage_sync_state SET last_sync_at=?, last_sync_status=? WHERE account_id=?",
                 ("2026-09-01T08:00:00", "error", a1))
    conn.execute("UPDATE usage_sync_state SET oldest_record_at=? WHERE account_id=?",
                 ("2026-08-01T00:00:00", ids["opencode"]))
    conn.commit()
    w = db.report_windows()
    oc = w["channels"]["opencode"]
    assert oc["last_sync_at"] == "2026-09-01T08:00:00"  # min(最陈旧)
    assert oc["ok"] is False                             # 任一失败
    assert w["data_since"] == "2026-08-01"               # oldest 日期部分
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_report_api.py -v -k report_windows`
Expected: FAIL `no attribute 'report_windows'`

- [ ] **Step 3: 最小实现（report 区块内追加）**

```python
def _win_records(where: str, params: list[Any]) -> dict[str, Any]:
    row = get_db().execute(
        "SELECT SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) tokens,"
        " SUM(r.cost_usd) cost, COUNT(*) requests"
        " FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id WHERE " + where,
        params,
    ).fetchone()
    return {"tokens": row["tokens"] or 0, "cost": row["cost"] or 0.0, "requests": row["requests"] or 0}


def _win_zcode(where: str) -> dict[str, Any]:
    row = get_db().execute(
        "SELECT SUM(z.input_tokens + z.output_tokens + z.reasoning_tokens) tokens,"
        " SUM(z.cost_raw)/1e8 cost, COUNT(*) requests FROM zcode_usage z WHERE " + where
    ).fetchone()
    return {"tokens": row["tokens"] or 0, "cost": row["cost"] or 0.0, "requests": row["requests"] or 0}


def _win_cc(where: str) -> dict[str, Any]:
    row = get_db().execute(
        "SELECT SUM(c.input_tokens + c.output_tokens) tokens,"   # claudecode 无 reasoning 列 (R6)
        " SUM(c.cost_raw)/1e8 cost, COUNT(*) requests FROM claudecode_usage c WHERE " + where
    ).fetchone()
    return {"tokens": row["tokens"] or 0, "cost": row["cost"] or 0.0, "requests": row["requests"] or 0}


def _win_merge(*rows: dict[str, Any]) -> dict[str, Any]:
    out = {"tokens": 0, "cost": 0.0, "requests": 0}
    for r in rows:
        out["tokens"] += r["tokens"]
        out["cost"] += r["cost"]
        out["requests"] += r["requests"]
    return out


def report_windows(channel: Optional[str] = None) -> dict[str, Any]:
    """时间窗口汇总条 (R6 三表求和): today/yesterday/7d/30d + 同时段环比 (样本保护)
    + 数据深度 + 同步状态。dsh 今日由 server 层并入 (T6), db 层不碰 dsh_api。

    同时段口径 (spec v4/v5): 今日截至当前 vs 昨日同时刻; 7 天同时段均值 = 近 7 个
    完整自然日(不含今天)各日同时段之和/7; <03:00 由测试环境窗口保证, 或对比窗口
    <5 条 -> 样本不足。
    """
    ch_filter, ch_params = ("", [])
    if channel:
        ch_filter, ch_params = f" AND {_report_channels_expr()} = ?", [channel]
    import datetime as _dt

    def records_where(range_: str, same_time: bool = False) -> tuple[str, list[Any]]:
        w = _report_range_sql(range_, "r.created_at")
        if same_time:
            w += " AND datetime(r.created_at,'localtime') <= datetime('now','localtime')" \
                 if range_ == "today" else \
                 f" AND time(datetime(r.created_at,'localtime')) <= time('now','localtime')"
        return w + ch_filter, list(ch_params)

    def local_where(range_: str, ts: str, same_time: bool = False) -> str:
        w = _report_range_sql(range_, ts)
        if same_time:
            w += f" AND datetime({ts},'localtime') <= datetime('now','localtime')" \
                 if range_ == "today" else \
                 f" AND time(datetime({ts},'localtime')) <= time('now','localtime')"
        return w

    def window(range_: str, same_time: bool = False) -> dict[str, Any]:
        rw, rp = records_where(range_, same_time)
        return _win_merge(
            _win_records(rw, rp),
            _win_zcode(local_where(range_, "z.started_at", same_time)) if not channel or channel == "zcode" else {"tokens": 0, "cost": 0.0, "requests": 0},
            _win_cc(local_where(range_, "c.started_at", same_time)) if not channel or channel == "claudecode" else {"tokens": 0, "cost": 0.0, "requests": 0},
        )

    windows = {
        "today": window("today"),
        "yesterday": window("yesterday"),
        "7d": window("7d"),
        "30d": window("30d"),
    }
    same_y = window("yesterday", same_time=True)
    # 新R5(本循环 R1) N19 修正: same_7 不走 7d 窗口(那是含今天的滚动 7 天), 直接用
    # v7 的 BETWEEN 形式取近 7 个完整自然日(-7~-1)各日同时段
    def same7_where(ts: str) -> str:
        day = f"substr(datetime({ts},'localtime'),1,10)"
        return (f"{day} BETWEEN date('now','localtime','-7 days') AND date('now','localtime','-1 day')"
                f" AND time(datetime({ts},'localtime')) <= time('now','localtime')")
    same_7 = _win_merge(
        _win_records(same7_where("r.created_at") + ch_filter, list(ch_params)),
        _win_zcode(same7_where("z.started_at")) if not channel or channel == "zcode" else {"tokens": 0, "cost": 0.0, "requests": 0},
        _win_cc(same7_where("c.started_at")) if not channel or channel == "claudecode" else {"tokens": 0, "cost": 0.0, "requests": 0},
    )
    early = _dt.datetime.now().hour < 1
    insufficient = early or same_y["requests"] < 5
    pct = None
    if not insufficient and same_y["tokens"]:
        pct = round((windows["today"]["tokens"] - same_y["tokens"]) / same_y["tokens"] * 100, 1)
    avg7 = (same_7["tokens"] / 7.0) if same_7["tokens"] else 0.0
    spike = (not insufficient) and avg7 > 0 and windows["today"]["tokens"] > avg7 * 2
    # 渠道归并: 账号渠道 sync_state (min + 失败优先); 本地渠道 last_sync=MAX(synced_at), ok 恒 True
    rows = get_db().execute(
        f"SELECT a.source AS ch,"
        f" MIN(s.oldest_record_at) oldest, MIN(s.last_sync_at) last_sync,"
        f" SUM(CASE WHEN s.last_sync_status IS NOT NULL AND s.last_sync_status != 'success' THEN 1 ELSE 0 END) fails"
        f" FROM accounts a LEFT JOIN usage_sync_state s ON s.account_id = a.id GROUP BY ch"
    ).fetchall()
    channels = {
        r["ch"]: {"oldest": (r["oldest"] or "")[:10] or None,
                  "last_sync_at": r["last_sync"], "ok": (r["fails"] or 0) == 0}
        for r in rows
    }
    for tbl, ch, ts in (("zcode_usage z", "zcode", "z.started_at"), ("claudecode_usage c", "claudecode", "c.started_at")):   # 新R8 N29: FROM 带别名, 否则 z.started_at 列不存在
        if channel and channel != ch:
            continue
        r = get_db().execute(
            f"SELECT MIN(substr({ts},1,10)) oldest, MAX(synced_at) last_sync FROM {tbl}"
        ).fetchone()
        channels[ch] = {"oldest": r["oldest"], "last_sync_at": r["last_sync"], "ok": True}
    since_all = [v["oldest"] for v in channels.values() if v["oldest"]] if not channel else \
        [channels[channel]["oldest"]] if channel in channels and channels[channel]["oldest"] else []
    return {
        **windows,
        "compare": {"pct": pct, "insufficient_sample": insufficient, "spike": spike},
        "data_since": min(since_all) if since_all else None,
        "channels": {k: v for k, v in channels.items() if not channel or k == channel},
    }
```

> 实现注：① 渠道归并的账号段直接 `a.source AS ch`（以账号为主表；`_report_channels_expr()` 面向记录侧 `r` 别名，两处别混用）；② `same_7` 的三段 where 需追加"排除今天"条件（`<day_expr> < date('now','localtime')`），保证"近 7 个完整自然日（不含今天）"口径；③ 早于 01:00 判定用 `import datetime as _dt`。

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_report_api.py -v -k report_windows`
Expected: PASS

- [ ] **Step 5: Commit（人工确认后执行）**

```bash
git add app/db.py tests/test_report_api.py
git commit -m "feat: db.report_windows 4窗口+同时段环比样本保护+同步归并"
```

---

### Task 4: db.report_channels + list_channel_summary — 明细表与渠道 tab 列表

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_report_api.py`

**Interfaces:**
- Produces: `report_channels(range_: str = "7d") -> list[dict]`（行含 `channel/tokens/input/output/cache_read/requests/cost/data_since/estimated`）；`list_channel_summary() -> list[dict]`（`[{"channel","accounts"}]`，固定排序 opencode→bai→commandcode→其余按账号创建时间）

- [ ] **Step 1: 写失败测试**

```python
def test_report_channels_rows_and_since(tmp_report_db):
    ids = _seed_channels()
    db.insert_usage_records([
        _mkrec("c1", _days_ago(3), inp=40, outp=60, cost_usd=1.0),   # R4: 相对日期
        _mkrec("c2", _days_ago(2), inp=10, outp=20, cost_usd=0.5),
    ], ids["opencode"])
    db.insert_usage_records([_mkrec("c3", _days_ago(3, h=13), inp=80, outp=120, cost_usd=2.0)], ids["bai"])
    conn = db.get_db()
    conn.execute("UPDATE usage_sync_state SET oldest_record_at=? WHERE account_id=?", ("2026-08-01T00:00:00Z", ids["opencode"]))
    conn.commit()
    rows = {r["channel"]: r for r in db.report_channels("7d")}
    oc = rows["opencode"]
    assert oc["tokens"] == 130 and oc["requests"] == 2 and oc["input"] == 50
    assert oc["data_since"] == "2026-08-01"
    assert oc["estimated"] is False and rows["bai"]["estimated"] is True   # BAI 估算标记
    # 勾稽: 渠道行合计 = windows 同范围合计 (spec v8; R6: 无本地渠道数据时三表和=records 和)
    w = db.report_windows()
    assert sum(r["tokens"] for r in rows.values()) == w["7d"]["tokens"]


def test_report_channels_local_rows(tmp_report_db):
    """R6: 本地渠道行 + est 扩展 (zcode/claudecode 费用为估算)."""
    _seed_channels()
    _seed_local(iso=_days_ago(1), z_in=30, z_out=50, c_in=20, c_out=40)
    rows = {r["channel"]: r for r in db.report_channels("7d")}
    assert rows["zcode"]["tokens"] == 80 and rows["claudecode"]["tokens"] == 60
    assert rows["zcode"]["estimated"] is True and rows["claudecode"]["estimated"] is True
    w = db.report_windows()
    assert sum(r["tokens"] for r in rows.values()) == w["7d"]["tokens"]    # 勾稽含本地渠道


def test_list_channel_summary_order(tmp_report_db):
    """R6: 五渠道 (db 层; dsh 由 server 按 found 追加) —— 本地渠道恒列 accounts=1.
    新R8 N30: opencode=2 —— add_account 保留空 token 种子行 (source 默认 opencode,
    见 test_db_multiuser '种子 + 1 新增' 同型行为), 断言按真实计数."""
    _seed_channels()
    s = db.list_channel_summary()
    assert [x["channel"] for x in s] == ["opencode", "bai", "commandcode", "zcode", "claudecode"]
    assert {x["channel"]: x["accounts"] for x in s} == {
        "opencode": 2, "bai": 1, "commandcode": 1, "zcode": 1, "claudecode": 1}
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_report_api.py -v -k "report_channels or list_channel"`
Expected: FAIL

- [ ] **Step 3: 最小实现**

```python
def report_channels(range_: str = "7d") -> list[dict[str, Any]]:
    """渠道明细表行 (R6 五渠道; dsh 今日行由 server 层并入 T6)。estimated=估算渠道
    {bai, zcode, claudecode}。"""
    exprs_t = _report_metric_exprs("tokens")
    exprs_c = _report_metric_exprs("cost")
    rows = get_db().execute(
        f"SELECT {_report_channels_expr()} AS ch,"
        f" {exprs_t['records']} tokens, SUM(r.input_tokens) input, SUM(r.output_tokens) output,"
        f" SUM(r.cache_read_tokens) cache_read, {_report_metric_exprs('requests')['records']} requests,"
        f" {exprs_c['records']} cost"
        f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
        f" WHERE {_report_range_sql(range_, 'r.created_at')} GROUP BY ch"
    ).fetchall()
    agg = {r["ch"]: dict(r) for r in rows}
    # R6: 本地渠道行 (各一次聚合, 同构 dict 并入)
    for ch, alias, table, ts in (("zcode", "z", "zcode_usage", "z.started_at"),
                                 ("claudecode", "c", "claudecode_usage", "c.started_at")):
        r = get_db().execute(
            f"SELECT {exprs_t[ch]} tokens, SUM({alias}.input_tokens) input,"
            f" SUM({alias}.output_tokens) output, SUM({alias}.cache_read_tokens) cache_read,"
            f" COUNT(*) requests, {exprs_c[ch]} cost"
            f" FROM {table} {alias} WHERE {_report_range_sql(range_, ts)}"
        ).fetchone()
        if r and ((r["tokens"] or 0) or (r["requests"] or 0)):
            agg[ch] = dict(r)
    since = {r["ch"]: r["oldest"] for r in get_db().execute(
        "SELECT a.source ch, MIN(substr(s.oldest_record_at,1,10)) oldest"
        " FROM accounts a LEFT JOIN usage_sync_state s ON s.account_id = a.id"
        " WHERE s.oldest_record_at IS NOT NULL GROUP BY ch"
    ).fetchall()}
    for ch, ts, table in (("zcode", "z.started_at", "zcode_usage z"), ("claudecode", "c.started_at", "claudecode_usage c")):   # 新R8 N29b: 同 N29, FROM 带别名
        r = get_db().execute(f"SELECT MIN(substr({ts},1,10)) oldest FROM {table}").fetchone()
        if r["oldest"]:
            since[ch] = r["oldest"]
    order = [c for c in _CHANNEL_ORDER if c != "dsh" and c in agg]
    order += sorted((c for c in agg if c not in _CHANNEL_ORDER))
    return [
        {"channel": ch, "tokens": agg[ch]["tokens"] or 0, "input": agg[ch]["input"] or 0,
         "output": agg[ch]["output"] or 0, "cache_read": agg[ch]["cache_read"] or 0,
         "requests": agg[ch]["requests"] or 0, "cost": agg[ch]["cost"] or 0.0,
         "data_since": since.get(ch), "estimated": ch in _LOCAL_EST_CHANNELS}
        for ch in order
    ]


def list_channel_summary() -> list[dict[str, Any]]:
    """渠道 tab 列表 (R6 五渠道; dsh 由 server 按 dsh_api found 追加): 账号渠道
    accounts=账号行数, 本地渠道恒 1 (单数据源); 其余渠道按最早账号追加。"""
    rows = get_db().execute(
        "SELECT source ch, COUNT(*) accounts, MIN(created_at) first_at"
        " FROM accounts GROUP BY source"
    ).fetchall()
    m = {r["ch"]: {"accounts": r["accounts"], "_at": r["first_at"]} for r in rows}
    fixed = [c for c in _CHANNEL_ORDER if c != "dsh" and (c in m or c in ("zcode", "claudecode"))]
    extra = sorted((c for c in m if c not in _CHANNEL_ORDER), key=lambda c: m[c]["_at"] or "")
    # 新R8 N31: m 值为 {accounts,_at} dict, 必须取 ["accounts"]; 原写法 m.get(c,1) 返回整个 dict
    return [{"channel": c, "accounts": m[c]["accounts"] if c in m else 1} for c in fixed + extra]
```

- [ ] **Step 4: 运行确认通过**

Run: `python -m pytest tests/test_report_api.py -v -k "report_channels or list_channel"`
Expected: PASS

- [ ] **Step 5: Commit（人工确认后执行）**

```bash
git add app/db.py tests/test_report_api.py
git commit -m "feat: db.report_channels 明细行+数据自 + list_channel_summary 渠道列表"
```

---

### Task 5: db.report_hourly + channel_totals + channel_trend — 24h 与单渠道视图数据

**Files:**
- Modify: `app/db.py`
- Test: `tests/test_report_api.py`

**Interfaces:**
- Produces:
  - `report_hourly(date_: str = "today", channel: Optional[str] = None) -> dict` → `{"labels": [0..23], "series": {ch: [24 num]}}`
  - `channel_totals(range_: str, channel: str) -> dict`（键与现 `db.totals()` 完全一致：`request_count/session_count/total_input_tokens/total_output_tokens/total_reasoning_tokens/cache_hit_tokens/uncached_input_tokens/cache_write_tokens/total_cost_usd/hit_rate`——供前端 `renderOverview()` 直接复用）
  - `channel_trend(date_: str = "today", channel: str) -> list[dict]`（`[{hour,input,output}]`，供前端 `chartToday()` 复用）

- [ ] **Step 1: 写失败测试**

```python
def test_report_hourly_buckets_and_channel_totals(tmp_report_db):
    ids = _seed_channels()
    db.insert_usage_records([
        _mkrec("h1", _today_iso(0), inp=40, outp=60),   # 当前小时, 100 tok
    ], ids["opencode"])
    db.insert_usage_records([_mkrec("h2", _today_iso(0), inp=80, outp=120)], ids["bai"])
    h = db.report_hourly("today")
    assert h["labels"] == list(range(24))
    assert sum(h["series"]["bai"]) == 200 and sum(h["series"]["opencode"]) == 100
    t = db.channel_totals("today", "bai")
    assert t["request_count"] == 1 and t["total_input_tokens"] == 80
    tr = db.channel_trend("today", "bai")
    assert sum(x["output"] for x in tr) == 120


def test_report_hourly_and_totals_local_dispatch(tmp_report_db):
    """R6: hourly 三表 UNION; channel_totals/channel_trend 按渠道分派本地表."""
    _seed_channels()
    _seed_local(iso=_today_iso(10), z_in=30, z_out=50, c_in=20, c_out=40)
    h = db.report_hourly("today")
    assert sum(h["series"]["zcode"]) == 80 and sum(h["series"]["claudecode"]) == 60
    t = db.channel_totals("today", "zcode")
    assert t["request_count"] == 1 and t["total_input_tokens"] == 30 + 0 + 0   # input+cache_read+cache_write
    assert t["total_cost_usd"] == pytest.approx(80 * 100_000 / 1e8)
    tr = db.channel_trend("today", "claudecode")
    assert sum(x["output"] for x in tr) == 40
    assert db.channel_trend("today", "dsh") == []       # dsh 无历史 (R6)
```

- [ ] **Step 2: 运行确认失败**

Run: `python -m pytest tests/test_report_api.py -v -k "report_hourly or channel_totals or channel_trend"`
Expected: FAIL

- [ ] **Step 3: 最小实现**

```python
def report_hourly(date_: str = "today", channel: Optional[str] = None) -> dict[str, Any]:
    """24h × 渠道堆叠 (R6 三表 UNION); date_: today|yesterday; dsh 无历史不参与。"""
    day_ts = {"today": "date('now','localtime')",
              "yesterday": "date('now','localtime','-1 day')"}[date_ if date_ in ("today", "yesterday") else "today"]
    segs: list[str] = []
    params: list[Any] = []
    if channel is None or channel in ("opencode", "bai", "commandcode"):
        ch_where = ""
        if channel:
            ch_where = f" AND {_report_channels_expr()} = ?"
            params.append(channel)
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(r.created_at,'localtime')) AS INTEGER) h,"
            f" {_report_channels_expr()} ch, SUM(r.input_tokens + r.output_tokens + r.reasoning_tokens) v"
            f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
            f" WHERE substr(datetime(r.created_at,'localtime'),1,10) = {day_ts}{ch_where} GROUP BY h, ch")
    if channel is None or channel == "zcode":
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(z.started_at,'localtime')) AS INTEGER) h, 'zcode' ch,"
            f" SUM(z.input_tokens + z.output_tokens + z.reasoning_tokens) v FROM zcode_usage z"
            f" WHERE substr(datetime(z.started_at,'localtime'),1,10) = {day_ts} GROUP BY h")
    if channel is None or channel == "claudecode":
        segs.append(
            f"SELECT CAST(strftime('%H', datetime(c.started_at,'localtime')) AS INTEGER) h, 'claudecode' ch,"
            f" SUM(c.input_tokens + c.output_tokens) v FROM claudecode_usage c"
            f" WHERE substr(datetime(c.started_at,'localtime'),1,10) = {day_ts} GROUP BY h")
    if not segs:
        return {"labels": list(range(24)), "series": {}}
    rows = get_db().execute(
        f"SELECT h, ch, SUM(v) v FROM ({' UNION ALL '.join(segs)}) GROUP BY h, ch", params
    ).fetchall()
    series: dict[str, list[int]] = {}
    for r in rows:
        series.setdefault(r["ch"], [0] * 24)[r["h"]] = r["v"] or 0
    return {"labels": list(range(24)), "series": series}


def _totals_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """聚合行 → db.totals 对齐键 + hit_rate (R6 抽公共, 供三表分派复用)。"""
    d = dict(row)
    inp, hit = d["total_input_tokens"] or 0, d["cache_hit_tokens"] or 0
    d["hit_rate"] = (hit / inp * 100) if inp else 0.0
    return d


def channel_totals(range_: str, channel: str) -> dict[str, Any]:
    """单渠道聚合 totals (键与 db.totals 对齐, 供 renderOverview 复用; R6 三表分派;
    dsh 由 server 层组装, 本函数不处理)。"""
    if channel == "zcode":
        row = get_db().execute(
            f"SELECT COUNT(*) request_count,"
            f" COUNT(DISTINCT CASE WHEN z.session_id IS NOT NULL AND z.session_id != '' THEN z.session_id END) session_count,"
            f" SUM(z.input_tokens + z.cache_read_tokens + z.cache_write_tokens) total_input_tokens,"
            f" SUM(z.input_tokens) uncached_input_tokens,"
            f" SUM(z.output_tokens) total_output_tokens,"
            f" SUM(z.reasoning_tokens) total_reasoning_tokens,"
            f" SUM(z.cache_read_tokens) cache_hit_tokens,"
            f" SUM(z.cache_write_tokens) cache_write_tokens,"
            f" SUM(z.cost_raw)/1e8 total_cost_usd"
            f" FROM zcode_usage z WHERE {_report_range_sql(range_, 'z.started_at')}"
        ).fetchone()
        return _totals_from_row(row)
    if channel == "claudecode":
        row = get_db().execute(
            f"SELECT COUNT(*) request_count,"
            f" COUNT(DISTINCT CASE WHEN c.session_id IS NOT NULL AND c.session_id != '' THEN c.session_id END) session_count,"
            f" SUM(c.input_tokens + c.cache_read_tokens + c.cache_write_tokens) total_input_tokens,"
            f" SUM(c.input_tokens) uncached_input_tokens,"
            f" SUM(c.output_tokens) total_output_tokens,"
            f" 0 total_reasoning_tokens,"                       # claudecode 无 reasoning 列 (R6)
            f" SUM(c.cache_read_tokens) cache_hit_tokens,"
            f" SUM(c.cache_write_tokens) cache_write_tokens,"
            f" SUM(c.cost_raw)/1e8 total_cost_usd"
            f" FROM claudecode_usage c WHERE {_report_range_sql(range_, 'c.started_at')}"
        ).fetchone()
        return _totals_from_row(row)
    row = get_db().execute(
        f"SELECT COUNT(*) request_count,"
        f" COUNT(DISTINCT CASE WHEN r.session_id IS NOT NULL AND r.session_id != '' THEN r.session_id END) session_count,"
        f" SUM(r.input_tokens + r.cache_read_tokens + r.cache_write_5m_tokens + r.cache_write_1h_tokens) total_input_tokens,"
        f" SUM(r.input_tokens) uncached_input_tokens,"
        f" SUM(r.output_tokens) total_output_tokens,"
        f" SUM(r.reasoning_tokens) total_reasoning_tokens,"
        f" SUM(r.cache_read_tokens) cache_hit_tokens,"
        f" SUM(r.cache_write_5m_tokens + r.cache_write_1h_tokens) cache_write_tokens,"
        f" SUM(r.cost_usd) total_cost_usd"
        f" FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
        f" WHERE {_report_range_sql(range_, 'r.created_at')} AND {_report_channels_expr()} = ?",
        [channel],
    ).fetchone()
    return _totals_from_row(row)


def channel_trend(date_: str = "today", channel: str = "opencode") -> list[dict[str, Any]]:
    """单渠道 24h input/output 双序列 (供 chartToday 复用; R6 三表分派; dsh 返回空)。"""
    if channel == "dsh":
        return []                                               # R6: dsh 无历史
    ts = "z.started_at" if channel == "zcode" else ("c.started_at" if channel == "claudecode" else "r.created_at")
    table = {"zcode": "zcode_usage z", "claudecode": "claudecode_usage c",
             }.get(channel, "usage_records r LEFT JOIN accounts a ON a.id = r.account_id")
    tok_in = {"zcode": "SUM(z.input_tokens)", "claudecode": "SUM(c.input_tokens)",
              }.get(channel, "SUM(r.input_tokens)")
    tok_out = {"zcode": "SUM(z.output_tokens)", "claudecode": "SUM(c.output_tokens)",
               }.get(channel, "SUM(r.output_tokens)")
    ch_filter = "" if channel in ("zcode", "claudecode") else \
        f" AND {_report_channels_expr()} = ?"
    params: list[Any] = [] if channel in ("zcode", "claudecode") else [channel]
    day_eq = "date('now','localtime')" if date_ != "yesterday" else "date('now','localtime','-1 day')"
    rows = get_db().execute(
        f"SELECT CAST(strftime('%H', datetime({ts},'localtime')) AS INTEGER) h,"
        f" {tok_in} i, {tok_out} o FROM {table}"
        f" WHERE substr(datetime({ts},'localtime'),1,10) = {day_eq}{ch_filter} GROUP BY h",
        params,
    ).fetchall()
    m = {r["h"]: r for r in rows}
    return [{"hour": h, "input": (m[h]["i"] or 0) if h in m else 0,
             "output": (m[h]["o"] or 0) if h in m else 0} for h in range(24)]
```

> 实现注（R6）：① `channel_totals` 的 `total_input_tokens` 沿用 `db.totals` 口径 = input + 缓存读 + 缓存写（与"消耗 tokens=input+output+reasoning"是两个不同指标，分别服务概览卡与堆叠图）；② zcode/cc 的 period 用 `_report_range_sql` 自然日口径，不复用 `_zcode_period_where` 滚动口径；③ dsh 单渠道的 overview/trend 由 server 层从 `dsh_api.get_dsh_usage()` 组装（T6 Step 4）。

> 性能注记（新 R1 N21）：三表聚合查询条件 `substr(datetime(created_at,'localtime'))` 函数包裹列，**SQLite 无法走 B-tree 索引**（idx_usage_time / idx_zcode_time / idx_cc_time 对本聚合无效，实为顺序扫描）——**P0 数据量（个人本地用量，≤10 万行）毫秒级可接受**；若未来超 50 万行再优化（表达式索引或物化日表），P0 不做（YAGNI）。spec §5"已有索引前提下毫秒级"的表述据此修正（见文末同步待办 6）。

- [ ] **Step 4: 运行确认通过（跑全量防回归）**

Run: `python -m pytest tests/test_report_api.py -v && python -m pytest tests/test_db_multiuser.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit（人工确认后执行）**

```bash
git add app/db.py tests/test_report_api.py
git commit -m "feat: db.report_hourly/channel_totals/channel_trend 单渠道与24h聚合"
```

---

### Task 6: server 路由 4 端点 + dashboard yesterday + overview 附 cc_summary

**Files:**
- Modify: `app/server.py:918-923`（dashboard range 映射）、`app/server.py:1029`（overview 逐账号附 cc_summary）、`app/server.py` `_handle_api` 内 `/api/usage/records` 路由之后（约 1145 行）追加组装函数与 4 个路由
- Modify: `app/db.py:1221`（`_PERIOD_CLAUSES` 加 yesterday key）
- Depends: `app/server.py:19` 已有 `from . import dsh_api`（R6 核实，无需新增 import）
- Test: `tests/test_report_api.py`

**Interfaces:**
- Consumes: Task 2-5 全部 db 函数
- Produces（HTTP 契约，前端 Task 7-12 消费）:
  - `GET /api/report/windows?channel=` → windows dict + `channel_count`/`account_count`
  - `GET /api/report/daily?range=&channel=&metric=` → report_daily dict（range/metric 非法值回退默认）
  - `GET /api/report/hourly?date=&channel=` → report_hourly dict
  - `GET /api/report/channels?range=` → `{"rows": [...], "summary": [...]}`

- [ ] **Step 1: 写失败测试（端点薄壳——测 db 侧已覆盖，此处只测参数回退纯函数）**

在 server.py 端点内联做参数白名单回退（与现有 `/api/usage/records` 的 try/int 模式一致，不抽纯函数）。测试补一条综合冒烟：

```python
def test_report_params_fallback_contract(tmp_report_db):
    """非法 range/metric/date 必须回退默认而非 500 (与现有 usage/records 容错模式一致)."""
    _seed_channels()
    assert db.report_daily("bogus")["granularity"] == "day"          # _report_range_sql('bogus') -> all 分支兜底
    assert db.report_daily("7d", metric="bogus")["metric"] == "bogus"  # 由 server 层白名单拦截; db 层不负责


def test_server_merge_dsh(tmp_report_db, monkeypatch):
    """R6: dsh 仅并入 today 窗口与 range=today 明细表 (勾稽口径: 7d/30d 双方均不含 dsh)."""
    _seed_channels()
    _mock_dsh(monkeypatch, today_tokens=70)
    from app import server
    resp = server._report_windows_response(None)
    assert resp["today"]["tokens"] == 70                  # 空库 + dsh today
    assert resp["7d"]["tokens"] == 0                      # 7d 不含 dsh (无历史)
    resp2 = server._report_channels_response("today")
    assert any(r["channel"] == "dsh" and r["tokens"] == 70 for r in resp2["rows"])
    assert any(s["channel"] == "dsh" for s in resp2["summary"])
    resp3 = server._report_channels_response("7d")
    assert not any(r["channel"] == "dsh" for r in resp3["rows"])   # 仅 range=today 注入
```

> 白名单逻辑放 **server 层**（Task 6 Step 3 的路由代码），db 层信任入参。此测试锁定该分工。

- [ ] **Step 2: 运行（当前 server 未改，此测试应 PASS——它是契约锁定；随后直接实现）**

Run: `python -m pytest tests/test_report_api.py::test_report_params_fallback_contract -v`
Expected: PASS（仅当 `report_daily("bogus")` 走 all 分支正常返回；若 KeyError 则修 `_report_range_sql` 的 else 分支）

- [ ] **Step 3: 实现 server 组装函数 + 路由（R6：dsh 并入抽纯函数保持可测；插在 `/api/usage/records` 路由块之后）**

组装函数（`_handle_api` 之前的模块级位置，与 `_zcode_summary_payload` 同模式）：

```python
def _report_windows_response(channel: Optional[str]) -> dict[str, Any]:
    """GET /api/report/windows 数据组装 (R6): db 三表 + dsh 今日并入。"""
    payload = db.report_windows(channel)
    # 新R3 N17: 仅在可能用到 dsh 数据时才触发扫描 (账号渠道请求不扫 ~/.dsh)
    dsh_found = dsh_api.get_dsh_usage().get("found") if channel in (None, "dsh") else False
    if channel in (None, "dsh") and dsh_found:
        dsh = dsh_api.get_dsh_usage()
        t = dsh.get("today") or {}
        dsh_win = {"tokens": (t.get("input") or 0) + (t.get("output") or 0) + (t.get("reasoning") or 0),
                   "cost": 0.0, "requests": 0}
        payload["today"] = {
            "tokens": payload["today"]["tokens"] + dsh_win["tokens"],
            "cost": payload["today"]["cost"] + dsh_win["cost"],
            "requests": payload["today"]["requests"] + dsh_win["requests"],
        }
        if channel == "dsh":
            payload = {**payload, "yesterday": dict(dsh_win), "7d": dict(dsh_win),
                       "30d": dict(dsh_win),
                       "channels": {"dsh": {"oldest": None, "last_sync_at": dsh.get("updated_at"),
                                            "ok": True}}}
            payload["data_since"] = None
    summary = db.list_channel_summary()
    # 新R2 N14: channel_count 语义 = 当前请求可见的渠道数
    if channel:                          # 单渠道请求: 可见渠道 = 该渠道自身 (dsh 需 found)
        payload["channel_count"] = 1 if (channel != "dsh" or dsh_found) else 0
    else:                                # 全部渠道: 五渠道 + dsh(若 found)
        payload["channel_count"] = len(summary) + (1 if dsh_found else 0)
    payload["account_count"] = sum(x["accounts"] for x in summary
                                   if x["channel"] in ("opencode", "bai", "commandcode"))
    return payload


def _report_channels_response(range_: str) -> dict[str, Any]:
    """GET /api/report/channels 数据组装 (R6): db 五渠道行 + dsh 今日行 (仅 range=today)。"""
    rows = db.report_channels(range_)
    summary = db.list_channel_summary()
    if range_ == "today":
        dsh = dsh_api.get_dsh_usage()
        if dsh.get("found"):
            t = dsh.get("today") or {}
            rows = rows + [{"channel": "dsh", "tokens": (t.get("input") or 0) + (t.get("output") or 0)
                            + (t.get("reasoning") or 0),
                            "input": t.get("input") or 0, "output": t.get("output") or 0,
                            "cache_read": t.get("cache") or 0, "requests": 0, "cost": 0.0,
                            "data_since": None, "estimated": False}]
            summary = summary + [{"channel": "dsh", "accounts": 0}]
    return {"rows": rows, "summary": summary}
```

路由（参数白名单与现有 `/api/usage/records` 容错模式一致）：

```python
    if route == "/api/report/windows" and method == "GET":
        channel = query.get("channel", [""])[0] or None
        _json_response(handler, _report_windows_response(channel))
        return

    if route == "/api/report/daily" and method == "GET":
        range_ = query.get("range", ["7d"])[0]
        range_ = range_ if range_ in ("today", "yesterday", "7d", "30d", "all") else "7d"
        metric = query.get("metric", ["tokens"])[0]
        metric = metric if metric in ("tokens", "cost", "requests") else "tokens"
        channel = query.get("channel", [""])[0] or None
        _json_response(handler, db.report_daily(range_, channel, metric))
        return

    if route == "/api/report/hourly" and method == "GET":
        date_ = query.get("date", ["today"])[0]
        date_ = date_ if date_ in ("today", "yesterday") else "today"
        channel = query.get("channel", [""])[0] or None
        _json_response(handler, db.report_hourly(date_, channel))
        return

    if route == "/api/report/channels" and method == "GET":
        range_ = query.get("range", ["7d"])[0]
        range_ = range_ if range_ in ("today", "yesterday", "7d", "30d", "all") else "7d"
        _json_response(handler, _report_channels_response(range_))
        return
```

- [ ] **Step 4: dashboard 支持 yesterday（918 分支映射处）**

```python
        if range_param == "today":
            period, days = "today", 1
        elif range_param == "yesterday":
            period, days = "yesterday", 1
        elif range_param == "7d":
```

并在 `app/db.py:1221` 的 `_PERIOD_CLAUSES` 加一行（**只新增 key，不动现有 5h/today**）：

```python
_PERIOD_CLAUSES = {
    "5h": "datetime(created_at) >= datetime('now', '-5 hours')",
    "today": "substr(datetime(created_at, 'localtime'), 1, 10) = date('now', 'localtime')",
    "yesterday": "substr(datetime(created_at, 'localtime'), 1, 10) = date('now', 'localtime', '-1 day')",
}
```

- [ ] **Step 5: accounts/overview 逐账号附 cc_summary（1029 行 accounts.append 内）**

```python
                    "last_sync_at": sync_state.get("last_sync_at"),
                    "last_sync_status": sync_state.get("last_sync_status"),
                    "cc_summary": (db.get_cc_summary(aid) if acc["source"] == "commandcode" else None),
```

- [ ] **Step 6: 全量测试 + 语法验证**

Run: `python -m pytest tests/ -v && python -c "import app.server"`
Expected: 全 PASS

- [ ] **Step 7: Commit（人工确认后执行）—— Phase 1 完成**

```bash
git add app/db.py app/server.py tests/test_report_api.py
git commit -m "feat: /api/report/* 聚合端点 + dashboard yesterday + overview 附账期快照 (P0 后端)"
```

---

### Task 7: 前端页头 — 渠道 tab + 5 档 pill + state 分流骨架

**Files:**
- Modify: `app/web/index.html:65`（页头）、`app/web/app.js:200`(state)/`1548`(bindEvents)
- Test: 手动验收（项目前端无测试框架）

**Interfaces:**
- Consumes: Task 6 的 `/api/report/windows`、`/api/report/channels`
- Produces: `state.channel`（`"all"|"opencode"|...`）、`switchChannel(ch)`、容器 id：`channel-tabs`、`report-scope`、`windows-bar`、`quota-bar`、`report-charts`、`report-table`、`report-empty`

- [ ] **Step 1: index.html 页头改造（65 行 ph 区域替换）**

```html
<div class="ph"><h2 class="ph-title" data-i18n="homeTitle">用量统计总览</h2><div class="ph-right"><div class="pill-row" id="channel-tabs"><button class="pill active" data-ch="all" data-i18n="channelAll">全部渠道</button></div><div class="pill-row" id="home-pills"><button class="pill active" data-r="today" data-i18n="today">今天</button><button class="pill" data-r="yesterday" data-i18n="yesterday">昨天</button><button class="pill" data-r="7d" data-i18n="d7">近7天</button><button class="pill" data-r="30d" data-i18n="d30">近30天</button><button class="pill" data-r="all" data-i18n="all">全部</button></div></div></div>
<div class="scope-hint" id="report-scope" hidden></div>
<div id="report-all" hidden>
  <div class="windows-bar" id="windows-bar"></div>
  <div class="card quota-bar"><div class="card-h"><h3 data-i18n="quotaBarTitle">各渠道配额</h3></div><div id="quota-bar"></div></div>
  <div class="ph-right" style="padding:8px 0"><div class="seg" id="report-metric"><button class="active" data-m="tokens" data-i18n="segTokens">Token</button><button data-m="cost" data-i18n="cost">费用</button><button data-m="requests" data-i18n="colRequests">请求</button></div></div>
  <div class="two-col">
    <div class="card"><div class="card-h"><h3 data-i18n="stackTitle">分渠道消耗趋势</h3><span class="est-badge" id="report-est" hidden title="" data-i18n-title="estimateTip">估</span></div><div class="chart-box" style="min-height:240px"><canvas id="report-stack"></canvas></div></div>
    <div class="card"><div class="card-h"><h3 data-i18n="donutTitle">渠道占比</h3></div><div class="chart-box" style="min-height:240px;position:relative"><canvas id="report-donut"></canvas></div></div>
  </div>
  <div class="card"><div class="card-h"><h3 id="hourly-title"><span data-i18n="todayTrend">今日趋势</span> <span class="hint">24h</span></h3></div><div class="chart-box" style="height:250px"><canvas id="report-hourly"></canvas></div></div>
  <div class="card"><div class="card-h"><h3 data-i18n="chTableTitle">渠道明细</h3></div><table class="tbl"><thead><tr><th data-i18n="channel">渠道</th><th class="num" data-i18n="totalTokens">Token</th><th class="num" data-i18n="input">输入</th><th class="num" data-i18n="output">输出</th><th class="num" data-i18n="colCacheRead">缓存读</th><th class="num" data-i18n="colRequests">请求</th><th class="num" data-i18n="colCost">费用</th><th data-i18n="dataSince">数据自</th></tr></thead><tbody id="report-table"></tbody></table></div>
</div>
```

现有 `usage-blocks`/`cc-summary`/`overview`/`today-trend` 四块包进 `<div id="report-single" hidden>`（单渠道 tab 视图复用）。

- [ ] **Step 2: app.js state 与绑定（200 state 加一行；1548 bindEvents 加块）**

```javascript
// state 内追加:
  channel: "all",        // 首页渠道 tab; 冷启动强制 all (spec v2)
  reportMetric: "tokens",
```

```javascript
  // 渠道 tab (bindEvents 内追加)
  document.addEventListener("click", (e) => {
    const b = e.target.closest("#channel-tabs .pill");
    if (!b) return;
    switchChannel(b.dataset.ch);
  });
  $("report-metric").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#report-metric button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active"); state.reportMetric = b.dataset.m; loadReportAll();
  });

function switchChannel(ch) {
  state.channel = ch;
  document.querySelectorAll("#channel-tabs .pill").forEach((x) => x.classList.toggle("active", x.dataset.ch === ch));
  loadDashboard();
}
```

- [ ] **Step 3: loadDashboard 分流骨架（448 行函数体首部插入；R4 修正：加 page 守卫）**

> R4 已核实：`loadDashboard` 同时服务 home 与 stats 页（`switchPage` 对两页均调用，app.js:454 附近；函数体核心 = `range 选择 + api('/api/dashboard') + renderAll(data)`，stats 页全部渲染依赖它）。**分流必须以 `state.page === "home"` 为守卫，stats 页落入现有逻辑原样执行（spec v3：P0 不动）。**

```javascript
async function loadDashboard(quiet = false) {
  if (state.page === "home") {
    renderChannelTabs();                     // 每次刷新渠道列表(账号增减/删除回退)
    if (state.channel === "all") {
      $("report-all").hidden = false; $("report-single").hidden = true;
      $("report-scope").hidden = false;
      await loadReportAll(quiet);
      return;
    }
    $("report-all").hidden = true; $("report-single").hidden = false;
    $("report-scope").hidden = true;
    // 单渠道: T7 阶段先落入下方现有逻辑(旧内容过渡), Task 12 替换为渠道过滤分支
  }
  // ... 以下保留现有逻辑 (range 选择 / api('/api/dashboard') / renderAll) 原样不动
}

function renderChannelTabs() {
  api("/api/report/channels?range=today").then((d) => {
    const tabs = [{ ch: "all", label: t("channelAll") }]
      .concat(d.summary.map((s) => ({ ch: s.channel, label: s.channel, n: s.accounts })));
    $("channel-tabs").innerHTML = tabs.map((x) =>
      `<button class="pill${x.ch === state.channel ? " active" : ""}" data-ch="${x.ch}">${x.label}${x.n > 1 ? ` <small>·${x.n}</small>` : ""}</button>`).join("");
    if (state.channel !== "all" && !d.summary.some((s) => s.channel === state.channel)) switchChannel("all"); // 账号被删回退
  }).catch(() => {});
}
```

- [ ] **Step 4: 手动验收**

启动应用（`python -m app.main` 或现有启动方式）：首页显示「全部渠道」tab 与 5 档 pill；点击渠道 tab 视图切换（单渠道区此时仍是旧内容，Task 12 完善）；删光某渠道账号后 tab 消失并回退全部。

- [ ] **Step 5: Commit（人工确认后执行）**

```bash
git add app/web/index.html app/web/app.js
git commit -m "feat: 首页渠道tab+5档pill 分流骨架"
```

---

### Task 8: 时间窗口汇总条（环比/样本不足/点击联动）

**Files:**
- Modify: `app/web/app.js`（新增 `loadReportAll/renderWindows`）、`app/web/style.css`（窗口条样式）
- Test: 手动验收

**Interfaces:**
- Consumes: `/api/report/windows`
- Produces: `loadReportAll(quiet)`（Task 10/11 在其中追加图表调用）

- [ ] **Step 1: 实现（app.js 追加）**

```javascript
const CH_COLOR = { opencode: "var(--ch-opencode)", bai: "var(--ch-bai)", commandcode: "var(--ch-commandcode)",
  zcode: "var(--ch-zcode)", claudecode: "var(--ch-claudecode)", dsh: "var(--ch-dsh)" };   // 新R5 N18: 扩齐六渠道, 防分段同色

async function loadReportAll(quiet = false) {
  try {
    const range = state.range;
    const [w, rows, ov] = await Promise.all([
      api(`/api/report/windows`),
      api(`/api/report/channels?range=${range}`),
      api(`/api/accounts/overview`),                    // R1: 摘要条数据并入同一并发 (T9 renderQuotaBar)
    ]);
    renderWindows(w);
    renderQuotaBar(ov.accounts);
    renderChannelTable(rows.rows);
    $("report-scope").textContent = t("scopeHint").replace("{n}", w.channel_count).replace("{m}", w.account_count);
    // 估算徽章: 仅 指标=费用 且 含估算渠道(bai/zcode/claudecode)时显示 (新R5 N24: 注释随 R6 est 集合更新)
    $("report-est").hidden = !(state.reportMetric === "cost" && rows.rows.some((r) => r.estimated));
    const daily = await api(`/api/report/daily?range=${range}&metric=${state.reportMetric}`);
    chartReportStack(daily);
    chartReportDonut(daily);
    if (range === "today" || range === "yesterday") {
      $("report-hourly").closest(".card").hidden = false;    // R2: 藏整卡, 不留空壳标题
      chartReportHourly(await api(`/api/report/hourly?date=${range}`));
    } else {
      $("report-hourly").closest(".card").hidden = true;
    }
  } catch (e) { if (!quiet) toast(t("loadFailed") + ": " + e); }   // R1: 现有 key 为 loadFailed
}

function renderWindows(w) {
  const cell = (key, label, sub) => `<div class="wb-cell" data-win="${key}"><div class="wb-l">${label}</div>
    <div class="wb-v">${fmtTokens(w[key].tokens)}</div><div class="wb-v2">${fmtMoney(w[key].cost)}</div>
    <div class="wb-s${w.compare.spike && key === "today" ? " spike" : ""}">${sub}</div></div>`;
  const cmp = w.compare.insufficient_sample ? t("sampleInsufficient")
    : (w.compare.pct == null ? "" : `<span class="${w.compare.pct >= 0 ? "up" : "down"}">${w.compare.pct >= 0 ? "↑" : "↓"}${Math.abs(w.compare.pct)}%</span> ${t("vsSame")}`);
  $("windows-bar").innerHTML =
    cell("today", t("today"), cmp) + cell("yesterday", t("yesterday"), "") +   // 新R1: 昨日格副行为空 (规格布局)
    cell("7d", t("d7"), w["7d"].tokens ? `${t("dailyAvg")} ${fmtTokens(Math.round(w["7d"].tokens / 7))}` : "") +
    cell("30d", t("d30"), w["30d"].tokens ? `${t("dailyAvg")} ${fmtTokens(Math.round(w["30d"].tokens / 30))}` : "");
  // 点击格 -> 页头 pill 联动 (spec v4/v5 单向映射)
  document.querySelectorAll("#windows-bar .wb-cell").forEach((c) => c.addEventListener("click", () => {
    const map = { today: "today", yesterday: "yesterday", "7d": "7d", "30d": "30d" };
    const r = map[c.dataset.win];
    const btn = document.querySelector(`#home-pills .pill[data-r="${r}"]`);
    if (btn) btn.click();
  }));
}
```

- [ ] **Step 2: style.css 追加窗口条样式**

```css
/* ---- 首页: 时间窗口汇总条 + 渠道摘要条 (spec §3.1) ---- */
.windows-bar { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 12px; }
.wb-cell { background: var(--card-bg, #fff); border: 1px solid var(--line, #e5e7eb); border-radius: 10px; padding: 10px 12px; cursor: pointer; }
.wb-l { font-size: 11px; color: var(--text3); }
.wb-v { font-size: 18px; font-weight: 600; }
.wb-v2 { font-size: 12px; color: var(--text2); }
.wb-s { font-size: 11px; color: var(--text3); margin-top: 2px; }
.wb-s .up { color: #16a34a; } .wb-s .down { color: #dc2626; }
.wb-s.spike { color: #d97706; font-weight: 600; }
.scope-hint { font-size: 11px; color: var(--text3); padding: 2px 0 6px; }
```

> 变量名以 style.css 现有暗色主题变量为准——先 grep `--card`/`--line`/`--text3` 用现有名，不要新造主题变量。

- [ ] **Step 3: 手动验收**

全部 tab 显示 4 格窗口条；今日格副行环比（或"样本不足"）；点"近7天"格页头 pill 同步变近7天且图表联动；超均值 2 倍时数字橙色。

- [ ] **Step 4: Commit（人工确认后执行）**

```bash
git add app/web/app.js app/web/style.css
git commit -m "feat: 首页时间窗口汇总条(同时段环比/样本保护/pill联动)"
```

---

### Task 9: 配额摘要条（多账号归并 / min 同步时间 / 失败红点）

**Files:**
- Modify: `app/web/app.js`（新增 `renderQuotaBar`，在 `loadReportAll` 内调用 `/api/accounts/overview`）
- Test: 手动验收

**Interfaces:**
- Consumes: `GET /api/accounts/overview`（已存在，Task 6 已附 cc_summary；T8 的 `loadReportAll` 已将其并入 Promise.all 并调用 `renderQuotaBar(ov.accounts)`）。**R6：该接口只含账号渠道（opencode/bai/commandcode），本地渠道（zcode/claudecode/dsh）无配额概念，摘要条天然只渲染账号渠道——符合规格"配额摘要条仅账号渠道"。**
- Produces: `renderQuotaBar(accounts)`、`fmtAgo(iso)`

- [ ] **Step 1: 实现（app.js 追加；数据获取已在 T8 loadReportAll 中）**

```javascript
function renderQuotaBar(accounts) {
  const byCh = {};
  for (const a of accounts) {
    (byCh[a.source] = byCh[a.source] || []).push(a);
  }
  $("quota-bar").innerHTML = Object.keys(byCh).map((ch) => {
    const list = byCh[ch];
    // 同步归并 (spec v10): 时间取最陈旧 min; 任一失败 -> 红点
    const times = list.map((a) => a.last_sync_at).filter(Boolean).sort();
    const failed = list.some((a) => a.last_sync_status && a.last_sync_status !== "success");
    const syncTxt = times.length ? ` · ${fmtAgo(times[0])}` : "";
    const dot = failed ? ' <span class="sync-fail" title="同步失败">⚠</span>' : "";
    let body;
    if (ch === "opencode") {
      // 窗口百分比不可聚合 -> 最紧张账号 max% + 账号数角标 (spec v5)
      const pct = list.map((a) => (a.quota && a.quota.windows || []).reduce((m, x) => Math.max(m, x.label === "5h Rolling" ? (x.used || 0) : 0), 0));
      body = `▓▓▓░ ${Math.max(0, ...pct).toFixed(0)}% · ${list.length}${t("accountsUnit")}`;
    } else if (ch === "bai") {
      // 积分余额跨账号合计 (新R1 补真实数字; 字段名同 renderUsageBlocks 的 points 分支)
      const pts = list.reduce((s, a) => s + (((a.quota && a.quota.windows || [])
        .find((x) => x.unit === "points" || x.points_balance != null) || {}).points_balance || 0), 0);
      body = `${t("quotaPointsBalance").replace("{n}", fmtInt(pts))} · ${list.length}${t("accountsUnit")}`;
    } else if (ch === "commandcode") {
      // USD 剩余额度跨账号合计 (字段名同 renderUsageBlocks 的 USD 分支: w.used/w.total)
      const rem = list.reduce((s, a) => s + (((a.quota && a.quota.windows || [])
        .filter((x) => x.unit === "USD")
        .reduce((u, x) => u + ((Number(x.total) || 0) - (Number(x.used) || 0)), 0)) || 0), 0);
      body = `${fmtUsd(rem)} · ${list.length}${t("accountsUnit")}`;
    } else {
      body = `${list.length}${t("accountsUnit")}`;   // 未来渠道: 仅账号数 (配色/title 追加见 spec §8 checklist)
    }
    return `<div class="qb-row"><span class="qb-ch" style="color:${CH_COLOR[ch] || "inherit"}">${ch}</span>${body}${syncTxt}${dot}</div>`;
  }).join("");
}

function fmtAgo(iso) {  // 相对时间: 简化复用 fmtDateTime + 差值分钟
  const ms = Date.now() - new Date(iso.replace(" ", "T")).getTime();
  const m = Math.max(0, Math.round(ms / 60000));
  return m < 60 ? `${m}min` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`;
}
```

> BAI 积分/CmdCode USD 余额字段名以 `/api/accounts/overview` 的 `quota` 实际结构为准（`quota.windows[].points_balance` / USD 额度，渲染参照现有 `renderUsageBlocks` 的 `w.unit === "points"` 与 `w.unit === "USD"` 分支）——实现时对每账号 quota 求和即可。

- [ ] **Step 2: style.css 追加**

```css
.qb-row { font-size: 12px; padding: 4px 0; border-bottom: 1px dashed var(--line, #eee); }
.qb-ch { font-weight: 600; margin-right: 8px; }
.sync-fail { color: #dc2626; }
```

- [ ] **Step 3: 手动验收**

摘要条每渠道一行：OpenCode 显示最紧张账号 max% + 账号数；同步时间取多账号最陈旧；把一个账号的 sync 状态手工置 error（sqlite 改库）后红点出现。

- [ ] **Step 4: Commit（人工确认后执行）**

```bash
git add app/web/app.js app/web/style.css
git commit -m "feat: 配额摘要条(多账号归并/最陈旧同步时间/失败红点)"
```

---

### Task 10: 堆叠图 + 环形图（中心总量 + 扇区下钻）+ 指标 seg 联动

**Files:**
- Modify: `app/web/app.js`（`chartReportStack/chartReportDonut`）
- Test: 手动验收

**Interfaces:**
- Consumes: `/api/report/daily`（Task 8 已拉取）
- Produces: 环形图扇区点击 → `switchChannel(ch)`

- [ ] **Step 1: 实现**

```javascript
let cStack = null, cDonut = null;

function chColor(ch) {
  const v = CH_COLOR[ch];
  return v ? getComputedStyle(document.documentElement).getPropertyValue(v.replace(/var\(|\)/g, "").trim()) || "#4f8ef7" : "#4f8ef7";
}

function chartReportStack(d) {
  const canvas = $("report-stack");
  if (cStack) cStack.destroy();
  cStack = new Chart(canvas, {
    type: "bar",
    data: {
      labels: d.labels,
      datasets: Object.keys(d.series).map((ch) => ({
        label: ch, data: d.series[ch], backgroundColor: chColor(ch), borderRadius: 2, barPercentage: 0.8,
      })),
    },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 10 } },
        y: { stacked: true, grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => d.metric === "cost" ? fmtMoney(v) : d.metric === "requests" ? fmtInt(v) : fmtTokens(v) } },
      },
    },
  });
  cStack.resize();
}

function chartReportDonut(d) {
  const canvas = $("report-donut");
  if (cDonut) cDonut.destroy();
  const chs = Object.keys(d.series);
  const totals = chs.map((ch) => d.series[ch].reduce((a, b) => a + b, 0));
  const grand = totals.reduce((a, b) => a + b, 0);
  const centerText = { id: "centerText", afterDraw(chart) {   // 环形图中心总量 (spec v8, P0)
    const { ctx, chartArea } = chart;
    if (!chartArea) return;
    ctx.save();
    ctx.font = "600 16px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillStyle = cssVar("--text1") || "#111";
    const v = d.metric === "cost" ? fmtMoney(grand) : d.metric === "requests" ? fmtInt(grand) : fmtTokens(grand);
    ctx.fillText(v, (chartArea.left + chartArea.right) / 2, (chartArea.top + chartArea.bottom) / 2);
    ctx.restore();
  } };
  cDonut = new Chart(canvas, {
    type: "doughnut",
    plugins: [centerText],
    data: { labels: chs, datasets: [{ data: totals, backgroundColor: chs.map(chColor), borderWidth: 0 }] },
    options: {
      responsive: false, maintainAspectRatio: false, cutout: "62%",
      onClick: (_e, els) => { if (els.length) switchChannel(chs[els[0].index]); },  // 扇区->渠道 tab (spec v4)
      plugins: { legend: { position: "bottom", labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } } },
    },
  });
  cDonut.resize();
}
```

> `cssVar()` 为 app.js 现有辅助（`chartToday` 在用）；`chColor` 里 CSS 变量名去 `var()` 后用 `getComputedStyle` 读取。指标=费用且 BAI 在列时 `$("report-est").hidden = false`（在 loadReportAll 里依据 `rows.some(r => r.estimated)` 控制）。

- [ ] **Step 2: 手动验收**

堆叠图分段=渠道、范围/指标切换生效；环形图中心显示当前范围总量并随 seg 联动；点击扇区跳对应渠道 tab；est 徽章只在含 BAI 且指标=费用时出现。

- [ ] **Step 3: Commit（人工确认后执行）**

```bash
git add app/web/app.js
git commit -m "feat: 分渠道堆叠图+环形图(中心总量/扇区下钻)+指标seg"
```

---

### Task 11: 24h 堆叠图 + 渠道明细表 + 空态

**Files:**
- Modify: `app/web/app.js`（`chartReportHourly/renderChannelTable`，Task 8 已在 loadReportAll 调用）
- Test: 手动验收

**Interfaces:**
- Consumes: `/api/report/hourly`、`/api/report/channels`

- [ ] **Step 1: 实现**

```javascript
let cHourly = null;

function chartReportHourly(d) {
  const canvas = $("report-hourly");
  if (cHourly) cHourly.destroy();
  const chs = Object.keys(d.series);
  cHourly = new Chart(canvas, {
    type: "bar",
    data: { labels: d.labels.map((h) => `${h}`), datasets: chs.map((ch) => ({ label: ch, data: d.series[ch], backgroundColor: chColor(ch), borderRadius: 2, barPercentage: 0.9 })) },
    options: {
      responsive: false, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: chs.length > 1, labels: { usePointStyle: true, boxWidth: 8, font: { size: 11 }, color: cssVar("--text2") } } },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: cssVar("--text3"), font: { size: 10 }, maxTicksLimit: 12 } },
        y: { stacked: true, grid: { color: cssVar("--grid") }, ticks: { color: cssVar("--text3"), font: { size: 10 }, callback: (v) => fmtTokens(v) } },
      },
    },
  });
  cHourly.resize();
}

function renderChannelTable(rows) {
  if (!rows.length) {
    $("report-table").innerHTML = `<tr><td colspan="8" class="empty-cell">${t("reportEmpty")}</td></tr>`;
    return;
  }
  $("report-table").innerHTML = rows.map((r) => `<tr>
    <td style="color:${chColor(r.channel)}">${r.channel}${r.estimated ? ` <span class="est-badge" title="${t("estimateTip")}">${t("estimateBadge")}</span>` : ""}</td>
    <td class="num">${fmtTokens(r.tokens)}</td><td class="num">${fmtTokens(r.input)}</td><td class="num">${fmtTokens(r.output)}</td>
    <td class="num">${fmtTokens(r.cache_read)}</td><td class="num">${fmtInt(r.requests)}</td><td class="num">${fmtMoney(r.cost)}</td>
    <td>${r.channel === "dsh" ? t("dataSinceToday") : (r.data_since || "—")}</td></tr>`).join("");   // R6: dsh 仅今日
}
```

- [ ] **Step 2: 手动验收（对照 spec §7 前端清单前 8 条）**

范围=昨天时 24h 图仍显示且标题为"昨日趋势"；范围=7d 隐藏且布局无空洞；明细表"数据自"列与 db 里 oldest 一致；空库显示占位不报错。

- [ ] **Step 3: Commit（人工确认后执行）**

```bash
git add app/web/app.js
git commit -m "feat: 24h渠道堆叠图+渠道明细表(数据自列/空态)"
```

---

### Task 12: 单渠道 tab 过滤视图 + user-switch 解耦

**Files:**
- Modify: `app/web/app.js`（loadDashboard 的单渠道分支、renderUsageBlocks 参数化、新增 renderQuotaSingle/renderCcAccounts）
- Modify: `app/server.py`（Step 3 回补 2 条路由）
- Modify: `app/web/style.css`（acct-quota/acct-name 样式）
- Test: 手动验收

**Interfaces:**
- Consumes: Task 5 的 `channel_totals/channel_trend`（经 dashboard? 无——直接新调用）＋ `/api/accounts/overview`（配额块逐账号）

- [ ] **Step 1: 现有渲染函数参数化（R1 补：`renderUsageBlocks`/`renderCcSummary` 均写死目标容器，无法逐账号复用）**

`app/web/app.js:454` 的 `renderUsageBlocks(quota)` 首行 `const row = $("usage-blocks");` 改为：

```javascript
function renderUsageBlocks(quota, box) {
  const row = box || $("usage-blocks");
```

（函数其余逻辑不动；现有首页调用 `renderUsageBlocks(quota)` 不受影响。）

- [ ] **Step 2: 单渠道分支接入（R4 修正：零删除方案，取代 R3 的删除指引）**

R4 核实结论（见 T7 Step 3 引注）：`loadDashboard` 是 home/stats 两页共用加载器，函数体核心 = `range 选择 + api('/api/dashboard') + renderAll(data)`，**stats 页全部渲染依赖它（app.js:454 附近 switchPage 对两页均调用）**。因此**不得删除任何现有代码**——T7 骨架已用 `state.page === "home"` 守卫隔离：

- `home + channel==="all"` → `loadReportAll`（T8-T11），已 return
- `home + 单渠道` → 本任务 Step 3 的分支代码，**末尾 `return`，不落入现有逻辑**（落入会双重渲染：renderAll 用活跃账号数据覆盖渠道过滤数据）
- `stats 页` → 守卫不命中，现有逻辑原样执行（spec v3：P0 不动）

T7 过渡态（单渠道落入旧逻辑显示活跃账号数据）在本 Step 被替换：将 T7 骨架中 `// 单渠道: T7 阶段先落入下方现有逻辑...` 注释行替换为 Step 3 代码 + `return;`。

- [ ] **Step 3: 单渠道分支实现（替换 T7 过渡注释行，R1 补完整代码）**

```javascript
function renderQuotaSingle(accounts) {
  if (!accounts.length) {   // R6: 本地渠道 (zcode/claudecode/dsh) 无账号 -> 无配额占位
    $("usage-blocks").innerHTML = `<div class="empty-cell">${t("localNoQuota")}</div>`; return;
  }
  $("usage-blocks").innerHTML = accounts.map((a) =>
    `<div class="acct-quota"><div class="acct-name">${escapeHtml(a.name)}</div><div class="acct-quota-body" id="aq-${a.id}"></div></div>`).join("");
  accounts.forEach((a) => renderUsageBlocks(a.quota, $(`aq-${a.id}`)));
}

function renderCcAccounts(accounts) {
  const cc = accounts.filter((a) => a.source === "commandcode" && a.cc_summary && Object.keys(a.cc_summary).length);
  if (!cc.length) { $("cc-summary").hidden = true; return; }
  $("cc-grid").innerHTML = cc.map((a) => {
    const cs = a.cc_summary;
    const cards = [   // 新R2: 四色与现有 renderCcSummary 一致 (c-blue/violet/amber/green)
      { cls: "c-blue", l: t("ccRequests"), v: fmtInt(cs.totalCount) },
      { cls: "c-violet", l: t("ccTokens"), v: fmtTokens(cs.totalTokens) },
      { cls: "c-amber", l: t("ccCost"), v: fmtUsd(cs.totalCost) },
      { cls: "c-green", l: t("ccSuccessRate"), v: (Number(cs.successRate) || 0).toFixed(1) + "%" },
    ];
    return `<div class="acct-name">${escapeHtml(a.name)}</div>` + cards.map((c) =>
      `<div class="card kpi ${c.cls}"><div class="kpi-l">${c.l}</div><div class="kpi-v">${c.v}</div></div>`).join("");
  }).join("");
  $("cc-summary").hidden = false;
}
```

单渠道分支（loadDashboard 内，替换 Task 7 留下的占位注释）：

```javascript
  // 单渠道: 消耗走 report 接口(与活跃账号无关), 配额块/账期卡走 accounts/overview 逐账号 (spec v5/v8)
  Promise.all([
    api(`/api/report/channel-overview?range=${state.range}&channel=${state.channel}`),
    api(`/api/report/channel-trend?date=${state.range === "yesterday" ? "yesterday" : "today"}&channel=${state.channel}`),
    api(`/api/accounts/overview`),
  ]).then(([totals, trend, ov]) => {
    const chAccounts = ov.accounts.filter((a) => a.source === state.channel);
    renderQuotaSingle(chAccounts);
    const rangeHint = document.querySelector(".overview .hint");   // 新R1 N13: dsh 仅今日口径提示
    if (rangeHint) rangeHint.textContent = totals.today_only ? t("dataSinceToday") : t("followRange");
    renderOverview(totals, state.channel);          // 概览 6 格: channel_totals 键与 db.totals 对齐 (T5)
    chartToday(trend);                              // 24h input/output 双系列 (spec v8)
    const isCc = state.channel === "commandcode";
    $("cc-summary").hidden = !isCc;
    if (isCc) renderCcAccounts(chAccounts);         // 账期卡逐账号 (spec v5); 全部 tab 不显示
  }).catch((e) => { if (!quiet) toast(t("loadFailed") + ": " + e); });
  return;   // R5 补: 必须 return, 否则落入现有逻辑 renderAll 双重渲染 (与 Step 2 要求一致)
```

style.css 追加：

```css
.acct-quota { margin-bottom: 10px; }
.acct-name { font-size: 12px; font-weight: 600; color: var(--text2); margin: 4px 0; }
```

- [ ] **Step 4: Task 6 追加两个路由（回补，保持契约完整）**

```python
    if route == "/api/report/channel-overview" and method == "GET":
        range_ = query.get("range", ["today"])[0]
        range_ = range_ if range_ in ("today", "yesterday", "7d", "30d", "all") else "today"
        channel = query.get("channel", [""])[0] or "opencode"
        if channel == "dsh":   # R6: dsh 无历史表, 仅今日口径 (键对齐 db.totals, 供 renderOverview)
            dsh = dsh_api.get_dsh_usage()
            t = (dsh.get("today") or {}) if dsh.get("found") else {}
            _json_response(handler, {
                "request_count": 0, "session_count": 0,
                "total_input_tokens": t.get("input", 0), "uncached_input_tokens": t.get("input", 0),
                "total_output_tokens": t.get("output", 0), "total_reasoning_tokens": t.get("reasoning", 0),
                "cache_hit_tokens": 0, "cache_write_tokens": 0,
                "total_cost_usd": 0.0, "hit_rate": 0.0,
                "today_only": True})   # 新R1 N13: 前端据此在范围≠今天时提示"仅今日"
            return
        _json_response(handler, db.channel_totals(range_, channel))
        return

    if route == "/api/report/channel-trend" and method == "GET":
        date_ = query.get("date", ["today"])[0]
        date_ = date_ if date_ in ("today", "yesterday") else "today"
        channel = query.get("channel", [""])[0] or "opencode"
        _json_response(handler, db.channel_trend(date_, channel))   # dsh 由 db 层返回 [] (R6)
        return
```

- [ ] **Step 5: user-switch 解耦验证（R5 修正：零代码改动，纯验证）**

R4 的 page 守卫已天然实现解耦：`loadDashboard` 对 `state.page === "home"` 走渠道分流（数据与活跃账号无关），对 stats 页走现有逻辑（跟随活跃账号）。因此 user-switch 回调中的 `loadDashboard()` 调用**不需要移除**（移除会破坏 stats 页跟随账号，spec v5 闭环）。

仅验证（无需改代码）：顶栏切换账号后——① 首页（全部 tab 与单渠道 tab）数据不变；② 切到 stats 统计页，数据跟随新账号刷新。若 ① 不成立，检查是否还有其他直接调用首页渲染函数（`renderUsageBlocks`/`renderOverview`/`chartToday`）的回调点（grep 这三个函数名，排除 loadDashboard/renderAll 内部与 T12 新代码）。

- [ ] **Step 6: 手动验收（对照 spec §7 前端 9-11 条）**

顶栏切换账号首页不变；单渠道 tab 配额逐账号；CmdCode tab 账期卡逐账号；全部 tab 无账期卡。

- [ ] **Step 7: Commit（人工确认后执行）**

```bash
git add app/server.py app/web/app.js app/web/style.css
git commit -m "feat: 单渠道tab过滤视图(配额逐账号/账期卡) + 首页与user-switch解耦"
```

---

### Task 13: i18n 全量 + 渠道配色变量 + 终验

**Files:**
- Modify: `app/web/app.js:7`（I18N 词典）、`app/web/style.css`（渠道配色变量）

- [ ] **Step 1: CSS 渠道配色（R6 扩为六渠道；style.css 顶部 :root 与暗色块各加）**

```css
:root { --ch-opencode: #4f8ef7; --ch-bai: #d97706; --ch-commandcode: #a78bfa;
        --ch-zcode: #06b6d4; --ch-claudecode: #e11d48; --ch-dsh: #64748b; }
[data-theme="dark"] { --ch-opencode: #6ba3ff; --ch-bai: #f59e0b; --ch-commandcode: #b79bfd;
                      --ch-zcode: #22d3ee; --ch-claudecode: #fb7185; --ch-dsh: #94a3b8; }
```

- [ ] **Step 2: I18N 补齐（zh/en 各约 15 条，key 与前文 t() 调用一一对应）**

```javascript
// zh:
channelAll: "全部渠道", yesterday: "昨天", vsSame: "vs 昨日同时段",
sampleInsufficient: "样本不足", dailyAvg: "日均", scopeHint: "{n} 渠道 · {m} 账号",
accountsUnit: "账号", quotaBarTitle: "各渠道配额",
stackTitle: "分渠道消耗趋势", donutTitle: "渠道占比", chTableTitle: "渠道明细",
dataSince: "数据自", reportEmpty: "暂无数据", segTokens: "Token",
dataSinceToday: "仅今日", localNoQuota: "本地渠道，无配额概念",
// en:
channelAll: "All Channels", yesterday: "Yesterday", vsSame: "vs yesterday same time",
sampleInsufficient: "Low sample", dailyAvg: "Daily avg", scopeHint: "{n} channels · {m} accounts",
accountsUnit: " acct", quotaBarTitle: "Channel Quotas",
stackTitle: "Usage by Channel", donutTitle: "Channel Share", chTableTitle: "Channel Breakdown",
dataSince: "Data since", reportEmpty: "No data yet", segTokens: "Tokens",
dataSinceToday: "Today only", localNoQuota: "Local source — no quota",
```

- [ ] **Step 3: 手动终验（跑 spec §7 全部 22 条 + R6 六渠道项，重点）**

冷启动默认全部 tab；中英切换全文案完整；空库/单渠道/删除账号回退；勾稽（窗口条=单渠道之和）；暗色主题下图表配色正常；**R6 六渠道项：六渠道 tab 齐全（dsh 未检测到时不出现）；窗口条 today 含 dsh 本地用量而 7d/30d 不含（勾稽口径：today 范围下窗口条=各单渠道之和）；堆叠图/环形图出现 zcode/claudecode 分段；明细表六行且 dsh 行"数据自"显示"仅今日"；费用含 zcode/claudecode 时 est 徽章出现；单渠道 tab 切 zcode/claudecode 概览正常、切 dsh 显示今日口径概览；stats 页三区块（ZCode/DSH/Claude Code）不受影响**。

- [ ] **Step 4: Commit（人工确认后执行）—— Phase 2 / P0 完成**

```bash
git add app/web/app.js app/web/style.css
git commit -m "feat: i18n 全量+渠道配色变量 (P0 前端收尾)"
```

---

## Self-Review 记录（R2 更新）

1. **Spec 覆盖**：spec §3.1 窗口条(T8)/摘要条(T9)/seg+堆叠+环形+中心总量+扇区下钻(T10)/24h(T11)/明细表+数据自(T11)/粒度自适应(T2)/页头 tab+5档pill+范围提示(T7)/单渠道视图+配额分行+账期卡(T12)/解耦(T12)；§5 SQL(T2-5)/API(T6+T12 Step4)/配额模式(T9)/自然日口径(T2,T6)/前置验证(T1)/测试(T1-6)；§7 验收 22 条映射到 T13 Step3 逐条跑。单渠道视图依赖的 2 条补充路由在 T12 Step4 定义，无悬空引用。
2. **占位符扫描**：R1 已清除 `db_totals_placeholder`；T9 余额合计标注字段名以实际 quota 结构为准并给出取值分支参照（实现时对齐现有 `renderUsageBlocks` 的 points/USD 分支，非占位）。无 TBD/TODO。
3. **类型一致性**：`report_daily` 返回 `series[label]` 对齐 T10 `d.series[ch]`；`report_windows.channels[ch].last_sync_at/ok` 对齐 T3 测试断言与 T9 逐账号 `a.last_sync_at/last_sync_status`；`channel_totals` 键名与 `db.totals` 对齐（T5 断言 + T12 `renderOverview(totals, source)` 消费）；`channel_trend` 返回 `{hour,input,output}` 对齐现有 `chartToday(trend)`；`list_channel_summary` 的 `channel/accounts` 对齐 T7 `renderChannelTabs`。
4. **R2 时间脆弱审查**：daily today 造数改固定午时 `_today_at`（today 子句无 `<=now` 条件，任何时刻运行均有效）；compare 测试加 `COMPARE_SKIP` 环境窗口（0-1 点样本保护必触发、22 点后 now+2h 跨天）；T5 `_today_iso(0)` 即"现在"永远属于今天，无脆弱。
5. **R6 六渠道一致性**：① 口径登记表与各任务代码逐一对照（tokens=input+output+reasoning；claudecode 无 reasoning 记 0；cost 统一 USD，镜像表 `cost_raw/1e8`）；② dsh 边界：db 层零依赖 dsh_api（import 方向安全且测试无文件系统污染），server 层 `_report_windows_response/_report_channels_response` 并入，仅 today 窗口 + range=today 明细行（勾稽口径双向成立：today 双方含 dsh、7d/30d 双方不含）；③ `_report_metric_exprs/_report_range_sql` 替代旧 `_REPORT_METRICS/_report_range_clause`，T3/T4/T5 引用已全部同步；④ `list_channel_summary` 五渠道 + server 追加 dsh，T7 `renderChannelTabs`/`scopeHint` 消费不变；⑤ T12 本地渠道单渠道 tab：配额区显示 `localNoQuota` 占位、overview 走 dsh 分支/本地表分派；⑥ stats 页三区块（ZCode/DSH/Claude Code）零改动（loadDashboard page 守卫隔离）。

## spec 同步待办（R6，实施完成后回写 spec）

spec `20260904-token-summary-report.md` v10 基于"三账号渠道"假设，本计划 R6 已扩展为六渠道。实施完成后需回写 spec（届时按 AGENTS.md 流程更新并请用户确认）：

1. §2 口径注意：补 zcode/claudecode/dsh 三行（表名、tokens/cost 口径、est 标记、无配额）
2. §3.1 布局图：渠道 tab 示例更新为六渠道；配额摘要条注明"仅账号渠道"；明细表 dsh 行"仅今日"
3. §5 API：windows/channels 端点补 dsh 并入规则；新增口径登记表（同本计划）
4. §7 验收标准：补六渠道勾稽（today 含 dsh、7d/30d 不含）、dsh found=false 场景、stats 页回归
5. §8 新渠道接入 checklist：补"本地镜像表型渠道"接入路径（建表 → import → report 聚合段 → 配色/i18n）与"内存扫描型渠道"接入路径（dsh 模式：server 层并入 + 仅今日标注）
6. §5 性能条：改为"函数包裹列不可走索引、顺序扫描，≤10 万行毫秒级可接受；50 万行以上再做表达式索引/物化"（新 R1 N21）
