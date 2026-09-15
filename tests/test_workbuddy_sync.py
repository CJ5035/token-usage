from __future__ import annotations

from datetime import datetime, timezone
import json
import threading
import time

import pytest

from app import db, server, workbuddy_api


@pytest.fixture
def tmp_workbuddy_server(tmp_path, monkeypatch):
    db.close_db()
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    server._quota_cache.clear()
    server._quota_refreshing.clear()
    server._sync_state.update(running=False, mode="", page=0, inserted=0, phase="idle", message="", account="")
    yield tmp_path
    db.close_db()


def _account():
    return db.add_account(json.dumps([{"name": "session", "value": "s"}]), "u", source="workbuddy", dedupe_key="u")


def _page(*rows, token=""):
    return {"rows": list(rows), "next_page_token": token, "version": 2}


def _row(rid, when="2025-12-02 10:00:00", credit=1.0):
    return {"request_id": rid, "request_time": when, "model": "m", "client": "desktop", "credit": credit}


def test_sync_workbuddy_full_pages_and_incremental_window(tmp_workbuddy_server, monkeypatch):
    aid = _account()
    calls = []

    def page(start, end, size, page_token="", page_num=None):
        calls.append((start, end, page_token, page_num))
        return _page(_row("r1"), token="next") if not page_token else _page(_row("r2"))

    monkeypatch.setattr(server, "WorkBuddyAPI", lambda token: type("A", (), {"fetch_request_usage_page": staticmethod(page)})())
    result = server._sync_workbuddy_account(aid, "WB", "full", None)
    assert result["ok"] is True and result["inserted"] == 2
    assert calls[0][0] == "2025-12-01 00:00:00"
    assert calls[1][2] == "next"
    assert db.get_db().execute("SELECT COUNT(*) c FROM workbuddy_usage").fetchone()["c"] == 2


def test_sync_workbuddy_auth_failure_preserves_rows(tmp_workbuddy_server, monkeypatch):
    aid = _account()
    db.insert_workbuddy_rows([_row("old")], aid)

    def fail(*_args, **_kwargs):
        raise workbuddy_api.WorkBuddyAuthError("expired")

    monkeypatch.setattr(server, "WorkBuddyAPI", lambda token: type("A", (), {"fetch_request_usage_page": fail})())
    result = server._sync_workbuddy_account(aid, "WB", "incremental", None)
    assert result["ok"] is False
    assert db.get_db().execute("SELECT COUNT(*) c FROM workbuddy_usage").fetchone()["c"] == 1
    assert db.get_sync_state(aid)["last_sync_status"] == "error"


def test_workbuddy_quota_maps_package_credits(tmp_workbuddy_server, monkeypatch):
    aid = _account()
    class API:
        def __init__(self, token): pass
        def fetch_resource_summary(self): return {}
        def fetch_paid_packages(self): return {"Accounts": []}
        def fetch_free_packages(self): return {"Accounts": [{"CycleCapacitySizePrecise": 100, "CycleCapacityRemainPrecise": 60}]}
    monkeypatch.setattr(server, "WorkBuddyAPI", API)
    quota = server._fetch_quota_with_cache(aid, "session", "u")
    assert quota["success"] is True
    assert quota["windows"][0]["unit"] == "credits"
    assert quota["windows"][0]["total"] == 100
    assert quota["windows"][0]["remaining"] == 60
    assert quota["windows"][0]["used"] == 40


def test_workbuddy_summary_route(tmp_workbuddy_server, monkeypatch, local_iso):
    aid = _account()
    today_utc = datetime.fromisoformat(local_iso()).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_workbuddy_rows([_row("r1", today_utc, 2.0)], aid)
    captured = {}
    monkeypatch.setattr(server, "_json_response", lambda _h, data, status=200: captured.update(data=data, status=status))
    server._handle_api(type("H", (), {"command": "GET"})(), "/api/workbuddy/summary", {"range": ["today"]})
    assert captured["status"] == 200
    assert captured["data"]["requests"] == 1
    assert captured["data"]["credits"] == 2.0


def test_workbuddy_counts_in_report_scope(tmp_workbuddy_server, monkeypatch):
    _account()
    monkeypatch.setattr(server.dsh_api, "get_dsh_summaries", lambda *args: {
        key: {"found": False, "totals": {}, "data_since": None, "updated_at": None}
        for key in ("today", "yesterday", "7d", "30d")
    })
    payload = server._report_windows_response(None)
    assert payload["account_count"] == 2  # seeded default OpenCode account + WorkBuddy


