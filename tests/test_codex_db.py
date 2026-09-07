"""Codex 存储层测试: 原子导入、批次事务回滚、迁移与聚合口径 (db.py Codex 区块)."""

import pytest

from app import db


def test_codex_totals_and_repeat(tmp_codex_db, codex_row, local_iso):
    rows = [codex_row(), codex_row("s:2", started_at=local_iso(1), model="m2",
                                   provider_id="codex", total_tokens=130)]
    assert db.import_codex_usage(rows) == 2
    assert db.import_codex_usage(rows) == 0
    all_t = db.codex_totals("all")
    assert all_t["total_tokens"] == 260
    assert all_t["total_input_tokens"] == 200
    assert all_t["uncached_input_tokens"] == 160
    assert all_t["avg_tps"] is None and all_t["total_cost_usd"] is None
    assert db.codex_totals("today")["total_tokens"] == 130
    assert sum(r["total_tokens"] for r in db.codex_model_stats("all")) == 260
    assert sum(r["total_tokens"] for r in db.codex_channel_stats("all")) == 260


def test_batch_rollback_keeps_cursor(tmp_codex_db, codex_row):
    import pytest
    b = {"path": "fixture.jsonl", "rows": [codex_row()], "progress": {
        "offset": 20, "file_size": 20, "mtime_ns": 1,
        "content_fingerprint": "fixture", "event_mode": "token_count",
        "last_model": "m1", "model_revision": 0, "has_turn_context": True,
        "last_event_seq": 1, "last_token_usage_fingerprint": "fp1",
        "parser_version": 1, "updated_at": None},
        "warnings": []}
    assert db.commit_codex_batch(b) == 1
    c = db.get_db()
    c.execute("CREATE TRIGGER reject_codex_progress BEFORE UPDATE ON codex_file_progress "
              "BEGIN SELECT RAISE(ABORT, 'test'); END;")
    c.commit()
    b["rows"] = [codex_row("s:2")]
    b["progress"] = dict(b["progress"], offset=40, file_size=40, last_event_seq=2)
    with pytest.raises(Exception):
        db.commit_codex_batch(b)
    assert db.codex_totals("all")["request_count"] == 1
    assert db.get_codex_file_progress_all()["fixture.jsonl"]["offset"] == 20


# ---------------------------------------------------------------------------
# 简报 Step 4 末段要求的补充测试
# ---------------------------------------------------------------------------


def test_codex_empty_db_zero_counts_and_null_speed(tmp_codex_db):
    t = db.codex_totals("all")
    assert t["request_count"] == 0
    assert t["session_count"] == 0
    assert t["total_tokens"] == 0
    assert t["total_input_tokens"] == 0
    assert t["uncached_input_tokens"] == 0
    assert t["total_output_tokens"] == 0
    assert t["avg_tps"] is None and t["max_tps"] is None
    assert t["speed_samples"] == 0
    assert t["total_cost_usd"] is None  # NULL 不是 0
    assert t["hit_rate"] == 0
    daily = db.codex_daily(7)
    assert len(daily) == 7
    assert all(d["request_count"] == 0 and d["total_tokens"] == 0 for d in daily)
    assert all(d["avg_tps"] is None and d["total_cost_usd"] is None for d in daily)
    from datetime import date
    dates = [date.fromisoformat(d["date"]) for d in daily]
    assert all((b - a).days == 1 for a, b in zip(dates, dates[1:]))
    assert db.codex_records_page() == ([], 0)
    assert db.codex_session_stats_page() == ([], 0)
    assert db.codex_channel_stats("all") == []
    assert db.codex_model_stats("all") == []
    assert db.codex_last_import_at() is None


def test_codex_backfill_model_and_speed_no_count_increase(tmp_codex_db, codex_row):
    assert db.import_codex_usage([codex_row(model="")]) == 1
    assert db.codex_totals("all")["request_count"] == 1
    # 同 key 重放: 只补此前缺失的模型与速度, 不新增记录
    assert db.import_codex_usage([codex_row(model="gpt-5.1", speed_tps=42.0,
                                            speed_source="duration")]) == 0
    assert db.codex_totals("all")["request_count"] == 1
    records, total = db.codex_records_page()
    assert total == 1
    assert records[0]["model"] == "gpt-5.1"
    assert records[0]["speed_tps"] == 42.0
    assert records[0]["speed_source"] == "duration"
    row = db.get_db().execute(
        "SELECT model_revision_at FROM codex_usage WHERE id = 's:1'").fetchone()
    # 补模型时 model_revision_at = max(当前 epoch ms, 库内最大值 + 1) > 0
    assert row["model_revision_at"] > 0


