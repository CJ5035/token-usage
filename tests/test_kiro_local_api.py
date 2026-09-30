"""kiro_local_api: Kiro CLI 会话侧车解析 (只读 ~/.kiro/sessions/cli/*.json)."""
import json
import os

import pytest

from app import kiro_local_api as kla


def _turn(end="2026-09-24T09:54:18.690299400Z", credits=(1.5, 2.25), reqs=2, secs=90,
          model="claude-opus-5", **extra):
    turn = {
        "message_ids": ["m-1", "m-2"],
        "total_request_count": reqs,
        "turn_duration": {"secs": secs, "nanos": 500_000_000},
        "end_timestamp": end,
        "input_token_count": 0, "output_token_count": 0,
        "cache_read_input_token_count": 0, "cache_write_input_token_count": 0,
        "model": model,
        "final_context_usage_percentage": 31.24,
        "metering_usage": [{"value": v, "unit": "credit", "unitPlural": "credits"} for v in credits],
        "result": {"Ok": {"content": [{"kind": "text", "data": "SECRET_REPLY_TEXT"}]}},
    }
    turn.update(extra)
    return turn


def _write_session(root, sid="sess-1", turns=None, model_id="claude-opus-5"):
    doc = {
        "session_id": sid, "cwd": "C:\\SECRET_CWD", "title": "SECRET_PROMPT_TITLE",
        "created_at": "2026-09-24T09:00:00Z", "updated_at": "2026-09-24T10:00:00Z",
        "session_state": {
            "version": "v1",
            "conversation_metadata": {"user_turn_metadatas": turns if turns is not None else [_turn()]},
            "rts_model_state": {"model_info": {"model_id": model_id, "context_window_tokens": 1000000}},
        },
    }
    path = root / f"{sid}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    root = tmp_path / "kiro_sessions"
    root.mkdir()
    monkeypatch.setattr(kla, "KIRO_SESSIONS_DIR", root)
    monkeypatch.setattr(kla, "_last_import_at", None)
    return root


_ROW_KEYS = {"dedupe_key", "session_id", "model", "started_at", "ended_at", "duration_ms",
             "request_count", "credits", "cost_raw", "context_pct", "file_path"}


def test_parse_turn_row_contract(sessions):
    rows, skipped = kla.parse_session_file(_write_session(sessions))
    assert skipped == 0 and len(rows) == 1
    row = rows[0]
    assert set(row) == _ROW_KEYS          # 无任何 *_tokens 键: 上游不下发 token, 不落库
    assert row["dedupe_key"] == "sess-1:2026-09-24T09:54:18.690299400Z"
    assert row["session_id"] == "sess-1"
    assert row["model"] == "claude-opus-5"
    assert row["credits"] == pytest.approx(3.75)
    assert row["cost_raw"] == 15_000_000        # 3.75 credits × 0.04 USD × 1e8
    assert row["request_count"] == 2
    assert row["duration_ms"] == 90_500
    assert row["ended_at"] == "2026-09-24T09:54:18.690Z"
    assert row["started_at"] == "2026-09-24T09:52:48.190Z"   # end − 90.5s
    assert row["context_pct"] == pytest.approx(31.24)


def test_missing_metering_is_skipped_but_empty_list_is_real_zero(sessions):
    no_meter = _turn(end="2026-09-24T10:00:00Z")
    del no_meter["metering_usage"]
    empty = _turn(end="2026-09-24T10:05:00Z", credits=())
    rows, skipped = kla.parse_session_file(_write_session(sessions, turns=[no_meter, empty]))
    assert skipped == 1
    assert [r["credits"] for r in rows] == [0.0]
    assert rows[0]["cost_raw"] == 0


def test_turn_without_end_timestamp_is_skipped(sessions):
    bad = _turn()
    bad["end_timestamp"] = None
    rows, skipped = kla.parse_session_file(
        _write_session(sessions, turns=[bad, _turn(end="2026-09-24T11:00:00Z")]))
    assert skipped == 1 and len(rows) == 1