def test_workbuddy_status_uses_current_quota(tmp_workbuddy_server):
    aid = _account()
    account = next(a for a in db.list_accounts() if a["id"] == aid)
    assert server._workbuddy_auth_status(account) == "unknown"
    server._quota_cache[aid] = {"at": 0, "data": {"success": False, "auth_error": True}}
    assert server._workbuddy_auth_status(account) == "required"
    server._quota_cache[aid]["data"] = {"success": True, "windows": []}
    assert server._workbuddy_auth_status(account) == "valid"


def test_workbuddy_status_two_accounts_401_isolation(tmp_workbuddy_server):
    aid1 = _account()
    aid2 = db.add_account("s2", "u2", source="workbuddy", dedupe_key="u2")
    acc1 = next(a for a in db.list_accounts() if a["id"] == aid1)
    acc2 = next(a for a in db.list_accounts() if a["id"] == aid2)

    server._quota_cache[aid1] = {"at": 0, "data": {"success": True, "windows": []}}
    server._quota_cache[aid2] = {"at": 0, "data": {"success": False, "auth_error": True}}

    assert server._workbuddy_auth_status(acc1) == "valid"
    assert server._workbuddy_auth_status(acc2) == "required"


def test_workbuddy_status_mapping_unverified(tmp_workbuddy_server):
    aid = _account()
    acc = next(a for a in db.list_accounts() if a["id"] == aid)
    server._quota_cache[aid] = {"at": 0, "data": {"success": False, "mapping_unverified": True}}
    assert server._workbuddy_auth_status(acc) == "valid"


def test_workbuddy_status_other_sources_and_missing_token(tmp_workbuddy_server):
    aid_oc = db.add_account("tok-oc", "wrk_1", source="opencode")
    acc_oc = next(a for a in db.list_accounts() if a["id"] == aid_oc)
    assert server._workbuddy_auth_status(acc_oc) is None

    aid_wb_empty = db.add_account("", "u-empty", source="workbuddy", dedupe_key="empty")
    acc_empty = next(a for a in db.list_accounts() if a["id"] == aid_wb_empty)
    assert server._workbuddy_auth_status(acc_empty) == "missing"


def test_in_flight_old_token_does_not_overwrite_new_quota(tmp_workbuddy_server, monkeypatch):
    aid = _account()
    req_started = threading.Event()
    continue_old_req = threading.Event()

    class StallingAPI:
        def __init__(self, token):
            self.token = token
        def fetch_resource_summary(self):
            if "session" in self.token:  # old token
                req_started.set()
                continue_old_req.wait(timeout=5.0)
                raise workbuddy_api.WorkBuddyAuthError("401 unauthorized")
            return {}  # new token
        def fetch_paid_packages(self):
            return {"Accounts": [{"CycleCapacitySizePrecise": 100, "CycleCapacityRemainPrecise": 80}]}
        def fetch_free_packages(self): return {"Accounts": []}

    monkeypatch.setattr(server, "WorkBuddyAPI", StallingAPI)

    old_res = []
    t_old = threading.Thread(
        target=lambda: old_res.append(server._fetch_quota_with_cache(aid, 'session-old', "u"))
    )
    t_old.start()
    assert req_started.wait(timeout=5.0)

    # Save new token in DB and clear cache slot
    db.save_workbuddy_token(aid, "new-token", "u")
    server._quota_cache.pop(aid, None)

    # New token succeeds and caches
    new_quota = server._fetch_quota_with_cache(aid, "new-token", "u")
    assert new_quota.get("success") is True

    # Release old request
    continue_old_req.set()
    t_old.join(timeout=5.0)

    # Verify quota cache still contains new valid quota, not overwritten by old 401
    cached = server._quota_cache.get(aid, {}).get("data") or {}
    assert cached.get("success") is True
    assert not cached.get("auth_error")




# --- Transport auto-route tests (T4) ---------------------------------------
# These do NOT monkeypatch server.WorkBuddyAPI. Instead they register a fake
# transport via workbuddy_api.set_transport(fn) and let the REAL WorkBuddyAPI
# run end-to-end, proving that server._fetch_workbuddy_quota /
# _sync_workbuddy_account (which build WorkBuddyAPI(token) with no transport=)
# auto-route through the module-level transport (the T2 channel wiring).
# CRITICAL: every test resets workbuddy_api._transport = None in a finally so
# the global transport never leaks into the rest of the suite.

