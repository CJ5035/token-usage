"""server: Kiro 本地导入调度、summary / usage 路由、额度缓存."""
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from app import db, dsh_api, server

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api_call(monkeypatch):
    captured = {}
    monkeypatch.setattr(server, "_json_response",
                        lambda h, data, status=200: captured.update(data=data, status=status))

    def call(url, method="GET"):
        captured.clear()
        parsed = urlsplit(url)
        server._handle_api(SimpleNamespace(command=method), parsed.path,
                           parse_qs(parsed.query, keep_blank_values=True))
        return dict(captured)
    return call


@pytest.fixture
def kiro_triggers(monkeypatch):
    """替换 Kiro 导入触发点为计数器; 同时屏蔽 codex/workbuddy 触发与真实 DSH 扫描。"""
    calls = []
    monkeypatch.setattr(server, "_maybe_trigger_kiro_import", lambda: calls.append(1))
    monkeypatch.setattr(server, "_maybe_trigger_codex_import", lambda: None)
    monkeypatch.setattr(server, "_maybe_trigger_workbuddy_import", lambda: None)
    monkeypatch.setattr(dsh_api, "get_dsh_summaries", lambda *ranges, **kw: {r: {
        "found": False, "scanning": False, "stale": False, "refresh_error": False,
        "updated_at": None, "retry_after_seconds": 0, "range": r, "totals": {},
        "trend": [], "hourly": [], "sessions_count": 0, "data_since": None}
        for r in dict.fromkeys(ranges)})
    return calls


@pytest.fixture
def kiro_dir(tmp_path, monkeypatch):
    """把 Kiro 会话目录指向一个存在的空目录 (autouse 夹具默认指向不存在的路径)."""
    root = tmp_path / "kiro_sessions"
    root.mkdir()
    monkeypatch.setattr(server.kiro_local_api, "KIRO_SESSIONS_DIR", root)
    return root


def test_sync_kiro_local_persists_rows_and_progress(tmp_db, kiro_row, kiro_dir, monkeypatch):
    batch = {"path": "C:\\kiro\\s1.json", "rows": [kiro_row("s1:a"), kiro_row("s1:b")],
             "mtime_ns": 123, "size": 456, "skipped": 1}
    monkeypatch.setattr(server.kiro_local_api, "import_incremental",
                        lambda progress, **kw: [batch])
    assert server._sync_kiro_local(force=True) == 2
    assert db.get_kiro_file_progress_all() == {"C:\\kiro\\s1.json": (123, 456)}
    assert db.kiro_skipped_total() == 1
    assert server._kiro_sync_error == ""


def test_sync_kiro_local_records_error_without_raising(tmp_db, kiro_dir, monkeypatch):
    def boom(progress, **kw):
        raise RuntimeError("disk gone")
    monkeypatch.setattr(server.kiro_local_api, "import_incremental", boom)
    assert server._sync_kiro_local() == 0
    assert server._kiro_sync_error == "disk gone"


def test_sync_kiro_local_skips_db_when_sessions_dir_missing(monkeypatch):
    """未装 kiro-cli: 不查库也不采集 (无需 tmp_db —— 触碰数据库即视为失败)."""
    def must_not_run(*a, **kw):
        raise AssertionError("must not touch db / scan when sessions dir is missing")
    monkeypatch.setattr(server.db, "get_kiro_file_progress_all", must_not_run)
    monkeypatch.setattr(server.kiro_local_api, "import_incremental", must_not_run)
    assert server._sync_kiro_local() == 0
    assert server._kiro_sync_error == ""


def test_kiro_summary_route(tmp_db, kiro_row, api_call, kiro_triggers, kiro_dir):
    db.import_kiro_usage([kiro_row("s1:a", credits=2.5, request_count=3)])
    res = api_call("/api/kiro/summary?range=bogus")
    d = res["data"]
    assert res["status"] == 200 and kiro_triggers == [1]
    assert d["found"] is True and d["has_data"] is True and d["range"] == "30d"
    assert d["totals"]["credits"] == 2.5 and d["totals"]["request_count"] == 3
    assert d["running"] is False and d["error"] == ""


def test_kiro_summary_reports_missing_sessions_dir(tmp_db, api_call, kiro_triggers):
    d = api_call("/api/kiro/summary")["data"]
    assert d["found"] is False and d["has_data"] is False


def test_usage_routes_accept_kiro_source(tmp_db, kiro_row, api_call, kiro_triggers):
    db.import_kiro_usage([kiro_row("s1:a")])
    rec = api_call("/api/usage/records?source=kiro&page=1&page_size=7")
    assert rec["status"] == 200 and rec["data"]["total"] == 1
    assert rec["data"]["records"][0]["source"] == "kiro"
    ses = api_call("/api/usage/sessions?source=kiro&page=1&page_size=7")
    assert ses["status"] == 200 and ses["data"]["total"] == 1
    assert len(kiro_triggers) == 2
    assert api_call("/api/usage/records?source=bogus")["status"] == 400
    assert api_call("/api/usage/sessions?source=bogus")["status"] == 400


