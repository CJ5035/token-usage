from __future__ import annotations

import json
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


def test_workbuddy_summary_route(tmp_workbuddy_server, monkeypatch):
    aid = _account()
    db.insert_workbuddy_rows([_row("r1", "2026-09-14 10:00:00", 2.0)], aid)
    captured = {}
    monkeypatch.setattr(server, "_json_response", lambda _h, data, status=200: captured.update(data=data, status=status))
    server._handle_api(type("H", (), {"command": "GET"})(), "/api/workbuddy/summary", {"range": ["today"]})
    assert captured["status"] == 200
    assert captured["data"]["requests"] == 1
    assert captured["data"]["credits"] == 2.0
