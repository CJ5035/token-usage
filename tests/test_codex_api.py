import json
import time
from pathlib import Path

import pytest

from app import codex_api


def write_lines(path, events):
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")


def event(output=30, **extra):
    return {
        "timestamp": "2026-09-06T01:00:01Z", "type": "event_msg",
        "payload": {"type": "token_count", "info": {"last_token_usage": {
            "input_tokens": 100, "cached_input_tokens": 20,
            "output_tokens": output, "reasoning_output_tokens": 4,
            "total_tokens": 100 + output}}},
        **extra,
    }


def fresh_progress(**overrides):
    p = dict(offset=0, file_size=0, mtime_ns=0, content_fingerprint="",
             event_mode="", last_model=None, model_revision=0,
             has_turn_context=False, last_event_seq=0,
             last_token_usage_fingerprint=None,
             parser_version=codex_api.PARSER_VERSION, updated_at=None)
    p.update(overrides)
    return p


def test_context_and_incremental_id(tmp_path):
    p = tmp_path / "rollout-00000000-0000-0000-0000-000000000001.jsonl"
    ctx = {"type": "turn_context", "payload": {"model": "m1"}}
    write_lines(p, [ctx, event()])
    result = codex_api.parse_session_file(p, fresh_progress())
    rows = result["rows"]
    assert (result["last_event_seq"], result["last_model"], rows[0]["total_tokens"]) == (1, "m1", 130)
    assert rows[0]["speed_tps"] is None
    with p.open("a", encoding="utf-8") as out:
        out.write(json.dumps(event(output=40)) + "\n")
    cont = fresh_progress(offset=result["offset"], file_size=result["offset"],
                          event_mode=result["event_mode"], last_model=result["last_model"],
                          model_revision=result["model_revision"],
                          has_turn_context=result["has_turn_context"],
                          last_event_seq=result["last_event_seq"],
                          last_token_usage_fingerprint=result["last_token_usage_fingerprint"])
    newer = codex_api.parse_session_file(p, cont, snapshot=p.read_bytes())
    assert len(newer["rows"]) == 1 and newer["last_event_seq"] == 2
    assert newer["last_model"] == "m1"
    assert newer["rows"][0]["id"] != rows[0]["id"] and newer["offset"] == p.stat().st_size


def test_partial_line_and_bad_json(tmp_path):
    p = tmp_path / "rollout-x.jsonl"
    raw = json.dumps(event()).encode()
    p.write_bytes(b"broken\n" + raw)
    result = codex_api.parse_session_file(p, fresh_progress())
    assert (result["rows"], result["offset"], result["last_event_seq"], result["last_model"]) == ([], 7, 0, None)
    with p.open("ab") as out:
        out.write(b"\n")
    cont = fresh_progress(offset=result["offset"], last_event_seq=result["last_event_seq"],
                          event_mode=result["event_mode"], last_model=result["last_model"])
    result = codex_api.parse_session_file(p, cont, snapshot=p.read_bytes())
    assert len(result["rows"]) == 1 and result["last_event_seq"] == 1 and result["offset"] == p.stat().st_size


def test_token_usage_record_mode_and_last_duplicate_wins(tmp_path):
    p = tmp_path / "rollout-00000000-0000-0000-0000-000000000002.jsonl"
    def record(output, response_id="resp-1"):
        return {"timestamp": "2026-09-06T01:00:01Z", "type": "token_usage_record",
                "payload": {"response_id": response_id, "usage": {
                    "input_tokens": 100, "cached_input_tokens": 20,
                    "cache_write_input_tokens": 3, "output_tokens": output,
                    "reasoning_output_tokens": 4, "total_tokens": 100 + output}},}
    write_lines(p, [record(30), record(40)])
    result = codex_api.parse_session_file(p, fresh_progress())
    assert result["event_mode"] == "token_usage_record"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["response_id"] == "resp-1"
    assert result["rows"][0]["output_tokens"] == 40
    assert result["rows"][0]["request_count_exact"] is True


