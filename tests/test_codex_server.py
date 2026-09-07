"""Codex 服务层测试: 无网络 handler 夹具 / summary 契约 / 导入编排单飞 /
状态语义 / 六报表路由接入 / dashboard scope=all / DSH 仅 today.

全部走临时库 + monkeypatch, 不读本机真实 Codex 文件, 不起真实网络请求;
fixture (tmp_codex_db/local_iso/codex_row) 由 conftest 提供.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit, parse_qs

import pytest

from app import db, dsh_api, server


@pytest.fixture
def api_call(monkeypatch):
    captured = {}
    monkeypatch.setattr(server, "_json_response",
                        lambda h, data, status=200: captured.update(data=data, status=status))
    monkeypatch.setattr(server, "_ensure_quota_async", lambda *a, **k: None)
    monkeypatch.setattr(server, "_fetch_usd_cny", lambda: 7.2)
    def call(url, method="GET"):
        captured.clear()
        parsed = urlsplit(url)
        server._handle_api(SimpleNamespace(command=method), parsed.path, parse_qs(parsed.query))
        return dict(captured)
    return call


def _no_source(tmp_codex_db, monkeypatch):
    """Codex 会话目录指向不存在路径 (source_found=False 分支)."""
    monkeypatch.setattr(server.codex_api, "sessions_dir",
                        lambda: tmp_codex_db / "gone" / "sessions")


def _with_source(tmp_codex_db, monkeypatch):
    """Codex 会话目录指向真实存在的临时目录 (source_found=True 分支)."""
    d = tmp_codex_db / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(server.codex_api, "sessions_dir", lambda: d)


def _codex_progress(**over):
    p = {"offset": 100, "file_size": 100, "mtime_ns": 7, "content_fingerprint": "fp",
         "event_mode": "token_count", "last_model": "m1", "model_revision": 0,
         "has_turn_context": True, "last_event_seq": 1,
         "last_token_usage_fingerprint": "fp1", "parser_version": 1, "updated_at": None}
    p.update(over)
    return p


def _batch(path, rows, warnings=None, **over):
    return {"path": path, "rows": rows, "progress": _codex_progress(**over),
            "warnings": warnings or []}


def _mock_dsh_absent(monkeypatch):
    """DSH 缓存注入 found=false (不触发真实 ~/.dsh 扫描)."""
    monkeypatch.setattr(dsh_api, "_cache_payload", {
        "found": False, "updated_at": None, "sessions_count": 0,
        "total": {}, "today": {}, "providers": [], "models": []})
    monkeypatch.setattr(dsh_api, "_cache_ts", time.time())


def _mock_dsh_today(monkeypatch, today_tokens=70):
    """DSH 缓存注入 found=true (仅 today 口径, 无历史)."""
    monkeypatch.setattr(dsh_api, "_cache_payload", {
        "found": True, "updated_at": "2026-09-04T10:00:00", "sessions_count": 2,
        "total": {"input": today_tokens, "cache": 0, "output": today_tokens,
                  "reasoning": 0, "seconds": 60, "tps": 1.0},
        "today": {"input": today_tokens // 2, "cache": 0,
                  "output": today_tokens - today_tokens // 2,
                  "reasoning": 0, "seconds": 30, "tps": 1.0},
        "providers": [], "models": []})
    monkeypatch.setattr(dsh_api, "_cache_ts", time.time())


# ---------------------------------------------------------------------------
# 1. 简报固定夹具与用例 (逐字)
# ---------------------------------------------------------------------------


def test_codex_summary_route_no_login(tmp_codex_db, codex_row, monkeypatch, api_call):
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    db.import_codex_usage([codex_row()])
    assert db.count_logged_in_accounts() == 0
    response = api_call("/api/codex/summary?range=today")
    assert response["status"] == 200
    d = response["data"]
    assert d["totals"]["total_tokens"] == d["today"]["total_tokens"] == 130
    assert d["totals"]["avg_tps"] is None
    assert d["has_data"] is True and d["request_count_exact"] is False
    assert d["cost_available"] is False and d["cost_unavailable_channels"] == ["codex"]
    assert d["daily"] == d["daily7"]


def test_import_passes_entire_progress(tmp_codex_db, codex_row, monkeypatch):
    b = {"path": "fixture.jsonl", "rows": [codex_row()], "progress": {
        "offset": 100, "file_size": 100, "mtime_ns": 7,
        "content_fingerprint": "fixture", "event_mode": "token_count",
        "last_model": "m1", "model_revision": 0, "has_turn_context": True,
        "last_event_seq": 1, "last_token_usage_fingerprint": "fp1",
        "parser_version": 1, "updated_at": None},
        "warnings": []}
    monkeypatch.setattr(server.codex_api, "import_incremental", lambda p, force=False: [b])
    monkeypatch.setattr(server.codex_api, "last_scan_errors", [])
    assert server._sync_codex_local(force=True) == 1
    stored = db.get_codex_file_progress_all()["fixture.jsonl"]
    assert all(stored[key] == value for key, value in b["progress"].items() if key != "updated_at")
    assert stored["updated_at"] is not None


# ---------------------------------------------------------------------------
# 2. summary 契约: 固定键集 / 空源空库 / 历史保留 / range 白名单 / 精确计数
# ---------------------------------------------------------------------------


def test_codex_summary_fixed_keys(tmp_codex_db, codex_row, monkeypatch, api_call):
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _with_source(tmp_codex_db, monkeypatch)
    db.import_codex_usage([codex_row()])
    d = api_call("/api/codex/summary?range=7d")["data"]
    assert set(d.keys()) == {
        "range", "db_found", "source_found", "has_data", "request_count_exact",
        "cost_available", "cost_partial", "cost_unavailable_channels",
        "totals", "today", "channels", "models", "daily", "daily7",
        "last_import_at", "import_error", "importing", "revision"}
    assert d["range"] == "7d"
    assert d["source_found"] is True and d["db_found"] is True
    assert d["totals"]["total_tokens"] == 130
    assert d["totals"]["total_cost_usd"] is None and d["totals"]["cost_usd"] is None
    assert d["channels"][0]["provider_id"] == "codex"
    assert d["models"][0]["model"] == "m1" and d["models"][0]["provider_id"] == "codex"
    assert d["daily"] is d["daily7"]
    assert d["importing"] is False and d["revision"] == 0


def test_codex_summary_empty_without_source(tmp_codex_db, monkeypatch, api_call):
    """无源无库: 零 totals、数组空、db_found=false (目录缺失 + 无历史镜像)."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _no_source(tmp_codex_db, monkeypatch)
    d = api_call("/api/codex/summary?range=all")["data"]
    assert d["source_found"] is False and d["has_data"] is False and d["db_found"] is False
    assert d["totals"]["total_tokens"] == 0 and d["totals"]["total_cost_usd"] is None
    assert d["channels"] == [] and d["models"] == []
    assert d["request_count_exact"] is False and d["cost_unavailable_channels"] == []
    assert len(d["daily"]) == 7 and d["daily"] == d["daily7"]
    assert d["importing"] is False


