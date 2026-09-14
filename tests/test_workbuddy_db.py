from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import db


@pytest.fixture
def tmp_workbuddy_db(tmp_path, monkeypatch):
    db.close_db()
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    yield tmp_path
    db.close_db()


def _row(request_id: str, when: str, credit=1.5, model="model-a"):
    return {
        "request_id": request_id,
        "request_time": when,
        "model": model,
        "client": "desktop",
        "credit": credit,
    }


def _workbuddy_account(token="session", user="u", switch=True):
    aid = db.add_account(token, user, switch=switch)
    db.get_db().execute("UPDATE accounts SET source='workbuddy', workspace_id=? WHERE id=?", (user, aid))
    db.get_db().commit()
    return aid


def test_workbuddy_schema_and_compound_idempotency(tmp_workbuddy_db):
    aid1 = _workbuddy_account("session-1", "u1")
    aid2 = _workbuddy_account("session-2", "u2", switch=False)
    assert db.insert_workbuddy_rows([_row("same", "2026-09-14 10:00:00")], aid1) == 1
    assert db.insert_workbuddy_rows([_row("same", "2026-09-14 10:00:00")], aid1) == 0
    assert db.insert_workbuddy_rows([_row("same", "2026-09-14 10:00:00")], aid2) == 1
    cols = db.get_db().execute("PRAGMA table_info(workbuddy_usage)").fetchall()
    pk = {r["name"] for r in cols if r["pk"]}
    assert pk == {"account_id", "request_id"}


def test_workbuddy_summary_excludes_unknown_credit_and_groups_models(tmp_workbuddy_db):
    aid = _workbuddy_account()
    db.insert_workbuddy_rows([
        _row("r1", "2026-09-14 10:00:00", 2.25, "m1"),
        _row("r2", "2026-09-14 11:00:00", None, "m1"),
        _row("r3", "2026-09-13 11:00:00", 1.0, "m2"),
    ], aid)
    summary = db.workbuddy_summary("today")
    assert summary["requests"] == 2
    assert summary["credits"] == pytest.approx(2.25)
    assert summary["models"][0]["model"] == "m1"
    assert summary["daily"][0]["credits"] == pytest.approx(2.25)
    assert summary["data_since"] == "2026-09-14"


def test_workbuddy_report_channel_has_unknown_cost_and_credits(tmp_workbuddy_db):
    aid = _workbuddy_account()
    db.insert_workbuddy_rows([_row("r1", "2026-09-14 10:00:00", 2.5)], aid)
    rows = {row["channel"]: row for row in db.report_channels("today")}
    wb = rows["workbuddy"]
    assert wb["requests"] == 1
    assert wb["tokens"] == 0
    assert wb["credits"] == pytest.approx(2.5)
    assert wb["cost"] is None
    assert wb["cost_available"] is False
    assert wb["data_since"] == "2026-09-14"


def test_workbuddy_summary_defaults_to_all_workbuddy_accounts(tmp_workbuddy_db):
    aid1 = _workbuddy_account("session-1", "u1")
    aid2 = _workbuddy_account("session-2", "u2", switch=False)
    db.insert_workbuddy_rows([_row("r1", "2026-09-14 10:00:00", 1.0)], aid1)
    db.insert_workbuddy_rows([_row("r2", "2026-09-14 11:00:00", 2.0)], aid2)
    summary = db.workbuddy_summary("today")
    assert summary["requests"] == 2
    assert summary["credits"] == pytest.approx(3.0)
    assert db.workbuddy_summary("today", account_id=aid1)["requests"] == 1


def test_delete_account_removes_workbuddy_usage(tmp_workbuddy_db):
    aid = _workbuddy_account()
    db.insert_workbuddy_rows([_row("r1", "2026-09-14 10:00:00")], aid)
    db.delete_account(aid)
    assert db.get_db().execute("SELECT COUNT(*) c FROM workbuddy_usage WHERE account_id=?", (aid,)).fetchone()["c"] == 0


def test_workbuddy_channel_order_and_summary(tmp_workbuddy_db):
    _workbuddy_account()
    channels = db.list_channel_summary()
    assert channels[0]["channel"] == "opencode"
    assert channels[-1]["channel"] == "workbuddy"