def test_root_precedence(monkeypatch, tmp_path):
    monkeypatch.setenv("ZBAR_CODEX_HOME", str(tmp_path / "fallback"))
    monkeypatch.setenv("GOUSAGE_CODEX_HOME", str(tmp_path / "chosen"))
    assert codex_api.sessions_dir() == tmp_path / "chosen" / "sessions"


def test_shrink_resets_context(monkeypatch, tmp_path):
    p = tmp_path / "rollout-x.jsonl"
    write_lines(p, [event()])
    size = p.stat().st_size
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p])
    batches = codex_api.import_incremental({str(p): {
        "offset": size + 100, "file_size": size + 100, "mtime_ns": 0,
        "content_fingerprint": "", "event_mode": "token_count",
        "last_model": "old", "model_revision": 0, "has_turn_context": False,
        "last_event_seq": 99, "last_token_usage_fingerprint": None,
        "parser_version": codex_api.PARSER_VERSION, "updated_at": None}}, force=True)
    b = batches[0]
    assert b["progress"]["offset"] == size
    assert b["progress"]["last_event_seq"] == 1
    assert b["rows"][0]["model"] == ""


def test_cache_and_reasoning_are_subsets():
    u = codex_api.normalize_usage({
        "input_tokens": 100, "cached_input_tokens": 20,
        "output_tokens": 30, "reasoning_output_tokens": 4})
    assert u["total_tokens"] == 130


@pytest.mark.parametrize("duration,expected", [
    (None, None), (0, None), (-1, None), (True, None),
    ("2000", None), (float("nan"), None), (2000, 50.0)])
def test_speed_requires_duration(duration, expected):
    assert codex_api.speed_from_duration(100, duration) == expected


# ---------------------------------------------------------------------------
# 以下为简报 Step 4 要求的 12 项补充测试 (+ 节流行为)
# ---------------------------------------------------------------------------

def ctx(model="m1"):
    return {"type": "turn_context", "payload": {"model": model}}


def record(output=30, response_id="resp-1"):
    payload = {"usage": {
        "input_tokens": 100, "cached_input_tokens": 20,
        "cache_write_input_tokens": 3, "output_tokens": output,
        "reasoning_output_tokens": 4, "total_tokens": 100 + output}}
    if response_id is not None:
        payload["response_id"] = response_id
    return {"timestamp": "2026-09-06T01:00:01Z",
            "type": "token_usage_record", "payload": payload}


def append_lines(path, events):
    with path.open("a", encoding="utf-8") as out:
        out.write("".join(json.dumps(e) + "\n" for e in events))


def rollout(tmp_path, n):
    return tmp_path / f"rollout-00000000-0000-0000-0000-{n:012d}.jsonl"


def test_unchanged_file_produces_no_batch(monkeypatch, tmp_path):
    p = rollout(tmp_path, 11)
    write_lines(p, [ctx(), event(30)])
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p])
    progress = {str(p): fresh_progress()}
    first = codex_api.import_incremental(progress, force=True)
    assert len(first) == 1 and len(first[0]["rows"]) == 1
    progress[str(p)] = first[0]["progress"]
    assert codex_api.import_incremental(progress, force=True) == []


def test_same_size_rewrite_rebuilds(monkeypatch, tmp_path):
    p = rollout(tmp_path, 12)
    write_lines(p, [ctx(), event(30)])
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p])
    progress = {str(p): fresh_progress()}
    first = codex_api.import_incremental(progress, force=True)
    assert len(first[0]["rows"]) == 1
    progress[str(p)] = first[0]["progress"]
    write_lines(p, [ctx(), event(40)])  # 同字节数的内容替换
    assert p.stat().st_size == first[0]["progress"]["file_size"]
    batches = codex_api.import_incremental(progress, force=True)
    assert len(batches) == 1
    b = batches[0]
    assert len(b["rows"]) == 1 and b["rows"][0]["output_tokens"] == 40
    assert b["progress"]["last_event_seq"] == 1  # 重建后序号从头计数
    assert b["progress"]["offset"] == p.stat().st_size