def test_codex_summary_history_without_source_dir(tmp_codex_db, codex_row, monkeypatch, api_call):
    """source_missing/history_present: 目录暂缺但镜像有历史 → 历史统计仍可查."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _no_source(tmp_codex_db, monkeypatch)
    db.import_codex_usage([codex_row()])
    d = api_call("/api/codex/summary?range=today")["data"]
    assert d["source_found"] is False and d["has_data"] is True and d["db_found"] is True
    assert d["totals"]["total_tokens"] == 130


@pytest.mark.parametrize("rng", ["today", "yesterday", "7d", "30d", "all"])
def test_codex_summary_range_whitelist(tmp_codex_db, codex_row, monkeypatch, api_call, rng):
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    d = api_call(f"/api/codex/summary?range={rng}")["data"]
    assert d["range"] == rng


def test_codex_summary_unknown_range_falls_back(tmp_codex_db, codex_row, monkeypatch, api_call):
    """非法 range 回落端点默认 30d, 不把非法 query 拼 SQL (200 而非 500)."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    resp = api_call("/api/codex/summary?range=banana")
    assert resp["status"] == 200
    assert resp["data"]["range"] == "30d"


def test_codex_summary_exact_only_for_record_mode(tmp_codex_db, codex_row, monkeypatch, api_call):
    """request_count_exact: 全部 token_usage_record → true; 混入 token_count → false."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    exact_row = codex_row("s:1", event_mode="token_usage_record", event_seq=None,
                          response_id="resp-1", request_count_exact=True)
    db.import_codex_usage([exact_row])
    assert api_call("/api/codex/summary?range=today")["data"]["request_count_exact"] is True
    db.import_codex_usage([codex_row("s:2")])   # token_count 兼容模式
    assert api_call("/api/codex/summary?range=today")["data"]["request_count_exact"] is False


# ---------------------------------------------------------------------------
# 3. 导入编排: 故障保持旧数据 / 告警保留错误 / 完整成功清错 / 无变化推进时刻 / 单飞
# ---------------------------------------------------------------------------


def test_codex_import_failure_keeps_old_data(tmp_codex_db, codex_row, monkeypatch):
    """单批失败: 该批回滚、旧数据保留、revision 不变、last_error 记录."""
    db.import_codex_usage([codex_row("s:1")])
    db.update_codex_import_state(revision=5)

    def boom(batch):
        raise RuntimeError("codex db locked")

    monkeypatch.setattr(server.codex_api, "import_incremental",
                        lambda p, force=False: [_batch("b.jsonl", [codex_row("s:2")])])
    monkeypatch.setattr(db, "commit_codex_batch", boom)
    monkeypatch.setattr(server.codex_api, "last_scan_errors", [])
    assert server._sync_codex_local(force=True) == 0
    state = db.get_codex_import_state()
    assert "codex db locked" in state["last_error"]
    assert state["revision"] == 5                       # 错误保持旧数据
    assert db.codex_totals("all")["request_count"] == 1  # 坏批次未写入


def test_codex_scan_error_keeps_old_data(tmp_codex_db, monkeypatch):
    """目录/文件级扫描错误 (last_scan_errors): 不吞成成功, 保持旧错误文案."""
    db.update_codex_import_state(last_error="旧错误: badDir: permission denied")
    monkeypatch.setattr(server.codex_api, "import_incremental",
                        lambda p, force=False: [])
    monkeypatch.setattr(server.codex_api, "last_scan_errors",
                        ["C:\\badDir: PermissionError"])
    assert server._sync_codex_local(force=True) == 0
    state = db.get_codex_import_state()
    assert "C:\\badDir" in state["last_error"]


def test_codex_warnings_keep_last_error(tmp_codex_db, codex_row, monkeypatch):
    """可跳过告警: 保留既有错误计数与文案, 不用成功写入部分数据覆盖告警."""
    db.update_codex_import_state(last_error="旧错误: bad.jsonl: 非法 JSON")
    monkeypatch.setattr(server.codex_api, "import_incremental", lambda p, force=False: [
        _batch("ok.jsonl", [codex_row("s:9")], warnings=["ok.jsonl@0: 非法 JSON 行"])])
    monkeypatch.setattr(server.codex_api, "last_scan_errors", [])
    assert server._sync_codex_local(force=True) == 1
    state = db.get_codex_import_state()
    assert state["last_error"] == "旧错误: bad.jsonl: 非法 JSON"
    assert state["warning_count"] == 1
    assert db.codex_totals("all")["request_count"] == 1  # 数据照常入库


def test_codex_clean_success_clears_error_and_bumps_revision(tmp_codex_db, codex_row, monkeypatch):
    """无告警的完整成功: 清空 last_error, 仅数据变化加 revision."""
    db.update_codex_import_state(last_error="历史错误", revision=2)
    monkeypatch.setattr(server.codex_api, "import_incremental", lambda p, force=False: [
        _batch("a.jsonl", [codex_row("s:1")])])
    monkeypatch.setattr(server.codex_api, "last_scan_errors", [])
    assert server._sync_codex_local(force=True) == 1
    state = db.get_codex_import_state()
    assert state["last_error"] is None
    assert state["revision"] == 3
    assert state["last_import_at"] is not None


def test_codex_scan_without_change_updates_time_not_revision(tmp_codex_db, monkeypatch):
    """无变化的成功扫描: 也更新最后扫描时间, 不加 revision, 不报错."""
    db.update_codex_import_state(last_import_at="old", revision=3)
    monkeypatch.setattr(server.codex_api, "import_incremental", lambda p, force=False: [])
    monkeypatch.setattr(server.codex_api, "last_scan_errors", [])
    assert server._sync_codex_local(force=True) == 0
    state = db.get_codex_import_state()
    assert state["last_import_at"] != "old"
    assert state["revision"] == 3
    assert state["last_error"] is None


def test_codex_import_single_flight(tmp_codex_db, monkeypatch):
    """两线程 Event 控制单飞 (不 sleep): 并发第二次进入非阻塞跳过, 不等待扫描."""
    started, release = threading.Event(), threading.Event()
    calls = []

    def fake_sync(force=False):
        calls.append(force)
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(server, "_sync_codex_local", fake_sync)
    worker = threading.Thread(target=server._run_codex_import_once, daemon=True)
    worker.start()
    assert started.wait(5)
    server._run_codex_import_once()   # 锁被 worker 持有: 非阻塞拿不到, 直接跳过
    assert len(calls) == 1
    release.set()
    worker.join(5)
    assert len(calls) == 1


def test_codex_import_async_starts_own_thread(tmp_codex_db, monkeypatch):
    """codex_import_async 自身起线程: 调用后即有导入在跑, 无需外部 Thread 包装."""
    done = threading.Event()
    monkeypatch.setattr(server, "_sync_codex_local", lambda force=False: done.set())
    server.codex_import_async()
    assert done.wait(5)


def test_codex_import_state_running_flag(tmp_codex_db, monkeypatch):
    """导入期间 running=1, 结束后复位 0 (summary 的 importing 键读取它)."""
    seen = []

    def fake_sync(force=False):
        seen.append(db.get_codex_import_state()["running"])

    monkeypatch.setattr(server, "_sync_codex_local", fake_sync)
    server._run_codex_import_once()
    assert seen == [1]
    assert db.get_codex_import_state()["running"] == 0


# ---------------------------------------------------------------------------
# 4. /api/state 的 codex 块 / sync piggyback / 触发守卫
# ---------------------------------------------------------------------------


def test_state_exposes_codex_block(tmp_codex_db, codex_row, monkeypatch, api_call):
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _with_source(tmp_codex_db, monkeypatch)
    db.import_codex_usage([codex_row()])
    data = api_call("/api/state")["data"]
    codex = data["codex"]
    assert set(codex.keys()) == {
        "source_found", "has_data", "running", "revision", "last_import_at", "error"}
    assert codex["source_found"] is True and codex["has_data"] is True
    assert codex["running"] is False and codex["revision"] == 0
    assert codex["last_import_at"] and codex["error"] is None


def test_sync_usage_piggybacks_codex_after_accounts(tmp_codex_db, monkeypatch):
    """登录后 sync_usage 在账号同步完成后 piggyback Codex (Codex 失败不阻塞)."""
    db.add_account("tok-1", "ws-1")
    order = []
    monkeypatch.setattr(server, "_sync_one_account",
                        lambda *a, **k: order.append("remote")
                        or {"ok": True, "inserted": 0, "pages": 1})
    monkeypatch.setattr(server, "_sync_zcode_local", lambda: order.append("zcode"))
    monkeypatch.setattr(server, "_sync_claude_local", lambda: order.append("claude"))

    def fake_codex(force=False):
        order.append("codex")
        raise RuntimeError("codex boom")   # 失败不得影响远程同步结果

    monkeypatch.setattr(server, "_run_codex_import_once", fake_codex)
    result = server.sync_usage("incremental")
    assert result["ok"] is True
    assert order == ["remote", "zcode", "claude", "codex"]


def test_report_routes_trigger_codex_only_for_codex_or_all(tmp_codex_db, monkeypatch, api_call):
    """仅 Codex/all 查询触发扫描; 专属其他渠道与无 scope dashboard 不触发."""
    triggered = []
    monkeypatch.setattr(server, "codex_import_async", lambda: triggered.append(1))
    _mock_dsh_absent(monkeypatch)
    db.add_account("tok-1", "ws-1")
    for url in ("/api/report/windows", "/api/report/daily", "/api/report/hourly",
                "/api/report/channels", "/api/report/channel-overview?channel=codex",
                "/api/report/channel-trend?channel=codex", "/api/codex/summary",
                "/api/dashboard?scope=all"):
        server._codex_last_import_trigger = 0.0
        api_call(url)
        assert triggered[-1:] == [1], url
    count = len(triggered)
    for url in ("/api/report/windows?channel=zcode", "/api/report/windows?channel=dsh",
                "/api/report/daily?channel=zcode", "/api/report/hourly?channel=claudecode",
                "/api/report/channel-overview?channel=zcode",
                "/api/report/channel-trend?channel=zcode", "/api/dashboard"):
        server._codex_last_import_trigger = 0.0
        api_call(url)
        assert len(triggered) == count, url


# ---------------------------------------------------------------------------
# 5. 六报表路由接入 Codex / dashboard scope / DSH 口径
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("url", [
    "/api/report/windows?channel=codex",
    "/api/report/daily?range=today&channel=codex",
    "/api/report/hourly?date=today&channel=codex",
    "/api/report/channels?range=today",
    "/api/report/channel-overview?range=today&channel=codex",
    "/api/report/channel-trend?date=today&channel=codex",
])
def test_report_routes_serve_codex(tmp_codex_db, codex_row, monkeypatch, api_call, url):
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _mock_dsh_absent(monkeypatch)
    db.import_codex_usage([codex_row()])
    resp = api_call(url)
    assert resp["status"] == 200, url
    d = resp["data"]
    if "windows" in url:
        assert d["today"]["tokens"] == 130 and d["today"]["cost"] is None
        assert d["today"]["cost_partial"] is True and d["today"]["request_count_exact"] is False
    elif "daily" in url:
        assert sum(d["series"]["codex"]) == 130
    elif "hourly" in url:
        assert len(d["buckets"]) == 24
        assert sum(b["total_tokens"] for b in d["buckets"]) == 130
    elif "/api/report/channels" in url:
        row = next(r for r in d["rows"] if r["channel"] == "codex")
        assert row["tokens"] == 130 and row["cost"] is None
        assert row["cost_available"] is False and row["cost_partial"] is True
        assert row["estimated"] is False
        assert any(s["channel"] == "codex" and s["accounts"] == 0 for s in d["summary"])
    elif "channel-overview" in url:
        assert d["total_tokens"] == 130 and d["total_cost_usd"] is None
        assert d["request_count"] == 1
    elif "channel-trend" in url:
        assert sum(r["total_tokens"] for r in d) == 130
        assert sum(r["total_input_tokens"] for r in d) == 100   # 含缓存的 input 不再加缓存


def test_report_routes_unknown_range_falls_back(tmp_codex_db, monkeypatch, api_call):
    """非法 range/date 参数回落默认, 不 500."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _mock_dsh_absent(monkeypatch)
    for url in ("/api/codex/summary?range=banana",
                "/api/dashboard?scope=all&range=banana",
                "/api/report/daily?range=banana",
                "/api/report/hourly?date=banana&channel=codex",
                "/api/report/channels?range=banana",
                "/api/report/channel-overview?range=banana&channel=codex",
                "/api/report/channel-trend?date=banana&channel=codex"):
        assert api_call(url)["status"] == 200, url


