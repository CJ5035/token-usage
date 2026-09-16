"""workbuddy_local_usage 存储层单测: 建表/幂等导入/游标存取/费用落库.

行数据统一由 conftest 的 wb_row fixture 提供 (tests/ 无 __init__.py, 不可跨文件 import).
"""
from __future__ import annotations

import sqlite3
import pytest
from app import db


def test_tables_created(tmp_db):
    names = {r["name"] for r in db.get_db().execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "workbuddy_local_usage" in names
    assert "workbuddy_file_progress" in names


def test_import_is_idempotent(tmp_db, wb_row):
    assert db.import_workbuddy_local_usage([wb_row()]) == 1
    assert db.import_workbuddy_local_usage([wb_row()]) == 0     # 同 dedupe_key 不重复插入
    assert db.get_db().execute(
        "SELECT COUNT(*) c FROM workbuddy_local_usage").fetchone()["c"] == 1


def test_import_persists_credit_and_cost(tmp_db, wb_row):
    db.import_workbuddy_local_usage([wb_row(credit=0.85, cost_raw=1000, available=1)])
    r = db.get_db().execute("SELECT * FROM workbuddy_local_usage").fetchone()
    assert r["credit"] == 0.85
    assert r["cost_raw"] == 1000
    assert r["cost_available"] == 1
    assert r["cache_write_tokens"] == 0
    assert r["total_tokens"] == 357          # 100+200+50+7, 与四项恒等


def test_import_handles_null_credit(tmp_db, wb_row):
    db.import_workbuddy_local_usage([wb_row(dedupe_key="m2", credit=None)])
    r = db.get_db().execute(
        "SELECT credit FROM workbuddy_local_usage WHERE dedupe_key='m2'").fetchone()
    assert r["credit"] is None


def test_failed_batch_rolls_back_and_can_retry(tmp_db, wb_row):
    with pytest.raises(sqlite3.IntegrityError):
        db.import_workbuddy_local_usage([wb_row("ok"), dict(wb_row("bad"), dedupe_key=None)])
    assert db.get_db().execute("SELECT COUNT(*) FROM workbuddy_local_usage").fetchone()[0] == 0
    assert db.get_workbuddy_file_progress_all() == {}
    assert db.import_workbuddy_local_usage([wb_row("ok"), wb_row("bad")]) == 2
    assert db.import_workbuddy_local_usage([wb_row("ok"), wb_row("bad")]) == 0


def test_progress_roundtrip(tmp_db):
    assert db.get_workbuddy_file_progress_all() == {}
    db.save_workbuddy_file_progress("C:\\wb\\s1.jsonl", 120, 200)
    assert db.get_workbuddy_file_progress_all() == {"C:\\wb\\s1.jsonl": (120, 200)}
    db.save_workbuddy_file_progress("C:\\wb\\s1.jsonl", 200, 200)   # 覆盖推进
    assert db.get_workbuddy_file_progress_all() == {"C:\\wb\\s1.jsonl": (200, 200)}


def test_last_import_at_none_when_empty(tmp_db, wb_row):
    assert db.workbuddy_local_last_import_at() is None
    db.import_workbuddy_local_usage([wb_row()])
    assert db.workbuddy_local_last_import_at() is not None