def test_bad_file_alongside_good_file(monkeypatch, tmp_path):
    bad = rollout(tmp_path, 13)
    good = rollout(tmp_path, 14)
    write_lines(bad, [event(30)])
    write_lines(good, [ctx(), event(30)])
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [bad, good])
    real_read_snapshot = codex_api.read_snapshot

    def fake_read_snapshot(path):
        if path == bad:
            raise OSError("permission denied")
        return real_read_snapshot(path)

    monkeypatch.setattr(codex_api, "read_snapshot", fake_read_snapshot)
    batches = codex_api.import_incremental({}, force=True)
    assert [b["path"] for b in batches] == [str(good)]
    assert len(batches[0]["rows"]) == 1
    assert batches[0]["rows"][0]["total_tokens"] == 130
    assert len(codex_api.last_scan_errors) == 1
    assert str(bad) in codex_api.last_scan_errors[0]
    assert "permission denied" in codex_api.last_scan_errors[0]


def test_inaccessible_subdir_recorded_not_blocking(monkeypatch, tmp_path):
    # sessions 下含不可访问子目录: 不阻塞其余可读文件, 错误记入 last_scan_errors
    root = tmp_path / "sessions"
    day = root / "2026" / "09" / "06"
    day.mkdir(parents=True)
    good = day / "rollout-00000000-0000-0000-0000-000000000031.jsonl"
    write_lines(good, [ctx(), event(30)])
    locked = root / "locked"
    locked.mkdir()
    real_iterdir = Path.iterdir

    def fake_iterdir(self):
        if self == locked:
            raise PermissionError(13, "Permission denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", fake_iterdir)
    monkeypatch.setenv("GOUSAGE_CODEX_HOME", str(tmp_path))
    batches = codex_api.import_incremental({}, force=True)
    assert [b["path"] for b in batches] == [str(good)]
    assert len(batches[0]["rows"]) == 1
    assert batches[0]["rows"][0]["total_tokens"] == 130
    assert len(codex_api.last_scan_errors) == 1
    assert str(locked) in codex_api.last_scan_errors[0]
    assert "Permission denied" in codex_api.last_scan_errors[0]


def test_empty_model_backfill_across_and_within_batch(monkeypatch, tmp_path):
    # 同批次内回填: token_count 先于 turn_context, 首个模型到达时补先前空模型行
    p1 = rollout(tmp_path, 15)
    result = codex_api.parse_session_file(
        p1, fresh_progress(), snapshot=b"".join(
            (json.dumps(e) + "\n").encode() for e in [event(30), ctx(), event(40)]))
    assert [row["model"] for row in result["rows"]] == ["m1", "m1"]
    assert [row["model_revision_at"] for row in result["rows"]] == [0, 1]
    assert (result["rows"][0]["event_seq"], result["rows"][1]["event_seq"]) == (1, 2)
    # 跨批次: 游标无 last_model 且文件增长 → 从头重放一次, 恢复早期空模型行
    p2 = rollout(tmp_path, 16)
    write_lines(p2, [event(30)])
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p2])
    progress = {str(p2): fresh_progress()}
    first = codex_api.import_incremental(progress, force=True)
    assert first[0]["rows"][0]["model"] == "" and first[0]["progress"]["last_model"] is None
    progress[str(p2)] = first[0]["progress"]
    append_lines(p2, [ctx(), event(40)])
    batches = codex_api.import_incremental(progress, force=True)
    assert len(batches) == 1
    b = batches[0]
    assert [(row["event_seq"], row["model"]) for row in b["rows"]] == [(1, "m1"), (2, "m1")]
    assert (b["progress"]["last_model"], b["progress"]["model_revision"]) == ("m1", 1)


