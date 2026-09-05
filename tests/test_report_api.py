"""report 聚合 API 测试: 渠道归一 / 自然日窗口 / 同时段环比 / 勾稽 / 空数据."""
from __future__ import annotations

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


@COMPARE_SKIP
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
    # pct 断言钉住对比分子 (今日同时段 1000 vs 昨日同时段 50 -> +1900%); 7 日跨度由下方 350 钉住
    assert w["compare"]["pct"] == pytest.approx(1900.0)
    # same_7 跨度直接断言: 近 7 个完整自然日(-7~-1, 不含今天)同时段 tokens = 7 天 × 50 = 350,
    # 错成 6 天(-6~-1)则只算到 300. SQL 与 report_windows 的 same7_where 同口径;
    # 本测试只种了 usage_records, 故仅查该表即等于三表合并值
    same7 = db._win_records(
        "substr(datetime(r.created_at,'localtime'),1,10) BETWEEN date('now','localtime','-7 days')"
        " AND date('now','localtime','-1 day')"
        " AND time(datetime(r.created_at,'localtime')) <= time('now','localtime')", [])
    assert same7["tokens"] == 350


def test_report_windows_sync_min_and_fail_priority(tmp_report_db):
    """同渠道多账号: 同步时间取 min(最陈旧); 任一失败 -> ok=False (spec v10).

    R1 修正: 账号必须先经 update_sync_state 建行(_ensure_state_row), 直接 UPDATE
    无行账号会命中 0 行导致断言必败."""
    a1 = db.add_account("tok-oc2", "ws-oc2")            # 同渠道第 2 个 opencode 账号
    ids = _seed_channels()
    for aid, st in ((a1, "ok"), (ids["opencode"], "ok")):
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


def test_channel_totals_zero_fallback_and_hit_rate(tmp_report_db):
    """review fix R1: channel_totals 空结果回退全零 (无 None), 口径逐字段对齐 db.totals."""
    ids = _seed_channels()
    t = db.channel_totals("7d", "bai")
    assert t["request_count"] == 0 and t["total_input_tokens"] == 0
    assert t["hit_rate"] == 0.0 and t["total_cost_usd"] == 0.0
    assert all(v is not None for v in t.values())
    db.insert_usage_records([_mkrec("hf1", _today_iso(5), inp=30, outp=10)], ids["opencode"])
    s = db.channel_totals("today", "opencode")
    assert isinstance(s["request_count"], int) and isinstance(s["total_input_tokens"], int)
    assert s["request_count"] == 1 and s["total_input_tokens"] == 30 and s["hit_rate"] == 0.0


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


def test_day_predicate_uses_expression_index(tmp_report_db):
    """性能修复 v2 (方案4① 路线C): datetime(col) 确定性表达式索引必须命中.
    today(等值边界) 与 7d(范围) 两档谓词都断言走 SEARCH USING INDEX."""
    ids = _seed_channels()
    db.insert_usage_records([_mkrec("u-ix", "2026-09-01T08:30:00Z")], ids["opencode"])
    for range_ in ("today", "7d"):
        where, params = db._report_range_sql(range_, "r.created_at")
        sql = ("SELECT COUNT(*) FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
               f" WHERE {where} AND COALESCE(a.source,'opencode') = 'opencode'")
        plan = " | ".join(r["detail"] for r in db.get_db().execute("EXPLAIN QUERY PLAN " + sql, params).fetchall())
        assert "USING" in plan and "INDEX" in plan, f"{range_} 谓词未命中索引: {plan}"


def test_range_sql_local_day_semantics(tmp_report_db):
    """边界语义: 本地今天中午(UTC 表示)的行命中 today 窗口, 前天行不命中;
    时区换算由 _local_day_utc_start 负责, 与原 substr(datetime(col,'localtime')) 逐日等价."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    ids = _seed_channels()
    noon_local = _dt.now().astimezone().replace(hour=12, minute=0, second=0, microsecond=0)
    in_row = noon_local.astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_row = (noon_local - _td(days=2)).astimezone(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.insert_usage_records([_mkrec("u-in", in_row), _mkrec("u-out", out_row)], ids["opencode"])
    where, params = db._report_range_sql("today", "r.created_at")
    sql = ("SELECT COUNT(*) FROM usage_records r LEFT JOIN accounts a ON a.id = r.account_id"
           f" WHERE {where}")
    assert db.get_db().execute(sql, params).fetchone()[0] == 1
