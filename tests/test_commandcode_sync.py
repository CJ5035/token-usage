"""server.py commandcode 同步调度测试: 配额分流 / 明细翻页+plan 盖章 / charts+summary / dashboard 分支."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from app import bai_api, commandcode_api, db, server


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库 + 重置 server 跨线程状态 (配额缓存/同步状态/防重入, 同 test_bai_sync)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    server._quota_cache.clear()
    server._quota_refreshing.clear()
    server._sync_state.update(
        running=False, mode="", page=0, inserted=0, phase="idle", message="", account=""
    )
    yield tmp_path
    db.close_db()


@pytest.fixture()
def no_window(tmp_db):
    """关闭同步范围裁剪, 避免测试记录被 window_days 删掉."""
    db.save_settings({"window_days": None})
    return tmp_db


_JAR = json.dumps([{"name": "better-auth.session-token", "value": "tok"}])
_HEADER = "better-auth.session-token=tok"


def _cc_account(name="CC", dedupe_key="usr-cc-1") -> int:
    """建一个 commandcode 账号 (token=jar JSON) 并设为活跃, 返回 account_id."""
    aid = db.add_account(_JAR, source="commandcode", dedupe_key=dedupe_key, switch=True)
    db.rename_account(aid, name)
    return aid


def _usage_row(usg_id, model="meta/muse-spark-1.3") -> dict:
    """commandcode usage 明细行 (同 commandcode_api._parse_usage_item 输出形态)."""
    return {
        "usg_id": usg_id, "created_at": "2026-09-03T08:00:00.000Z", "model": model,
        "provider": "commandcode", "input_tokens": 10, "output_tokens": 5,
        "reasoning_tokens": 0, "cache_read_tokens": 0, "cache_write_5m_tokens": 0,
        "cache_write_1h_tokens": 0, "cost_raw": 20507, "cost_usd": 0.00020507,
        "key_id": "", "session_id": "trace-1", "plan": None,
    }


def _bucket_today() -> str:
    """UTC 桶字符串 (1 小时前整点), 本地化后必落在今日 (避开本地零点边界 1 小时)."""
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")


def _boom(*_a, **_k):
    raise AssertionError("opencode/bai 专属入口不应被调用")


# ---------------------------------------------------------------------------
# _cc_cookie_header: jar JSON → Cookie 头
# ---------------------------------------------------------------------------

def test_cc_cookie_header_jar_and_passthrough():
    jar = json.dumps([
        {"name": "a", "value": "1"},
        {"name": "", "value": "2"},      # 空名过滤
        {"name": "b", "value": ""},      # 空值过滤
        {"name": "c", "value": "3"},
    ])
    assert server._cc_cookie_header(jar) == "a=1; c=3"
    # 非 JSON → 视为已是 header 形态, 原样返回
    assert server._cc_cookie_header("a=1; b=2") == "a=1; b=2"
    assert server._cc_cookie_header("") == ""
    # JSON 但非 jar 数组 → 取不到 cookie 对, 返回 ""
    assert server._cc_cookie_header('{"x": 1}') == ""


# ---------------------------------------------------------------------------
# 配额分流
# ---------------------------------------------------------------------------

def test_quota_commandcode_dispatches_to_cc_fetch_quota(no_window, monkeypatch):
    """commandcode 账号配额 → jar 转 Cookie 头后走 commandcode_api.fetch_quota, 缓存入槽."""
    aid = _cc_account()
    calls = []

    def fake_fetch_quota(cookie):
        calls.append(cookie)
        return {"success": True, "windows": [{"label": "5h Rolling", "unit": "USD"}]}

    monkeypatch.setattr(commandcode_api, "fetch_quota", fake_fetch_quota)
    monkeypatch.setattr(server, "fetch_quota", _boom)       # opencode 分支不应被触发
    monkeypatch.setattr(bai_api, "fetch_usage_points", _boom)  # bai 分支不应被触发

    quota = server._fetch_quota_with_cache(aid, _JAR, "")
    assert quota["success"] is True
    assert calls == [_HEADER]                  # 收到的是 jar 转出的 Cookie 头
    assert server._quota_cache[aid]["data"] is quota   # 写入缓存槽
    # TTL 内第二次调用命中缓存, 不再请求
    server._fetch_quota_with_cache(aid, _JAR, "")
    assert calls == [_HEADER]


# ---------------------------------------------------------------------------
# _sync_commandcode_account: 翻页 / plan 盖章 / charts / summary / 裁剪 / 认证
# ---------------------------------------------------------------------------

def test_sync_pages_until_hit_then_stops(no_window, monkeypatch):
    """两页翻页: 第二页命中已存在 usg_id → 该页入库后停止, plan 盖章生效."""
    aid = _cc_account()
    db.insert_usage_records([_usage_row("old_1")], account_id=aid)

    cursors = []

    def fake_page(cookie, limit=50, cursor=""):
        cursors.append(cursor)
        if cursor == "":
            return [_usage_row("new_1"), _usage_row("new_2")], "c2"
        if cursor == "c2":
            return [_usage_row("new_3"), _usage_row("old_1")], "c3"
        raise AssertionError("命中旧数据后不应继续翻页")

    monkeypatch.setattr(commandcode_api, "fetch_usage_page", fake_page)
    monkeypatch.setattr(commandcode_api, "fetch_subscription", lambda cookie: {"planId": "individual-go"})
    monkeypatch.setattr(commandcode_api, "fetch_charts", lambda cookie: [])
    monkeypatch.setattr(commandcode_api, "fetch_summary", lambda cookie: {})

    result = server._sync_commandcode_account(aid, "CC", "incremental", None)

    assert result["ok"] is True
    assert cursors == ["", "c2"]        # 第二页命中 old_1 即停, 未拉 c3
    assert result["inserted"] == 3      # new_1/2/3 入库, old_1 幂等未重复
    rows = db.get_db().execute(
        "SELECT usg_id, plan FROM usage_records WHERE account_id = ?", (aid,)
    ).fetchall()
    assert {r["usg_id"] for r in rows} == {"old_1", "new_1", "new_2", "new_3"}
    plans = {r["usg_id"]: r["plan"] for r in rows}
    # plan 盖章: 新插入行统一为订阅 planId (旧行 upsert 不改 plan 列)
    assert plans["new_1"] == plans["new_2"] == plans["new_3"] == "individual-go"


def test_sync_charts_summary_and_prune(tmp_db, monkeypatch):
    """charts 桶映射字段正确入库 (键缺失容错) + summary 落盘 + window_days 触发裁剪."""
    aid = _cc_account()
    ancient = _usage_row("ancient")
    ancient["created_at"] = "2025-01-01T00:00:00.000Z"   # 远超 30 天窗口
    db.insert_usage_records([ancient], account_id=aid)

    bucket = {
        "model": "meta/muse-spark-1.3", "provider": "vercel-ai-gateway",
        "timeBucket": "2026-09-03 08:50:00", "requests": 16,
        "totalCost": 0.031, "inputCost": 0.027, "outputCost": 0.001,
        "cacheCost": 0.001, "cacheSavings": 0.079,
        "consumedFreeCredits": 0.0, "consumedMonthlyCredits": 0.031,
        "consumedPurchasedCredits": 0.0,
        "tokensIn": 1091434, "tokensOut": 9282, "tokensTotal": 1100716,
        "cacheReadInputTokens": 813023, "cacheCreationInputTokens": 0,
    }
    summary = {"totalCount": 205, "totalCost": 0.38}

    monkeypatch.setattr(commandcode_api, "fetch_usage_page",
                        lambda cookie, limit=50, cursor="": ([_usage_row("n1")], ""))
    monkeypatch.setattr(commandcode_api, "fetch_subscription", lambda cookie: {"planId": "individual-go"})
    monkeypatch.setattr(commandcode_api, "fetch_charts", lambda cookie: [bucket, {"model": "m2"}])
    monkeypatch.setattr(commandcode_api, "fetch_summary", lambda cookie: summary)

    result = server._sync_commandcode_account(aid, "CC", "incremental", 30)

    assert result["ok"] is True
    rows = {
        r["model"]: r
        for r in db.get_db().execute(
            "SELECT * FROM charts_buckets WHERE account_id = ?", (aid,)
        ).fetchall()
    }
    b = rows["meta/muse-spark-1.3"]
    assert b["provider"] == "vercel-ai-gateway"
    assert b["time_bucket"] == "2026-09-03 08:50:00"
    assert b["requests"] == 16
    assert b["total_cost"] == 0.031
    assert b["input_cost"] == 0.027 and b["output_cost"] == 0.001
    assert b["cache_cost"] == 0.001 and b["cache_savings"] == 0.079
    assert b["consumed_monthly_credits"] == 0.031
    assert b["consumed_free_credits"] == 0.0 and b["consumed_purchased_credits"] == 0.0
    assert b["tokens_in"] == 1091434 and b["tokens_out"] == 9282
    assert b["tokens_total"] == 1100716
    assert b["cache_read_tokens"] == 813023 and b["cache_creation_tokens"] == 0
    # 键缺失容错: 缺失键取 0/""
    m2 = rows["m2"]
    assert (m2["provider"], m2["time_bucket"], m2["requests"]) == ("", "", 0)
    assert db.get_cc_summary(aid) == summary       # summary 已保存
    # window_days=30 裁剪: 窗口外旧记录被删, 本次新记录保留
    left = {
        r["usg_id"]
        for r in db.get_db().execute(
            "SELECT usg_id FROM usage_records WHERE account_id = ?", (aid,)
        ).fetchall()
    }
    assert "ancient" not in left
    assert "n1" in left


def test_sync_auth_error_sets_sync_state(no_window, monkeypatch):
    """明细拉取遇 CommandCodeAuthError → sync_state=error, 文案提示重新登录."""
    aid = _cc_account()

    def fake_page(cookie, limit=50, cursor=""):
        raise commandcode_api.CommandCodeAuthError("认证失败 (HTTP 401)")

    monkeypatch.setattr(commandcode_api, "fetch_usage_page", fake_page)
    result = server._sync_commandcode_account(aid, "CC", "incremental", None)

    assert result["ok"] is False
    state = db.get_sync_state(aid)
    assert state["last_sync_status"] == "error"
    assert "重新登录" in state["last_sync_error"]


def test_sync_unparsable_token_reports_error(tmp_db, monkeypatch):
    """token 非 jar 数组 (转不出 Cookie 头) → '未配置 token' 且 sync_state=error."""
    aid = db.add_account('{"name": "x"}', source="commandcode", dedupe_key="u9", switch=True)
    result = server._sync_commandcode_account(aid, "CC", "incremental", None)

    assert result["ok"] is False
    assert result["error"] == "未配置 token"
    assert db.get_sync_state(aid)["last_sync_status"] == "error"


# ---------------------------------------------------------------------------
# sync_usage 分发: commandcode 账号走 _sync_commandcode_account
# ---------------------------------------------------------------------------

def test_sync_usage_dispatches_commandcode(no_window, monkeypatch):
    """source='commandcode' 的活跃账号 → 走新函数, 不进 opencode 分支."""
    aid = _cc_account()   # 设为活跃

    monkeypatch.setattr(server, "_sync_one_account", _boom)
    monkeypatch.setattr(server, "resolve_workspace_id", _boom)
    monkeypatch.setattr(commandcode_api, "fetch_usage_page",
                        lambda cookie, limit=50, cursor="": ([], ""))
    monkeypatch.setattr(commandcode_api, "fetch_subscription", lambda cookie: None)
    monkeypatch.setattr(commandcode_api, "fetch_charts", lambda cookie: [])
    monkeypatch.setattr(commandcode_api, "fetch_summary", lambda cookie: {})

    result = server.sync_usage("full")

    assert result["ok"] is True
    assert db.get_sync_state(aid)["last_sync_status"] == "ok"   # cc 收尾已执行


# ---------------------------------------------------------------------------
# /api/dashboard 组装: commandcode 账户统计键来自 charts_aggregate + cc_summary
# ---------------------------------------------------------------------------

class _FakeHandler:
    command = "GET"


def _get_dashboard(monkeypatch, range_param="7d") -> dict:
    """直调 _handle_api, 捕获 _json_response 的 payload."""
    captured: dict = {}
    monkeypatch.setattr(server, "_json_response",
                        lambda handler, data, status=200: captured.update(data))
    server._handle_api(_FakeHandler(), "/api/dashboard", {"range": [range_param]})
    return captured


def test_dashboard_commandcode_uses_charts_aggregate(tmp_db, monkeypatch):
    aid = _cc_account()
    db.upsert_charts_buckets(
        [{
            "model": "m1", "provider": "commandcode", "time_bucket": _bucket_today(),
            "requests": 2, "total_cost": 0.5,
            "tokens_in": 100, "tokens_out": 20, "tokens_total": 120,
            "cache_read_tokens": 40, "cache_creation_tokens": 0,
        }],
        account_id=aid,
    )
    db.save_cc_summary(aid, {"totalCount": 9, "totalCost": 0.4})
    # 预热配额缓存槽, 避免 dashboard 触发后台刷新线程
    server._quota_cache[aid] = {"at": time.time(), "data": {"success": True, "windows": []}}

    agg_calls: dict = {}
    real_agg = db.charts_aggregate

    def spy_agg(account_id, days=None):
        agg_calls["days"] = days
        return real_agg(account_id, days=days)

    monkeypatch.setattr(db, "charts_aggregate", spy_agg)
    monkeypatch.setattr(server, "_fetch_usd_cny", lambda: 7.2)

    payload = _get_dashboard(monkeypatch, "7d")

    assert agg_calls["days"] == 7
    assert payload["totals"]["total_input_tokens"] == 100
    assert payload["totals"]["uncached_input_tokens"] == 60      # 100 - 40
    assert payload["totals"]["cache_hit_tokens"] == 40
    assert payload["today"]["request_count"] == 2
    assert payload["cc_summary"] == {"totalCount": 9, "totalCost": 0.4}
    assert payload["quota"] == {"success": True, "windows": []}
    assert payload["range"] == "7d"

    # range=all → charts_aggregate days=None
    _get_dashboard(monkeypatch, "all")
    assert agg_calls["days"] is None


def test_dashboard_opencode_has_no_cc_summary(tmp_db, monkeypatch):
    """opencode 账户: 不调 charts_aggregate, 无 cc_summary 键, 统计仍来自 usage_records."""
    aid = db.add_account("op-token", "ws-a", switch=True, source="opencode")
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    db.insert_usage_records(
        [{
            "usg_id": "op1", "created_at": now_iso, "model": "m", "provider": None,
            "input_tokens": 7, "output_tokens": 1, "reasoning_tokens": 0,
            "cache_read_tokens": 0, "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
            "cost_raw": 0, "cost_usd": 0.0, "key_id": None, "session_id": None, "plan": None,
        }],
        account_id=aid,
    )
    server._quota_cache[aid] = {"at": time.time(), "data": None}
    monkeypatch.setattr(db, "charts_aggregate", _boom)
    monkeypatch.setattr(server, "_fetch_usd_cny", lambda: 7.2)

    payload = _get_dashboard(monkeypatch, "7d")

    assert "cc_summary" not in payload
    assert payload["totals"]["total_input_tokens"] == 7   # 仍走 usage_records 聚合