def test_fingerprint_append_does_not_reparse_from_head(monkeypatch, tmp_path):
    p = rollout(tmp_path, 17)
    write_lines(p, [ctx(), event(30)])
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p])
    progress = {str(p): fresh_progress()}
    first = codex_api.import_incremental(progress, force=True)
    assert len(first[0]["rows"]) == 1
    saved = first[0]["progress"]
    progress[str(p)] = saved
    append_lines(p, [event(40)])
    start_offsets = []
    real_parse = codex_api.parse_session_file

    def spy(path, prog=None, snapshot=None):
        start_offsets.append(None if prog is None else prog.get("offset"))
        return real_parse(path, prog, snapshot)

    monkeypatch.setattr(codex_api, "parse_session_file", spy)
    batches = codex_api.import_incremental(progress, force=True)
    # 快速路径: 从保存游标续读, 不从文件头重扫
    assert start_offsets == [saved["offset"]]
    assert len(batches) == 1
    b = batches[0]
    # 批次只含新增字节产出的行 (重扫会带出 2 行)
    assert len(b["rows"]) == 1 and b["rows"][0]["output_tokens"] == 40
    assert b["rows"][0]["event_seq"] == 2 and b["rows"][0]["model"] == "m1"
    assert b["progress"]["offset"] == p.stat().st_size


def test_stale_parser_version_rebuilds(monkeypatch, tmp_path):
    p = rollout(tmp_path, 18)
    write_lines(p, [ctx(), event(30)])
    data = p.read_bytes()
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p])
    known = fresh_progress(
        offset=len(data), file_size=len(data),
        content_fingerprint=codex_api.sha256_prefix(data, len(data)),
        event_mode="token_count", last_model="m1", model_revision=1,
        has_turn_context=True, last_event_seq=1, parser_version=0)
    batches = codex_api.import_incremental({str(p): known}, force=True)
    assert len(batches) == 1
    b = batches[0]
    # 游标本已到文件尾 (未过期则不产批次), 过期触发重建并重新产出全部行
    assert len(b["rows"]) == 1 and b["rows"][0]["output_tokens"] == 30
    assert b["progress"]["parser_version"] == codex_api.PARSER_VERSION
    assert b["progress"]["last_event_seq"] == 1


def test_adjacent_duplicate_seq_still_increments(tmp_path):
    p = rollout(tmp_path, 19)
    write_lines(p, [ctx(), event(30), event(30)])
    result = codex_api.parse_session_file(p, fresh_progress())
    assert len(result["rows"]) == 1
    assert result["rows"][0]["event_seq"] == 1
    assert result["rows"][0]["id"] == "codex:00000000-0000-0000-0000-000000000019:1"
    assert result["rows"][0]["total_tokens"] == 130
    # 去重跳过入库但 last_event_seq 照常递增; 去重后求和 == 会话最终累计 (需求 §8)
    assert result["last_event_seq"] == 2
    assert sum(row["total_tokens"] for row in result["rows"]) == 130
    assert result["rows"][0]["request_count_exact"] is False


def test_dedupe_fingerprint_survives_batch_boundary(monkeypatch, tmp_path):
    p = rollout(tmp_path, 20)
    write_lines(p, [ctx(), event(30)])
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p])
    progress = {str(p): fresh_progress()}
    first = codex_api.import_incremental(progress, force=True)
    assert len(first[0]["rows"]) == 1
    saved = first[0]["progress"]
    progress[str(p)] = saved
    append_lines(p, [event(30)])  # 批次边界另一侧的完全相同五元组
    batches = codex_api.import_incremental(progress, force=True)
    assert len(batches) == 1
    b = batches[0]
    assert b["rows"] == []  # 重复事件仍被跳过
    assert b["progress"]["last_event_seq"] == 2
    assert b["progress"]["last_token_usage_fingerprint"] == saved["last_token_usage_fingerprint"]
    assert b["progress"]["offset"] == p.stat().st_size


def test_record_without_response_id_skipped_with_warning(tmp_path):
    p = rollout(tmp_path, 21)
    write_lines(p, [record(30, response_id=None), record(40)])
    result = codex_api.parse_session_file(p, fresh_progress())
    assert result["event_mode"] == "token_usage_record"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["response_id"] == "resp-1"
    assert result["rows"][0]["output_tokens"] == 40
    assert any("response_id" in w for w in result["warnings"])