def test_non_credit_units_ignored_but_invalid_credit_is_unknown(sessions):
    t = _turn(credits=(1.0,))
    t["metering_usage"] += [{"value": 99, "unit": "token", "unitPlural": "tokens"},
                            {"value": -5, "unit": "credit"}, {"value": "7", "unit": "credit"},
                            {"value": True, "unit": "credit"}]
    rows, skipped = kla.parse_session_file(_write_session(sessions, turns=[t]))
    assert rows == [] and skipped == 1


def test_model_falls_back_to_session_model_then_auto(sessions):
    t1 = _turn(end="2026-09-24T12:00:00Z")
    del t1["model"]
    rows, _ = kla.parse_session_file(
        _write_session(sessions, sid="a", turns=[t1], model_id="claude-sonnet-5"))
    assert rows[0]["model"] == "claude-sonnet-5"
    t2 = _turn(end="2026-09-24T12:00:00Z")
    del t2["model"]
    rows, _ = kla.parse_session_file(_write_session(sessions, sid="b", turns=[t2], model_id=None))
    assert rows[0]["model"] == "auto"


def test_rows_never_carry_conversation_content(sessions):
    rows, _ = kla.parse_session_file(_write_session(sessions))
    dumped = json.dumps(rows, ensure_ascii=False)
    for secret in ("SECRET_PROMPT_TITLE", "SECRET_REPLY_TEXT", "SECRET_CWD"):
        assert secret not in dumped


def test_scan_ignores_jsonl_and_subdirectories(sessions):
    _write_session(sessions, sid="x")
    (sessions / "x.jsonl").write_text('{"kind":"Prompt"}\n', encoding="utf-8")
    (sessions / "x.lock").write_text("1", encoding="utf-8")
    sub = sessions / "x"
    sub.mkdir()
    (sub / "nested.json").write_text("{}", encoding="utf-8")
    assert [p.name for p in kla.scan_session_files()] == ["x.json"]


def test_import_incremental_skips_unchanged_and_rereads_changed(sessions):
    path = _write_session(sessions)
    first = kla.import_incremental({}, force=True)
    assert len(first) == 1
    batch = first[0]
    assert batch["path"] == str(path) and len(batch["rows"]) == 1 and batch["skipped"] == 0
    progress = {batch["path"]: (batch["mtime_ns"], batch["size"])}
    assert kla.import_incremental(progress, force=True) == []
    _write_session(sessions, turns=[_turn(), _turn(end="2026-09-24T13:00:00Z")])
    later = batch["mtime_ns"] + 1_000_000_000
    os.utime(path, ns=(later, later))
    again = kla.import_incremental(progress, force=True)
    assert len(again) == 1 and len(again[0]["rows"]) == 2


def test_import_incremental_throttles_unless_forced(sessions):
    _write_session(sessions)
    assert len(kla.import_incremental({})) == 1
    assert kla.import_incremental({}) == []           # 5 秒节流窗口内
    assert len(kla.import_incremental({}, force=True)) == 1


def test_corrupt_file_is_skipped_without_aborting(sessions):
    (sessions / "broken.json").write_text("{not json", encoding="utf-8")
    _write_session(sessions, sid="ok")
    batches = kla.import_incremental({}, force=True)
    assert [os.path.basename(b["path"]) for b in batches] == ["ok.json"]


def test_sessions_dir_exists_reflects_directory(sessions, tmp_path, monkeypatch):
    assert kla.sessions_dir_exists() is True
    monkeypatch.setattr(kla, "KIRO_SESSIONS_DIR", tmp_path / "nope")
    assert kla.sessions_dir_exists() is False
    assert kla.scan_session_files() == []

def test_invalid_metering_is_unknown():
    assert kla._credits([{'unit':'credit', 'value':'bad'}]) is None