def test_codex_model_switch_two_groups(tmp_codex_db, codex_row, local_iso):
    assert db.import_codex_usage([
        codex_row("s:1"),
        codex_row("s:2", started_at=local_iso(1), model="m2"),
    ]) == 2
    stats = db.codex_model_stats("all")
    assert len(stats) == 2
    assert {s["model"] for s in stats} == {"m1", "m2"}
    assert sum(s["total_tokens"] for s in stats) == 260


def test_codex_today_boundary(tmp_codex_db, codex_row, local_iso):
    # 昨天午间在"今天"自然日窗口之前, 今天午间在窗口之内
    assert db.import_codex_usage([
        codex_row("s:1", started_at=local_iso(1)),
        codex_row("s:2", started_at=local_iso(0)),
    ]) == 2
    today = db.codex_totals("today")
    assert today["request_count"] == 1
    assert today["total_tokens"] == 130
    records, total = db.codex_records_page(period="today")
    assert total == 1
    assert records[0]["source_record_id"] == "s:2"
    _, total_y = db.codex_records_page(period="yesterday")
    assert total_y == 1


def test_codex_records_pagination_90_no_overlap(tmp_codex_db, codex_row):
    rows = [codex_row(f"s:{i}") for i in range(1, 91)]
    assert db.import_codex_usage(rows) == 90
    seen: list[str] = []
    for page in (1, 2, 3):
        records, total = db.codex_records_page(page=page, page_size=30)
        assert total == 90
        assert len(records) == 30
        seen.extend(r["source_record_id"] for r in records)
    assert len(seen) == 90
    assert len(set(seen)) == 90


def test_codex_query_plan_uses_utc_index(tmp_codex_db, codex_row):
    assert db.import_codex_usage([codex_row()]) == 1
    plan = db.get_db().execute(
        "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM codex_usage"
        " WHERE datetime(started_at) >= datetime('2000-01-01 00:00:00')"
        " AND datetime(started_at) < datetime('2100-01-01 00:00:00')"
    ).fetchall()
    detail = " | ".join(r["detail"] for r in plan)
    assert "idx_codex_usage_utc" in detail


def test_codex_source_dir_loss_keeps_mirror(tmp_codex_db, codex_row):
    assert db.import_codex_usage([
        codex_row("s:1", file_path="fixture.jsonl"),
        codex_row("s:2", file_path="other.jsonl"),
    ]) == 2
    # 源目录丢失不触发镜像清理: 幸存文件的空批次/无批次都不删除历史记录
    progress = {"offset": 0, "file_size": 0, "mtime_ns": 0, "content_fingerprint": "",
                "event_mode": "token_count", "last_model": None, "model_revision": 0,
                "has_turn_context": False, "last_event_seq": 0,
                "last_token_usage_fingerprint": None, "parser_version": 1,
                "updated_at": None}
    assert db.commit_codex_batch(
        {"path": "fixture.jsonl", "rows": [], "progress": progress, "warnings": []}) == 0
    assert db.codex_totals("all")["request_count"] == 2
    assert db.codex_totals("all")["total_tokens"] == 260