def test_dashboard_scope_all_and_account(tmp_codex_db, codex_row, monkeypatch, api_call):
    """scope=all 全渠道聚合 (含 Codex), 不伪装 active account; 无 scope 保持原语义."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _mock_dsh_absent(monkeypatch)
    db.import_codex_usage([codex_row()])
    d = api_call("/api/dashboard?scope=all&range=today")["data"]
    assert d["scope"] == "all" and d["range"] == "today"
    assert d["totals"]["total_tokens"] == d["today"]["total_tokens"] == 130
    assert d["totals"]["total_cost_usd"] is None
    assert d["totals"]["cost_unavailable_channels"] == ["codex"]
    assert d["codex"]["has_data"] is True
    assert "account" not in d and "quota" not in d and "logged_in" not in d
    # 无 scope: 原六个账号聚合键保持原义, 仅追加 scope 与 codex 状态
    d2 = api_call("/api/dashboard?range=today")["data"]
    assert d2["scope"] == "account"
    assert d2["range"] == "today" and "account" in d2 and "quota" in d2
    assert d2["codex"]["has_data"] is True
    assert d2["totals"]["request_count"] == 0   # codex 不进账号聚合


def test_dashboard_scope_all_equals_channel_rows_without_dsh(tmp_codex_db, codex_row,
                                                             monkeypatch, api_call):
    """DSH 未发现: 全渠道 totals 与渠道行同指标合计一致 (勾稽)."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _mock_dsh_absent(monkeypatch)
    ids = {}
    ids["opencode"] = db.add_account("tok-oc", "ws-oc")
    import datetime as _dt
    noon = (_dt.datetime.now().astimezone()
            .replace(hour=12, minute=0, second=0, microsecond=0)
            .astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    db.insert_usage_records([{
        "usg_id": "u1", "created_at": noon, "model": "m", "provider": "anthropic",
        "input_tokens": 10, "output_tokens": 20, "reasoning_tokens": 0,
        "cache_read_tokens": 0, "cache_write_5m_tokens": 0, "cache_write_1h_tokens": 0,
        "cost_raw": 0, "cost_usd": 0.5, "key_id": None, "session_id": None, "plan": None,
    }], ids["opencode"])
    db.import_codex_usage([codex_row()])
    d = api_call("/api/dashboard?scope=all&range=today")["data"]
    rows = db.report_channels("today")
    assert sum(r["tokens"] for r in rows) == d["totals"]["total_tokens"] == 160
    assert sum(r["requests"] for r in rows) == d["totals"]["request_count"] == 2
    # windows 全渠道同口径勾稽
    w = api_call("/api/report/windows")["data"]
    assert w["today"]["tokens"] == d["totals"]["total_tokens"]


def test_dashboard_scope_all_dsh_contributes_only_today(tmp_codex_db, codex_row,
                                                        monkeypatch, api_call):
    """DSH found: 仅 range=today 的 totals/today 并入 (35+35=70), 7d 不含 DSH."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _mock_dsh_today(monkeypatch, today_tokens=70)
    db.import_codex_usage([codex_row()])
    d_today = api_call("/api/dashboard?scope=all&range=today")["data"]
    assert d_today["totals"]["total_tokens"] == 130 + 70
    assert d_today["today"]["total_tokens"] == 130 + 70
    d_7d = api_call("/api/dashboard?scope=all&range=7d")["data"]
    assert d_7d["totals"]["total_tokens"] == 130   # 7d 不含 DSH (无历史)


def test_account_switch_keeps_scope_all(tmp_codex_db, codex_row, monkeypatch, api_call):
    """两个远程账号切换不改变 scope=all 聚合 (全渠道口径与 active account 无关)."""
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    _mock_dsh_absent(monkeypatch)
    a1 = db.add_account("tok-1", "ws-1")
    a2 = db.add_account("tok-2", "ws-2", switch=False)
    db.import_codex_usage([codex_row()])
    before = api_call("/api/dashboard?scope=all&range=today")["data"]["totals"]
    assert db.set_active_account(a2)
    after = api_call("/api/dashboard?scope=all&range=today")["data"]["totals"]
    assert before == after
