"""db.py commandcode 数据层测试: charts_buckets 建表/upsert/聚合 + commandcode 账号去重 + cc_summary 持久化."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app import db


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库: 重定向 data_dir 并重置模块级连接 (同 test_db_multiuser 夹具)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


def _bucket_utc(hour_offset: int = 0) -> str:
    """UTC 桶字符串 "YYYY-MM-DD HH:MM:SS" (整点); hour_offset=0 -> 当前小时, 本地化后必落在今日."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return (now + timedelta(hours=hour_offset)).strftime("%Y-%m-%d %H:%M:%S")


def _local_date(bucket: str) -> str:
    """桶经 SQLite datetime(time_bucket, 'localtime') 换算后的本地日期."""
    utc = datetime.strptime(bucket, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return utc.astimezone().strftime("%Y-%m-%d")


def _local_hour(bucket: str) -> str:
    utc = datetime.strptime(bucket, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return utc.astimezone().strftime("%H") + ":00"


def _bkt(model="mA", bucket=None, requests=1, total_cost=0.0, tokens_in=0,
         tokens_out=0, cache_read=0, cache_creation=0, provider="commandcode"):
    """charts_buckets 行字典, 键名与列一致 (调用方映射契约)."""
    return {
        "model": model, "provider": provider, "time_bucket": bucket,
        "requests": requests, "total_cost": total_cost,
        "input_cost": 0.0, "output_cost": 0.0, "cache_cost": 0.0, "cache_savings": 0.0,
        "consumed_free_credits": 0.0, "consumed_monthly_credits": 0.0,
        "consumed_purchased_credits": 0.0,
        "tokens_in": tokens_in, "tokens_out": tokens_out,
        "tokens_total": tokens_in + tokens_out,
        "cache_read_tokens": cache_read, "cache_creation_tokens": cache_creation,
    }


def _usage_today(usg_id="u1", model="m"):
    """今日一条 usage_records 行, 使 totals/daily_stats/model_stats/today_trend 有真实输出可对照键名."""
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "usg_id": usg_id, "created_at": now_iso, "model": model, "provider": None,
        "input_tokens": 1, "output_tokens": 1, "reasoning_tokens": 0,
        "cache_read_tokens": 0, "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
        "cost_raw": 0, "cost_usd": 0.1, "key_id": None, "session_id": None, "plan": None,
    }


# ---------------------------------------------------------------------------
# 建表
# ---------------------------------------------------------------------------


def test_charts_buckets_schema(tmp_db):
    conn = db.get_db()
    names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "charts_buckets" in names
    cols = conn.execute("PRAGMA table_info(charts_buckets)").fetchall()
    assert [c["name"] for c in cols] == [
        "account_id", "model", "provider", "time_bucket", "requests", "total_cost",
        "input_cost", "output_cost", "cache_cost", "cache_savings",
        "consumed_free_credits", "consumed_monthly_credits", "consumed_purchased_credits",
        "tokens_in", "tokens_out", "tokens_total", "cache_read_tokens",
        "cache_creation_tokens", "synced_at",
    ]
    pk = [c["name"] for c in sorted((c for c in cols if c["pk"]), key=lambda c: c["pk"])]
    assert pk == ["account_id", "model", "provider", "time_bucket"]


# ---------------------------------------------------------------------------
# upsert_charts_buckets
# ---------------------------------------------------------------------------


def test_upsert_overwrite_not_accumulate(tmp_db):
    """同 (account_id, model, provider, time_bucket) 重写 -> 覆盖不累加, count=1."""
    bucket = _bucket_utc()
    first = db.upsert_charts_buckets(
        [_bkt(bucket=bucket, requests=2, total_cost=0.5, tokens_in=80, tokens_out=40, cache_read=20)]
    )
    assert db.upsert_charts_buckets([]) == 0            # 空记录直接返回 0
    again = db.upsert_charts_buckets(
        [_bkt(bucket=bucket, requests=3, total_cost=0.9, tokens_in=10, tokens_out=5, cache_read=0)]
    )
    assert first == 1 and again == 1
    conn = db.get_db()
    rows = conn.execute("SELECT * FROM charts_buckets").fetchall()
    assert len(rows) == 1
    r = rows[0]
    assert r["requests"] == 3 and r["total_cost"] == 0.9
    assert r["tokens_in"] == 10 and r["tokens_out"] == 5 and r["tokens_total"] == 15
    assert r["cache_read_tokens"] == 0


def test_upsert_multi_account_isolated(tmp_db):
    """同桶不同 account_id 互不影响."""
    a = db.add_account("tA", "ws-a")
    b = db.add_account("tB", "ws-b")
    bucket = _bucket_utc()
    db.upsert_charts_buckets([_bkt(bucket=bucket, tokens_in=100, tokens_out=10)], account_id=a)
    db.upsert_charts_buckets([_bkt(bucket=bucket, tokens_in=7, tokens_out=1)], account_id=b)
    conn = db.get_db()
    assert conn.execute("SELECT COUNT(*) AS c FROM charts_buckets").fetchone()["c"] == 2
    ta = db.charts_aggregate(account_id=a)["totals"]
    tb = db.charts_aggregate(account_id=b)["totals"]
    assert ta["total_input_tokens"] == 100 and ta["total_output_tokens"] == 10
    assert tb["total_input_tokens"] == 7 and tb["total_output_tokens"] == 1


# ---------------------------------------------------------------------------
# charts_aggregate
# ---------------------------------------------------------------------------


def test_charts_aggregate_keys_and_values(tmp_db):
    # 现有函数的真实输出作为键名对照基准
    db.insert_usage_records([_usage_today()])
    totals_keys = set(db.totals(period="all").keys())
    daily_keys = set(db.daily_stats(days=7)[0].keys())
    model_keys = set(db.model_stats(period="all")[0].keys())
    trend_keys = set(db.today_trend()[0].keys())

    today = _bucket_utc(0)
    old = _bucket_utc(-72)                              # 三天前, 便于 days 过滤断言
    db.upsert_charts_buckets([
        _bkt(model="mA", bucket=today, requests=2, total_cost=0.5,
             tokens_in=80, tokens_out=40, cache_read=20),
        _bkt(model="mB", bucket=today, requests=1, total_cost=0.25,
             tokens_in=10, tokens_out=5, cache_read=0),
        _bkt(model="mA", bucket=old, requests=1, total_cost=1.0,
             tokens_in=100, tokens_out=50, cache_read=100),
    ])
    agg = db.charts_aggregate()
    assert set(agg.keys()) == {"totals", "today", "daily", "trend", "today_trend", "models"}
    assert set(agg["totals"].keys()) == totals_keys
    assert set(agg["today"].keys()) == totals_keys
    assert all(set(d.keys()) == daily_keys for d in agg["daily"])
    assert all(set(d.keys()) == daily_keys for d in agg["trend"])
    assert all(set(m.keys()) == model_keys for m in agg["models"])
    assert all(set(t.keys()) == trend_keys for t in agg["today_trend"])

    # totals: requests=4, tokens_in=190, 命中 120, 未缓存 70, 输出 95, 成本 1.75
    t = agg["totals"]
    assert t["request_count"] == 4
    assert t["total_input_tokens"] == 190
    assert t["cache_hit_tokens"] == 120
    assert t["uncached_input_tokens"] == 70             # tokens_in - cache_read
    assert t["total_output_tokens"] == 95
    assert t["total_cost_usd"] == pytest.approx(1.75, abs=1e-9)
    assert t["hit_rate"] == 63.16                       # 120 / 190 * 100, 两位小数
    assert t["session_count"] == 0                      # 桶无会话维度, 记 0
    assert t["total_reasoning_tokens"] == 0
    assert t["cache_write_tokens"] == 0

    # today: 仅今日两桶
    assert agg["today"]["request_count"] == 3
    assert agg["today"]["total_input_tokens"] == 90
    assert agg["today"]["hit_rate"] == 22.22            # 20 / 90

    # daily: 固定近 7 天, 日期升序 (old 在前)
    today_date, old_date = _local_date(today), _local_date(old)
    daily = {d["date"]: d for d in agg["daily"]}
    assert set(daily.keys()) == {old_date, today_date}
    assert daily[old_date]["request_count"] == 1
    assert daily[old_date]["cache_hit_tokens"] == 100
    assert daily[old_date]["uncached_input_tokens"] == 0
    assert daily[old_date]["hit_rate"] == 100.0
    assert daily[today_date]["request_count"] == 3

    # trend: days=None 不限时间; days=1 只剩今日
    assert {d["date"] for d in agg["trend"]} == {old_date, today_date}
    assert {d["date"] for d in db.charts_aggregate(days=1)["trend"]} == {today_date}

    # models: 按 tokens_in + tokens_out 降序 mA(270) > mB(15)
    models = agg["models"]
    assert [m["model"] for m in models] == ["mA", "mB"]
    assert models[0]["total_input_tokens"] == 180 and models[0]["total_output_tokens"] == 90
    assert models[0]["hit_rate"] == 66.67               # 120 / 180
    assert models[1]["hit_rate"] == 0.0                 # 0 / 10

    # today_trend: 24 小时补 0, 仅当前小时有值 (input=未缓存输入口径)
    tt = agg["today_trend"]
    assert len(tt) == 24
    by_hour = {x["hour"]: x for x in tt}
    h0 = _local_hour(today)
    assert by_hour[h0]["input"] == 70 and by_hour[h0]["output"] == 45
    assert by_hour[h0]["reasoning"] == 0
    assert sum(x["input"] for x in tt) == 70
    assert sum(x["output"] for x in tt) == 45
    assert sum(1 for x in tt if x["input"] == 0 and x["output"] == 0) == 23


def test_charts_aggregate_empty_bucket_zeroes(tmp_db):
    """无桶数据时全 0 且键齐全, 不崩溃."""
    agg = db.charts_aggregate()
    assert agg["totals"]["request_count"] == 0 and agg["totals"]["hit_rate"] == 0.0
    assert agg["today"]["total_input_tokens"] == 0
    assert agg["daily"] == [] and agg["trend"] == []
    assert len(agg["today_trend"]) == 24
    assert all(x["input"] == 0 and x["output"] == 0 for x in agg["today_trend"])
    assert agg["models"] == []


# ---------------------------------------------------------------------------
# add_account("commandcode") 去重
# ---------------------------------------------------------------------------


def test_commandcode_add_and_dedupe(tmp_db):
    """同 userId 重登 -> 不产生新行仅更新 token; 不同 userId 各自成行."""
    a = db.add_account("cc-tok-1", source="commandcode", dedupe_key="u-1")
    row = next(x for x in db.list_accounts() if x["id"] == a)
    assert row["source"] == "commandcode"
    assert row["workspace_id"] == "u-1"
    assert row["has_token"]
    before = db.count_accounts()
    b = db.add_account("cc-tok-2", source="commandcode", dedupe_key="u-1")
    assert a == b
    assert db.count_accounts() == before
    conn = db.get_db()
    assert conn.execute(
        "SELECT token FROM accounts WHERE id = ?", (a,)
    ).fetchone()["token"] == "cc-tok-2"
    c = db.add_account("cc-tok-3", source="commandcode", dedupe_key="u-2")
    assert c != a
    assert db.count_accounts() == before + 1


def test_commandcode_dedupe_fallback_to_hint(tmp_db):
    """dedupe_key 缺省时兜底取 workspace_hint, 只传 hint 的调用方同样正确去重."""
    a = db.add_account("cc-tok-1", workspace_hint="u-9", source="commandcode")
    b = db.add_account("cc-tok-2", workspace_hint="u-9", source="commandcode")
    assert a == b
    assert db.count_accounts() == 2                     # 种子 + 1
    row = next(x for x in db.list_accounts() if x["id"] == a)
    assert row["workspace_id"] == "u-9"


def test_commandcode_dedupe_scoped_to_source(tmp_db):
    """去重只在 source='commandcode' 内生效, 不命中同 workspace 的 opencode 行."""
    op = db.add_account("op-code", "u-1")
    cc = db.add_account("cc-tok", source="commandcode", dedupe_key="u-1")
    assert op != cc
    rows = {r["id"]: r["source"] for r in db.list_accounts()}
    assert rows[op] == "opencode" and rows[cc] == "commandcode"


# ---------------------------------------------------------------------------
# cc_summary 持久化
# ---------------------------------------------------------------------------


def test_cc_summary_roundtrip(tmp_db):
    assert db.get_cc_summary(1) == {}                   # 缺失
    summary = {"userId": "u-1", "planId": "individual-go", "monthlyCredits": 10.0}
    db.save_cc_summary(1, summary)
    assert db.get_cc_summary(1) == summary
    db.save_cc_summary(2, {"userId": "u-2"})
    assert db.get_cc_summary(1) == summary              # 多账号互不覆盖
    assert db.get_cc_summary(2) == {"userId": "u-2"}
    assert db.get_cc_summary(3) == {}                   # 未写入的账号
    db.save_cc_summary(1, {"userId": "u-1b"})           # 覆盖写
    assert db.get_cc_summary(1) == {"userId": "u-1b"}
    assert db.get_cc_summary(2) == {"userId": "u-2"}


def test_cc_summary_corrupted_or_missing_returns_empty(tmp_db):
    conn = db.get_db()
    db.save_cc_summary(1, {"a": 1})
    conn.execute("UPDATE settings SET payload = 'not-json' WHERE id = 1")
    conn.commit()
    assert db.get_cc_summary(1) == {}                   # 整个 payload 损坏
    db.save_cc_summary(1, {"a": 1})
    data = db._raw_payload(conn)
    data["cc_summary"] = "oops"                         # cc_summary 值不是 dict
    conn.execute(
        "UPDATE settings SET payload = ? WHERE id = 1", (json.dumps(data),)
    )
    conn.commit()
    assert db.get_cc_summary(1) == {}


# ---------------------------------------------------------------------------
# delete_account 级联清理 / clear_account 凭证语义 (EVOLUTION-2)
# ---------------------------------------------------------------------------


def test_delete_account_clears_charts_and_cc_summary(tmp_db):
    """delete_account 级联清理 charts_buckets 与 cc_summary; id 复用后新账户读不到幽灵历史."""
    a = db.add_account("tok-a", "ws-a")
    b = db.add_account("tok-b", "ws-b")
    db.upsert_charts_buckets([_bkt(bucket=_bucket_utc())], account_id=a)
    db.upsert_charts_buckets([_bkt(bucket=_bucket_utc())], account_id=b)
    db.save_cc_summary(a, {"userId": "u-a"})
    db.save_cc_summary(b, {"userId": "u-b"})

    assert db.delete_account(a) == 2                    # 剩余: 种子行 + b
    conn = db.get_db()
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM charts_buckets WHERE account_id = ?", (a,)
    ).fetchone()["c"] == 0
    assert db.get_cc_summary(a) == {}
    assert conn.execute(                                # 其他账号数据不受影响
        "SELECT COUNT(*) AS c FROM charts_buckets WHERE account_id = ?", (b,)
    ).fetchone()["c"] == 1
    assert db.get_cc_summary(b) == {"userId": "u-b"}

    # 删除后新建账户 (AUTOINCREMENT 递增, id 不复用) 读不到任何幽灵桶/summary
    top = conn.execute("SELECT MAX(id) AS m FROM accounts").fetchone()["m"]
    db.delete_account(top)
    fresh = db.add_account("tok-c", "ws-c")
    assert fresh > top
    assert db.get_cc_summary(fresh) == {}
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM charts_buckets WHERE account_id = ?", (fresh,)
    ).fetchone()["c"] == 0


def test_clear_account_keeps_charts_and_cc_summary(tmp_db):
    """登出仅清凭证 (EVOLUTION-2): usage_records/charts_buckets/cc_summary 属本地数据, 保留不清."""
    a = db.add_account("tok-a", "ws-a")                 # add_account 默认 switch=True
    db.insert_usage_records([_usage_today()], account_id=a)
    db.upsert_charts_buckets([_bkt(bucket=_bucket_utc())], account_id=a)
    db.save_cc_summary(a, {"userId": "u-a"})

    db.clear_account()

    conn = db.get_db()
    assert conn.execute("SELECT COUNT(*) AS c FROM charts_buckets").fetchone()["c"] == 1
    assert db.get_cc_summary(a) == {"userId": "u-a"}
    assert db.totals(period="all", account_id=a)["request_count"] == 1
    assert next(x for x in db.list_accounts() if x["id"] == a)["has_token"] is False