def test_codex_mode_switch_rebuilds_in_one_tx(tmp_codex_db, codex_row, local_iso):
    progress = {"offset": 40, "file_size": 40, "mtime_ns": 1, "content_fingerprint": "fp-a",
                "event_mode": "token_count", "last_model": "m1", "model_revision": 0,
                "has_turn_context": True, "last_event_seq": 2,
                "last_token_usage_fingerprint": "fp1", "parser_version": 1,
                "updated_at": None}
    b1 = {"path": "fixture.jsonl",
          "rows": [codex_row("s:1"), codex_row("s:2", started_at=local_iso(1))],
          "progress": dict(progress), "warnings": []}
    assert db.commit_codex_batch(b1) == 2
    record = codex_row("s:9", event_mode="token_usage_record", event_seq=None,
                       response_id="resp-9", request_count_exact=True)
    b2 = {"path": "fixture.jsonl", "rows": [record],
          "progress": dict(progress, offset=88, file_size=88,
                           event_mode="token_usage_record",
                           last_event_seq=0, last_token_usage_fingerprint=None),
          "warnings": []}
    assert db.commit_codex_batch(b2) == 1
    # 同一事务删除该文件旧记录并重建: 无残留/错位记录
    t = db.codex_totals("all")
    assert t["request_count"] == 1
    assert t["total_tokens"] == 130
    records, total = db.codex_records_page(page_size=50)
    assert total == 1
    assert records[0]["source_record_id"] == "s:9"
    stale = db.get_db().execute(
        "SELECT COUNT(*) AS c FROM codex_usage WHERE event_mode = 'token_count'").fetchone()
    assert stale["c"] == 0


def test_codex_import_state_survives_reopen(tmp_codex_db):
    db.get_db()
    db.update_codex_import_state(last_success_at="2026-09-07T08:00:00Z",
                                 last_error="boom", warning_count=2)
    db.close_db()
    state = db.get_codex_import_state()
    assert state["last_success_at"] == "2026-09-07T08:00:00Z"
    assert state["last_error"] == "boom"
    assert state["warning_count"] == 2


# ---------------------------------------------------------------------------
# 任务上下文约束: 批次内部同 key 重复必须收敛为"文件顺序末条完整 usage 胜出",
# 且不得违反 UNIQUE 约束 (T1 相邻去重只看前一行, 非相邻重复由存储层收敛)
# ---------------------------------------------------------------------------


def test_codex_aggregate_fixed_keys(tmp_codex_db, codex_row):
    # 计划固定键清单: 所有 Codex 聚合结果使用同一 17 键集,
    # speed_source/cost_usd/total_cost_usd 恒 None、cost_available 恒 False
    assert db.import_codex_usage([codex_row()]) == 1
    fixed = {"request_count", "session_count", "total_tokens", "total_input_tokens",
             "uncached_input_tokens", "total_output_tokens", "total_reasoning_tokens",
             "cache_hit_tokens", "cache_write_tokens", "hit_rate", "avg_tps", "max_tps",
             "speed_samples", "speed_source", "cost_usd", "total_cost_usd",
             "cost_available"}
    t = db.codex_totals("all")
    assert set(t) == fixed
    assert t["speed_source"] is None
    assert t["cost_usd"] is None
    assert t["cost_available"] is False
    groups = db.codex_channel_stats("all") + db.codex_model_stats("all")
    assert len(groups) == 2
    for g in groups:
        assert fixed <= set(g)
        assert g["speed_source"] is None
        assert g["cost_usd"] is None
        assert g["cost_available"] is False
    # 会话分页复用同一构造路径, 聚合键集一致
    sessions, total = db.codex_session_stats_page()
    assert total == 1
    assert fixed <= set(sessions[0])
    assert sessions[0]["speed_source"] is None
    assert sessions[0]["cost_usd"] is None
    assert sessions[0]["cost_available"] is False
    # daily 补零行与数据行同键集
    for d in db.codex_daily(7):
        assert fixed <= set(d)


def test_codex_batch_internal_duplicate_record_last_wins(tmp_codex_db, codex_row):
    first = codex_row("s:1", event_mode="token_usage_record", event_seq=None,
                      response_id="r1", request_count_exact=True,
                      started_at="2026-09-07T01:00:00.000Z", total_tokens=100,
                      input_tokens=80, output_tokens=20, cache_read_tokens=10,
                      reasoning_tokens=2)
    last = codex_row("s:1", event_mode="token_usage_record", event_seq=None,
                     response_id="r1", request_count_exact=True,
                     started_at="2026-09-07T01:00:01.000Z", total_tokens=250,
                     input_tokens=200, output_tokens=50, cache_read_tokens=40,
                     reasoning_tokens=6)
    assert db.import_codex_usage([first, last]) == 1
    t = db.codex_totals("all")
    assert t["request_count"] == 1
    assert t["total_tokens"] == 250
    assert t["total_input_tokens"] == 200
    assert t["uncached_input_tokens"] == 160  # MAX(200-40, 0), 不累加首条