def test_report_routes_trigger_kiro_import_by_channel(tmp_db, api_call, kiro_triggers):
    api_call("/api/report/windows?channel=opencode")
    api_call("/api/report/channel-overview?channel=opencode&range=today")
    assert kiro_triggers == []
    api_call("/api/report/windows")
    api_call("/api/report/channels?range=7d")
    api_call("/api/report/channel-overview?channel=kiro&range=today")
    api_call("/api/report/channel-trend?channel=kiro&date=today")
    assert len(kiro_triggers) == 4


def test_channel_overview_for_kiro_uses_kiro_totals(tmp_db, kiro_row, api_call, kiro_triggers):
    db.import_kiro_usage([kiro_row("s1:a", credits=2.5, request_count=3)])
    d = api_call("/api/report/channel-overview?channel=kiro&range=today")["data"]
    assert d["credits"] == 2.5 and d["tokens_available"] is False and d["turn_count"] == 1

def test_kiro_only_install_is_discoverable_before_import(tmp_db, api_call, kiro_triggers, kiro_dir):
    assert api_call("/api/state")["data"]["kiro_found"] is True
    data = api_call("/api/report/channels")["data"]
    assert "kiro" in [x["channel"] for x in data["summary"]]
    assert data["kiro_local"]["running"] is False


def test_records_exposes_kiro_running_before_query(tmp_db, api_call, kiro_triggers, monkeypatch):
    monkeypatch.setattr(server, "_kiro_import_running", True)
    payload = api_call("/api/usage/records?source=kiro")["data"]
    assert payload["kiro_local"]["running"] is True


def test_no_import_thread_when_source_is_missing(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("missing source must not create a thread")
    monkeypatch.setattr(server.threading, "Thread", forbidden)
    monkeypatch.setattr(server, "_kiro_sync_error", "disk gone")   # 卸载 kiro 后旧错误不得残留
    server.kiro_import_async()
    assert server._kiro_import_running is False
    assert server._kiro_sync_error == ""


def test_kiro_probe_survives_raising_credential_read(tmp_db, api_call, kiro_triggers, monkeypatch):
    """凭据读取意外抛错时 /api/state 与 /api/report/channels 不得 500 (spec 保证 ②)."""
    def boom():
        raise RuntimeError("odd data dir")
    monkeypatch.setattr(server.kiro_api, "read_credentials", boom)
    assert api_call("/api/state")["data"]["kiro_found"] is False
    assert "kiro" not in [x["channel"] for x in api_call("/api/report/channels")["data"]["summary"]]


def test_kiro_quota_first_call_fetches_with_oauth_cache_in_data_dir(tmp_db, api_call, monkeypatch):
    seen = []

    def fake(path):
        seen.append(path)
        return {"success": True, "state": "ok", "plan": "KIRO STUDENT", "used": 1.0, "limit": 10.0}
    monkeypatch.setattr(server.kiro_api, "fetch_quota", fake)
    monkeypatch.setattr(server.kiro_api, "read_credentials", lambda: {"source_id": "fixture"})
    kicked = []
    monkeypatch.setattr(server, "_ensure_kiro_quota_async", lambda: kicked.append(1))
    assert api_call("/api/kiro/quota")["data"]["state"] == "loading"
    assert seen == [] and kicked == [1]  # HTTP 读取没有执行网络请求
    server._kiro_fetch_under_lock()       # 模拟单个后台 worker 完成
    assert api_call("/api/kiro/quota")["data"]["plan"] == "KIRO STUDENT"
    assert seen == [os.path.join(str(tmp_db), "kiro_oauth.json")]
    api_call("/api/kiro/quota")
    assert len(seen) == 1                        # 30 秒 TTL 内直返缓存


def test_kiro_quota_expired_cache_returns_old_and_refreshes_async(tmp_db, api_call, monkeypatch):
    monkeypatch.setattr(server.kiro_api, "read_credentials", lambda: {"source_id": "fixture"})
    server._kiro_quota_cache.update(at=1.0, source_id="fixture", data={"success": True, "plan": "OLD"})
    kicked = []
    monkeypatch.setattr(server, "_ensure_kiro_quota_async", lambda: kicked.append(1))
    d = api_call("/api/kiro/quota")["data"]
    # 过期缓存: 旧值照常返回, 但必须同时带 stale 与 refreshing (删掉任一即失败)
    assert d["plan"] == "OLD" and d["stale"] is True and d["refreshing"] is True
    assert kicked == [1]


def test_main_warms_up_kiro_import_and_quota():
    src = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "server.kiro_import_async()" in src
    assert "target=server.kiro_quota_warmup" in src

def test_quota_cache_invalidates_identity_and_reset(tmp_db, monkeypatch):
    identity = ["A"]
    monkeypatch.setattr(server.kiro_api, "read_credentials", lambda: {"source_id": identity[0]})
    monkeypatch.setattr(server, "_ensure_kiro_quota_async", lambda: None)
    monkeypatch.setattr(server.time, "time", lambda: 1000.0)
    server._kiro_quota_cache.update(at=999, source_id="A", data={
        "success": True, "reset_at_epoch": 1100, "reset_in_sec": 999})
    assert server._kiro_quota_payload()["reset_in_sec"] == 100
    identity[0] = "B"
    assert server._kiro_quota_payload() == {"success": False, "state": "loading"}
    server._kiro_quota_cache.update(at=999, source_id="B", data={
        "success": True, "reset_at_epoch": 1000})
    assert server._kiro_quota_payload()["state"] == "loading"
