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


def test_workbuddy_summary_excludes_unknown_credit_and_groups_models(tmp_workbuddy_db, local_iso):
    aid = _workbuddy_account()
    today_utc = datetime.fromisoformat(local_iso()).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    yesterday_utc = datetime.fromisoformat(local_iso(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_workbuddy_rows([
        _row("r1", today_utc, 2.25, "m1"),
        _row("r2", today_utc, None, "m1"),
        _row("r3", yesterday_utc, 1.0, "m2"),
    ], aid)
    summary = db.workbuddy_summary("today")
    assert summary["requests"] == 2
    assert summary["credits"] == pytest.approx(2.25)
    assert summary["models"][0]["model"] == "m1"
    assert summary["daily"][0]["credits"] == pytest.approx(2.25)
    assert summary["data_since"] == today_utc[:10]


def test_workbuddy_report_channel_has_unknown_cost_and_credits(tmp_workbuddy_db, local_iso):
    aid = _workbuddy_account()
    today_utc = datetime.fromisoformat(local_iso()).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_workbuddy_rows([_row("r1", today_utc, 2.5)], aid)
    rows = {row["channel"]: row for row in db.report_channels("today")}
    wb = rows["workbuddy"]
    assert wb["requests"] == 1
    assert wb["tokens"] == 0
    assert wb["credits"] == pytest.approx(2.5)
    assert wb["cost"] is None
    assert wb["cost_available"] is False
    assert wb["data_since"] == today_utc[:10]


def test_workbuddy_summary_defaults_to_all_workbuddy_accounts(tmp_workbuddy_db, local_iso):
    aid1 = _workbuddy_account("session-1", "u1")
    aid2 = _workbuddy_account("session-2", "u2", switch=False)
    today_utc = datetime.fromisoformat(local_iso()).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db.insert_workbuddy_rows([_row("r1", today_utc, 1.0)], aid1)
    db.insert_workbuddy_rows([_row("r2", today_utc, 2.0)], aid2)
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


def test_workbuddy_relogin_updates_same_row(tmp_workbuddy_db):
    aid = db.add_account("session=old", "wb-u", switch=True, source="workbuddy", dedupe_key="wb-u")
    before = db.get_account()
    count = db.count_accounts()
    db.save_workbuddy_token(aid, "session=new", "wb-u")
    after = db.get_account()
    assert db.count_accounts() == count
    assert (after["id"], after["name"], after["source"]) == (aid, before["name"], "workbuddy")
    assert db.get_account_credentials(aid)[0] == "session=new"


def test_workbuddy_relogin_rejects_another_identity(tmp_workbuddy_db):
    aid = db.add_account("session=old", "wb-u", switch=True, source="workbuddy", dedupe_key="wb-u")
    with pytest.raises(ValueError, match="不一致"):
        db.save_workbuddy_token(aid, "session=new", "another-user")
    assert db.get_account_credentials(aid)[0] == "session=old"


def test_workbuddy_relogin_anonymous_target_fills_user_id(tmp_workbuddy_db):
    aid = db.add_account("session=old", "Default", switch=True, source="workbuddy", dedupe_key="")
    db.save_workbuddy_token(aid, "session=new", "wb-new-user")
    acc = db.get_account()
    assert acc["workspace_id"] == "wb-new-user"
    assert db.get_account_credentials(aid)[0] == "session=new"


def test_workbuddy_relogin_empty_user_id_keeps_previous_id(tmp_workbuddy_db):
    aid = db.add_account("session=old", "wb-orig", switch=True, source="workbuddy", dedupe_key="wb-orig")
    db.save_workbuddy_token(aid, "session=new", "")
    acc = db.get_account()
    assert acc["workspace_id"] == "wb-orig"
    assert db.get_account_credentials(aid)[0] == "session=new"


def test_workbuddy_relogin_target_deleted_or_non_workbuddy_raises(tmp_workbuddy_db):
    aid_oc = db.add_account("tok-oc", "wrk_1", switch=True, source="opencode")
    with pytest.raises(ValueError, match="不存在或来源不匹配"):
        db.save_workbuddy_token(aid_oc, "session=new", "wb-u")
    with pytest.raises(ValueError, match="不存在或来源不匹配"):
        db.save_workbuddy_token(99999, "session=new", "wb-u")


def test_workbuddy_relogin_two_accounts_no_crosstalk(tmp_workbuddy_db):
    aid1 = db.add_account("session=1", "u1", switch=True, source="workbuddy", dedupe_key="u1")
    aid2 = db.add_account("session=2", "u2", switch=False, source="workbuddy", dedupe_key="u2")
    db.insert_workbuddy_rows([_row("r1", "2026-09-15 10:00:00", 1.0)], aid1)
    db.insert_workbuddy_rows([_row("r2", "2026-09-15 10:00:00", 2.0)], aid2)

    db.save_workbuddy_token(aid2, "session=2-new", "u2")

    assert db.get_account_credentials(aid1)[0] == "session=1"
    assert db.get_account_credentials(aid2)[0] == "session=2-new"
    # usage rows remain attributed correctly
    assert db.workbuddy_summary("all", account_id=aid1)["requests"] == 1
    assert db.workbuddy_summary("all", account_id=aid2)["requests"] == 1