def _envelope(data):
    """Wrap a data dict in the {"code":0,"data":...} envelope WorkBuddyAPI expects."""
    return json.dumps({"code": 0, "data": data}, ensure_ascii=False)


def test_sync_workbuddy_routes_through_registered_transport(tmp_workbuddy_server):
    aid = _account()
    seen = []

    def fake_transport(url, headers, body, timeout):
        seen.append(url)
        # request-usage v2 shape: data.data = list of rows, data.nextPageToken = ""
        payload = {
            "data": [
                {
                    "requestId": "req-1",
                    "requestTime": "2025-12-02 10:00:00",
                    "model": "gpt-x",
                    "client": "desktop",
                    "credit": 1.5,
                }
            ],
            "total": 1,
            "nextPageToken": "",
        }
        return (200, _envelope(payload), {})

    try:
        workbuddy_api.set_transport(fake_transport)
        result = server._sync_workbuddy_account(aid, "WB", "full", None)
        assert result["ok"] is True
        assert result["inserted"] == 1
        assert seen and seen[0].endswith(workbuddy_api.REQUEST_USAGE)
        row = db.get_db().execute(
            "SELECT request_id, credit FROM workbuddy_usage WHERE account_id = ?", (aid,)
        ).fetchone()
        assert row["request_id"] == "req-1"
        assert row["credit"] == 1.5
    finally:
        workbuddy_api._transport = None


def test_sync_workbuddy_transport_redirect_to_login_is_auth_error(tmp_workbuddy_server):
    aid = _account()
    db.insert_workbuddy_rows([_row("old")], aid)

    def fake_transport(url, headers, body, timeout):
        # exactly what workbuddy_channel produces for a redirect-to-login:
        # 302 with a same-origin /auth/realms/... Location -> WorkBuddyAuthError
        return (302, "", {"Location": "/auth/realms/copilot/protocol/openid-connect/auth"})

    try:
        workbuddy_api.set_transport(fake_transport)
        result = server._sync_workbuddy_account(aid, "WB", "incremental", None)
        assert result["ok"] is False
        # existing rows preserved
        assert db.get_db().execute(
            "SELECT COUNT(*) c FROM workbuddy_usage WHERE account_id = ?", (aid,)
        ).fetchone()["c"] == 1
        assert db.get_sync_state(aid)["last_sync_status"] == "error"
    finally:
        workbuddy_api._transport = None


def test_quota_workbuddy_routes_through_registered_transport(tmp_workbuddy_server):
    aid = _account()

    def fake_transport(url, headers, body, timeout):
        if url.endswith(workbuddy_api.RESOURCE_SUMMARY):
            return (200, _envelope({}), {})
        if url.endswith(workbuddy_api.PAID_PACKAGES):
            return (200, _envelope({"Accounts": []}), {})
        if url.endswith(workbuddy_api.FREE_PACKAGES):
            return (200, _envelope({
                "Accounts": [
                    {"CycleCapacitySizePrecise": 100, "CycleCapacityRemainPrecise": 60}
                ]
            }), {})
        raise AssertionError(f"unexpected url {url}")

    try:
        workbuddy_api.set_transport(fake_transport)
        quota = server._fetch_quota_with_cache(aid, "session", "u")
        assert quota["success"] is True
        window = quota["windows"][0]
        assert window["unit"] == "credits"
        assert window["total"] == 100
        assert window["remaining"] == 60
        assert window["used"] == 40
    finally:
        workbuddy_api._transport = None


def test_request_usage_400_does_not_fallback_to_v1():
    """v2 遇 HTTP 4xx (契约/权限) 不应回退 v1 (官网无 v1, 诊断附录 A.2)."""
    calls = []

    def transport(url, headers, body, timeout):
        import json as _json
        calls.append(_json.loads(body) if body else None)
        return 400, "bad request", {}

    api = workbuddy_api.WorkBuddyAPI("session=s", transport=transport)
    import pytest as _pytest
    with _pytest.raises(workbuddy_api.WorkBuddyAPIError):
        api.fetch_request_usage_page("2026-09-01 00:00:00", "2026-09-14 23:59:59", 50)
    # 只应发一次 (v2), 不回退 v1
    assert len(calls) == 1
    assert calls[0]["version"] == 2
