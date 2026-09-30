"""db: kiro_usage 存储、进度与单渠道聚合."""
import pytest

from app import db


def test_kiro_table_has_no_token_columns(tmp_db):
    cols = {r["name"] for r in db.get_db().execute("PRAGMA table_info(kiro_usage)")}
    assert {"dedupe_key", "credits", "request_count", "cost_raw", "started_at"} <= cols
    assert not any(c.endswith("_tokens") for c in cols)


def test_import_kiro_usage_is_idempotent(tmp_db, kiro_row):
    assert db.import_kiro_usage([kiro_row("s1:a"), kiro_row("s1:b")]) == 2
    assert db.import_kiro_usage([kiro_row("s1:a")]) == 0
    assert db.import_kiro_usage([]) == 0
    assert db.get_db().execute("SELECT COUNT(*) c FROM kiro_usage").fetchone()["c"] == 2
    assert db.kiro_last_import_at() is not None


def test_kiro_file_progress_roundtrip_and_skipped_total(tmp_db):
    assert db.get_kiro_file_progress_all() == {}
    db.save_kiro_file_progress("C:\\k\\a.json", 111, 10, 2)
    db.save_kiro_file_progress("C:\\k\\b.json", 222, 20, 1)
    db.save_kiro_file_progress("C:\\k\\a.json", 333, 30, 0)
    assert db.get_kiro_file_progress_all() == {"C:\\k\\a.json": (333, 30),
                                               "C:\\k\\b.json": (222, 20)}
    assert db.kiro_skipped_total() == 1


def test_kiro_totals_aggregate_credits_requests_turns(tmp_db, kiro_row, local_iso):
    db.import_kiro_usage([
        kiro_row("s1:a", session_id="s1", credits=2.5, request_count=3, duration_ms=60_000),
        kiro_row("s1:b", session_id="s1", credits=1.5, request_count=2, duration_ms=30_000),
        kiro_row("s2:a", session_id="s2", credits=4.0, request_count=1,
                 started_at=local_iso(days=40)),
    ])
    t = db.kiro_totals("30d")
    assert t["turn_count"] == 2 and t["request_count"] == 5 and t["session_count"] == 1
    assert t["credits"] == 4.0
    assert t["total_cost_usd"] == pytest.approx(0.16)
    assert t["avg_duration_ms"] == 45_000
    assert t["tokens_available"] is False and t["total_tokens"] == 0 and t["hit_rate"] == 0.0
    assert t["cost_available"] is True and t["local_only"] is True
    assert db.kiro_totals("all")["turn_count"] == 3


def test_kiro_totals_empty_range(tmp_db):
    t = db.kiro_totals("today")
    assert t["turn_count"] == 0 and t["credits"] == 0.0 and t["cost_available"] is False
    assert t["avg_duration_ms"] is None and t["last_import_at"] is None


def test_kiro_summary_models_sorted_by_credits(tmp_db, kiro_row):
    db.import_kiro_usage([
        kiro_row("a", model="auto", credits=1.0, request_count=4),
        kiro_row("b", model="claude-opus-5", credits=5.0, request_count=2),
        kiro_row("c", model="claude-opus-5", credits=2.0, request_count=1),
    ])
    s = db.kiro_summary("30d")
    assert s["has_data"] is True and s["range"] == "30d"
    assert [(m["model"], m["turns"], m["requests"], m["credits"]) for m in s["models"]] == [
        ("claude-opus-5", 2, 3, 7.0), ("auto", 1, 4, 1.0)]
    assert s["models"][0]["cost"] == pytest.approx(0.28)
    assert s["data_since"] is not None and s["skipped"] == 0
    assert s["totals"]["turn_count"] == 3


def test_kiro_summary_without_data(tmp_db):
    s = db.kiro_summary("7d")
    assert s["has_data"] is False and s["models"] == [] and s["data_since"] is None

def test_rewritten_turn_updates_without_double_count(tmp_db, kiro_row):
    assert db.import_kiro_usage([kiro_row("a", credits=1, request_count=1)]) == 1
    assert db.import_kiro_usage([kiro_row("a", credits=2, request_count=3)]) == 0
    totals = db.kiro_totals("all")
    assert totals["turn_count"] == 1 and totals["credits"] == 2
    assert totals["request_count"] == 3
