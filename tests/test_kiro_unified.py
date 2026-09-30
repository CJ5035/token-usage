"""统一记录源: Kiro turn 进入使用记录与会话聚合."""
from app import db


def test_unified_records_kiro_rows(tmp_db, kiro_row):
    db.import_kiro_usage([kiro_row("s1:a", credits=2.5), kiro_row("s1:b", credits=1.0)])
    records, total = db.unified_records_page("kiro", 1, 20)
    assert total == 2
    r = records[0]
    assert r["source"] == "kiro" and r["source_record_id"].startswith("kiro:")
    assert r["total_tokens"] == 0 and r["input_tokens"] == 0 and r["cache_read_tokens"] == 0
    assert r["cost_available"] is True and r["cost_usd"] is not None
    assert r["duration_ms"] == 60_000 and r["speed_tps"] is None and r["ttft_ms"] is None


def test_unified_all_and_models_include_kiro(tmp_db, kiro_row):
    db.import_kiro_usage([kiro_row("s1:a", model="auto")])
    records, total = db.unified_records_page("all", 1, 20)
    assert total == 1 and records[0]["source"] == "kiro"
    assert db.unified_models("kiro") == ["auto"]


def test_unified_sessions_group_kiro_turns_and_drill_down(tmp_db, kiro_row):
    db.import_kiro_usage([kiro_row("s1:a", session_id="s1"), kiro_row("s1:b", session_id="s1"),
                          kiro_row("s2:a", session_id="s2")])
    sessions, total = db.unified_sessions_page("kiro", 1, 10)
    assert total == 2
    by = {s["session_id"]: s for s in sessions}
    assert by["s1"]["request_count"] == 2 and by["s1"]["source"] == "kiro"
    assert by["s1"]["group_id"].startswith("kiro:")
    rows, n = db.unified_records_page("kiro", 1, 20, group_id=by["s1"]["group_id"])
    assert n == 2 and {r["session_id"] for r in rows} == {"s1"}