def test_invalid_or_missing_timestamp_skipped(tmp_path):
    p = rollout(tmp_path, 22)
    bad_ts = event(30)
    bad_ts["timestamp"] = "not-a-time"
    no_ts = event(40)
    del no_ts["timestamp"]
    write_lines(p, [ctx(), bad_ts, no_ts, event(50)])
    result = codex_api.parse_session_file(p, fresh_progress())
    assert len(result["rows"]) == 1
    assert result["rows"][0]["output_tokens"] == 50
    assert result["last_event_seq"] == 1  # 无效事件不递增
    assert len(result["warnings"]) >= 2


def test_zero_details_nonzero_total_kept(tmp_path):
    p = rollout(tmp_path, 23)
    old_format = event(output=0)
    old_format["payload"]["info"]["last_token_usage"] = {
        "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
        "reasoning_output_tokens": 0, "total_tokens": 290}
    write_lines(p, [old_format])
    result = codex_api.parse_session_file(p, fresh_progress())
    assert len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["total_tokens"] == 290  # 按日志总量入库, 不用明细反推
    assert (row["input_tokens"], row["output_tokens"]) == (0, 0)


def test_mode_switch_in_appended_bytes_rebuilds(monkeypatch, tmp_path):
    p = rollout(tmp_path, 24)
    write_lines(p, [ctx(), event(30)])
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [p])
    progress = {str(p): fresh_progress()}
    first = codex_api.import_incremental(progress, force=True)
    assert first[0]["progress"]["event_mode"] == "token_count"
    progress[str(p)] = first[0]["progress"]
    append_lines(p, [record(50, response_id="resp-9")])
    batches = codex_api.import_incremental(progress, force=True)
    assert len(batches) == 1
    b = batches[0]
    # 模式切换触发从头重建; 文件级唯一模式: 重建批次只含 record 行
    # (token_count 事件被预扫描判定忽略, 不与 record 双计, 需求 §二/§六/§八)
    assert [(row["event_mode"], row["total_tokens"]) for row in b["rows"]] == [
        ("token_usage_record", 150)]
    assert b["rows"][0]["response_id"] == "resp-9"
    assert b["rows"][0]["request_count_exact"] is True
    assert b["progress"]["event_mode"] == "token_usage_record"
    assert b["progress"]["offset"] == p.stat().st_size


def test_mixed_file_first_scan_uses_record_mode_only(tmp_path):
    # 需求 §二/§六/§八 文件级唯一模式: 混合文件首扫只按 record 模式产出,
    # token_count 事件不产行也不推进序号 (不得两种模式同时计入)
    p = rollout(tmp_path, 25)
    write_lines(p, [ctx(), event(30), record(40, response_id="resp-1"), event(50)])
    result = codex_api.parse_session_file(p, fresh_progress())
    assert result["event_mode"] == "token_usage_record"
    assert [(row["event_mode"], row["response_id"], row["total_tokens"])
            for row in result["rows"]] == [("token_usage_record", "resp-1", 140)]
    assert result["last_event_seq"] == 0
    assert result["last_token_usage_fingerprint"] is not None


def test_record_mode_fast_path_ignores_appended_token_count(tmp_path):
    # 快速路径信任持久化 event_mode: record 模式下追加 token_count 字节
    # 不产行、序号不推进, offset 照常推进 (需求 §二/§六/§八)
    p = rollout(tmp_path, 26)
    write_lines(p, [record(30, response_id="resp-1")])
    result = codex_api.parse_session_file(p, fresh_progress())
    assert result["event_mode"] == "token_usage_record"
    cont = fresh_progress(offset=result["offset"], file_size=result["offset"],
                          event_mode=result["event_mode"],
                          last_event_seq=result["last_event_seq"],
                          last_token_usage_fingerprint=result["last_token_usage_fingerprint"])
    append_lines(p, [event(40)])
    newer = codex_api.parse_session_file(p, cont, snapshot=p.read_bytes())
    assert newer["rows"] == []
    assert newer["last_event_seq"] == cont["last_event_seq"]
    assert newer["event_mode"] == "token_usage_record"
    assert newer["offset"] == p.stat().st_size


def test_import_throttled_without_force(monkeypatch):
    monkeypatch.setattr(codex_api, "_last_import_at", time.monotonic())
    monkeypatch.setattr(codex_api, "scan_session_files", lambda: [])
    assert codex_api.import_incremental({}) == []
