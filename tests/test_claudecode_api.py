"""claudecode_api.py 单测: 文件发现/行过滤/去重键/token 秒速/渠道判定/增量续读/节流.

全部走临时目录 + monkeypatch (CLAUDE_PROJECTS/CLAUDE_SETTINGS 指向 tmp_path,
节流模块变量重置), 不读本机真实 ~/.claude 文件.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import claudecode_api

# 启用时刻基准 (epoch ms): 1750000000000 = 2025-06-15T15:06:40.000Z
ENABLED_TS = 1_750_000_000_000
TS_BEFORE = "2025-06-15T15:06:39.000Z"   # < ENABLED_TS
TS_AFTER = "2025-06-15T15:06:41.000Z"    # > ENABLED_TS


# ---------------------------------------------------------------------------
# fixture 与测试数据工具
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def cc_projects(tmp_path, monkeypatch):
    """伪造 ~/.claude: projects 目录与 settings.json 路径指向临时目录;
    并重置模块级节流变量 (进出各一次, 防用例间串扰)."""
    projects = tmp_path / "claude" / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(claudecode_api, "CLAUDE_PROJECTS", projects)
    monkeypatch.setattr(claudecode_api, "CLAUDE_SETTINGS",
                        tmp_path / "claude" / "settings.json")
    claudecode_api._last_import_at = None
    yield projects
    claudecode_api._last_import_at = None


_UNSET = object()


def _usage(output_tokens, input_tokens=10):
    """构造 usage dict (cache 两项 0, 便于按 output 手算秒速)."""
    return {"input_tokens": input_tokens, "output_tokens": output_tokens,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def _line(type_="assistant", msg_id="msg_1", model="claude-sonnet-4-5",
          ts=TS_AFTER, usage=_UNSET, duration_ms=1000, cwd="C:\\proj"):
    """构造一条 JSONL 记录; msg_id/ts/usage 为 None 表示键缺失 (显式 null)."""
    rec = {"type": type_, "cwd": cwd}
    if ts is not None:
        rec["timestamp"] = ts
    msg = {}
    if msg_id is not None:
        msg["id"] = msg_id
    msg["model"] = model
    msg["usage"] = usage if usage is not _UNSET else {
        "input_tokens": 10, "output_tokens": 100,
        "cache_read_input_tokens": 200, "cache_creation_input_tokens": 5,
    }
    if duration_ms is not None:
        msg["durationMs"] = duration_ms
    rec["message"] = msg
    return json.dumps(rec)


def _write_jsonl(path: Path, lines, mode="w"):
    """写 JSONL; lines 元素为 str (utf-8) 或 bytes (脏字节用)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode + "b") as f:
        for line in lines:
            f.write(line.encode("utf-8") if isinstance(line, str) else line)
            f.write(b"\n")


def _parse(path: Path, offset=0):
    return claudecode_api.parse_session_file(path, offset)


# ---------------------------------------------------------------------------
# 1. 文件发现 (subagents / 深度 5 / 排序稳定 / 目录缺失)
# ---------------------------------------------------------------------------

def test_scan_finds_main_and_subagent_files(cc_projects):
    _write_jsonl(cc_projects / "proj-a" / "s1.jsonl", [])
    _write_jsonl(cc_projects / "proj-a" / "s1" / "subagents" / "agent-1.jsonl", [])
    _write_jsonl(cc_projects / "proj-b" / "s2.jsonl", [])
    files = claudecode_api.scan_session_files()
    assert len(files) == 3
    assert {f.name for f in files} == {"s1.jsonl", "agent-1.jsonl", "s2.jsonl"}


def test_scan_depth_limit_is_five(cc_projects):
    deep = cc_projects / "a" / "b" / "c" / "d" / "e"          # 第 5 层 → 收集
    _write_jsonl(deep / "ok.jsonl", [])
    _write_jsonl(deep / "f" / "too-deep.jsonl", [])           # 第 6 层 → 不收集
    assert [f.name for f in claudecode_api.scan_session_files()] == ["ok.jsonl"]


def test_scan_order_stable(cc_projects):
    for name in ("z.jsonl", "a.jsonl", "m.jsonl"):
        _write_jsonl(cc_projects / name, [])
    first = claudecode_api.scan_session_files()
    second = claudecode_api.scan_session_files()
    assert first == second
    assert [f.name for f in first] == ["a.jsonl", "m.jsonl", "z.jsonl"]


def test_scan_missing_projects_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(claudecode_api, "CLAUDE_PROJECTS",
                        tmp_path / "nonexistent")
    assert claudecode_api.scan_session_files() == []


# ---------------------------------------------------------------------------
# 2. 行过滤 (synthetic / 0 值 / 无 timestamp / 非法 JSON / 脏字节; 偏移照推进)
# ---------------------------------------------------------------------------

def test_filter_skips_non_assistant_lines(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(type_="user", msg_id="u1"),
                     _line(msg_id="keep"),
                     _line(type_="summary", msg_id="s1")])
    rows, offset = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["keep"]
    assert offset == f.stat().st_size          # 跳过的行偏移照常推进


def test_filter_skips_synthetic_and_blank_model(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="a", model="<synthetic>"),
                     _line(msg_id="b", model=""),
                     _line(msg_id="c", model=None),
                     _line(msg_id="keep")])
    rows, _ = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["keep"]


def test_filter_skips_zero_or_missing_usage(tmp_path):
    zero = {"input_tokens": 0, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="z1", usage=zero),          # 四项和 0 (流式占位)
                     _line(msg_id="z2", usage={"input_tokens": 1}),  # 和 1 > 0 → 保留
                     _line(msg_id="z3", usage=None),           # usage 缺失
                     _line(msg_id="keep")])
    rows, offset = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["z2", "keep"]
    assert offset == f.stat().st_size


def test_filter_skips_bad_timestamp(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="t1", ts=None),
                     _line(msg_id="t2", ts="not-a-time"),
                     _line(msg_id="keep")])
    rows, offset = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["keep"]
    assert offset == f.stat().st_size          # 无 timestamp 跳过但偏移仍推进


def test_filter_skips_invalid_json_and_dirty_bytes(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [b"not json at all",
                     b'{"type":"assistant","message":{"\xff\xfe"}}',
                     _line(msg_id="keep")])
    rows, offset = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["keep"]   # 脏字节行/坏 JSON 行均跳过
    assert offset == f.stat().st_size


# ---------------------------------------------------------------------------
# 3. dedupe key 与 session_id
# ---------------------------------------------------------------------------

def test_dedupe_key_message_id_global(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="msgAAA"), _line(msg_id="msgBBB")])
    rows, _ = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["msgAAA", "msgBBB"]


def test_dedupe_key_fallback_sequence_skips_filtered(tmp_path):
    # 文件名 stem 决定 session_id → "sess|<序号>"; 序号只对通过过滤的行递增
    # (全局 id 行也占序号 — 照 zai 语义, 序号 = 通过过滤的行计数)
    f = tmp_path / "sess.jsonl"
    _write_jsonl(f, [
        _line(msg_id="bad|id"),               # id 含 "|" → seq=1 → sess|1
        _line(type_="user"),                  # 不通过过滤 → 不递增
        _line(msg_id=None),                   # 无 id → seq=2 → sess|2
        _line(msg_id="msg_ok"),               # 全局键 (seq=3 被占)
        _line(msg_id="", model="claude-3"),   # 空 id → seq=4 → sess|4
    ])
    rows, _ = _parse(f)
    assert [r["dedupe_key"] for r in rows] == [
        "sess|1", "sess|2", "msg_ok", "sess|4"]


def test_session_id_subagent_uses_parent_dir(tmp_path):
    sub = tmp_path / "proj" / "conv-uuid" / "subagents" / "agent-x.jsonl"
    _write_jsonl(sub, [_line(msg_id="m1")])
    rows, _ = _parse(sub)
    assert rows[0]["session_id"] == "conv-uuid"
    main = tmp_path / "proj" / "conv-uuid.jsonl"
    _write_jsonl(main, [_line(msg_id="m2")])
    rows, _ = _parse(main)
    assert rows[0]["session_id"] == "conv-uuid"      # 主会话 = 文件名 stem


# ---------------------------------------------------------------------------
# 4. 产出行形状与 compute_total
# ---------------------------------------------------------------------------

def test_compute_total_sums_four_fields():
    assert claudecode_api.compute_total({
        "input_tokens": 10, "output_tokens": 100,
        "cache_read_input_tokens": 200, "cache_creation_input_tokens": 5,
    }) == 315
    assert claudecode_api.compute_total({}) == 0
    assert claudecode_api.compute_total({"input_tokens": True}) == 0  # bool 排除


def test_row_shape_and_timestamp_roundtrip(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="m1", ts="2026-06-12T19:12:00.759Z",
                           duration_ms=None)])
    rows, _ = _parse(f)
    r = rows[0]
    # 13 键契约, 不含 channel (盖章在 import_incremental)
    assert set(r) == {"dedupe_key", "session_id", "project_path", "model",
                      "started_at", "input_tokens", "output_tokens",
                      "cache_read_tokens", "cache_write_tokens",
                      "total_tokens", "duration_ms", "speed_tps", "file_path"}
    assert r["started_at"] == "2026-06-12T19:12:00.759Z"  # 毫秒精度 + Z 后缀
    assert r["total_tokens"] == 315
    assert r["duration_ms"] is None                        # 旧版 CLI 行无 durationMs
    assert r["speed_tps"] is None                          # 单行且无 durationMs
    assert r["project_path"] == "C:\\proj"
    assert r["file_path"] == str(f)


def test_row_duration_ms_kept_when_present(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="m1", duration_ms=1757)])
    rows, _ = _parse(f)
    assert rows[0]["duration_ms"] == 1757


# ---------------------------------------------------------------------------
# 4b. token 秒速 (同文件内按 message.id 分组, 值附着该 id 末行;
#     阈值: 窗口 >=100ms、输出 >=10 tok、速率 <=500 tok/s)
# ---------------------------------------------------------------------------

def test_speed_duration_ms_path(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="m1", duration_ms=1000, usage=_usage(100))])
    rows, _ = _parse(f)
    assert rows[0]["speed_tps"] == 100.0           # 100*1000/1000


def test_speed_single_row_without_duration_is_none(tmp_path):
    # 真机口径: 当前 CLI 不写 durationMs, 单行 → NULL
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="m1", duration_ms=None, usage=_usage(100))])
    rows, _ = _parse(f)
    assert rows[0]["speed_tps"] is None


def test_speed_delta_fallback_and_value_on_last_row(tmp_path):
    # 同 id 流式多行: usage 逐行累计, Δoutput/Δt 取末行−首行, 值只附着末行
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [
        _line(msg_id="m1", ts="2026-06-12T19:12:00.000Z", duration_ms=None,
              usage=_usage(50)),
        _line(msg_id="m1", ts="2026-06-12T19:12:00.500Z", duration_ms=None,
              usage=_usage(100)),
        _line(msg_id="m1", ts="2026-06-12T19:12:01.000Z", duration_ms=None,
              usage=_usage(150)),
    ])
    rows, _ = _parse(f)
    assert [r["speed_tps"] for r in rows] == [None, None, 100.0]
    # (150-50)*1000 / 1000ms = 100; 幸存行 = 末行 (总量大者胜)


def test_speed_duration_ms_takes_priority_over_delta(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [
        _line(msg_id="m1", ts="2026-06-12T19:12:00.000Z", duration_ms=1000,
              usage=_usage(50)),
        _line(msg_id="m1", ts="2026-06-12T19:12:01.000Z", duration_ms=1000,
              usage=_usage(150)),
    ])
    rows, _ = _parse(f)
    # durationMs 优先: 末行 output 150*1000/1000 = 150 (Δ 口径会给 100)
    assert rows[1]["speed_tps"] == 150.0
    assert rows[0]["speed_tps"] is None


def test_speed_noise_filtered_delta_windows(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [
        # 窗口 50ms < 100ms → 排除
        _line(msg_id="w1", ts="2026-06-12T19:12:00.000Z", duration_ms=None,
              usage=_usage(50)),
        _line(msg_id="w1", ts="2026-06-12T19:12:00.050Z", duration_ms=None,
              usage=_usage(150)),
        # Δoutput = 5 < 10 tok → 排除
        _line(msg_id="w2", ts="2026-06-12T19:12:00.000Z", duration_ms=None,
              usage=_usage(100)),
        _line(msg_id="w2", ts="2026-06-12T19:12:01.000Z", duration_ms=None,
              usage=_usage(105)),
        # (150-50)*1000/100 = 1000 tok/s > 500 → 排除
        _line(msg_id="w3", ts="2026-06-12T19:12:00.000Z", duration_ms=None,
              usage=_usage(50)),
        _line(msg_id="w3", ts="2026-06-12T19:12:00.100Z", duration_ms=None,
              usage=_usage(150)),
    ])
    rows, _ = _parse(f)
    assert all(r["speed_tps"] is None for r in rows)


def test_speed_noise_filtered_duration_ms_path(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [
        _line(msg_id="n1", duration_ms=1000, usage=_usage(5)),    # 输出 <10 tok
        _line(msg_id="n2", duration_ms=100, usage=_usage(100)),   # 1000 tok/s > 500
        _line(msg_id="n3", duration_ms=50, usage=_usage(100)),    # 窗口 <100ms
    ])
    rows, _ = _parse(f)
    assert all(r["speed_tps"] is None for r in rows)


def test_speed_no_id_rows_not_grouped(tmp_path):
    # 无 id 行各持独立兜底键, 不构成同 id 分组窗口 → 均无 Δ 秒速
    f = tmp_path / "sess.jsonl"
    _write_jsonl(f, [
        _line(msg_id=None, ts="2026-06-12T19:12:00.000Z", duration_ms=None,
              usage=_usage(50)),
        _line(msg_id=None, ts="2026-06-12T19:12:01.000Z", duration_ms=None,
              usage=_usage(150)),
    ])
    rows, _ = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["sess|1", "sess|2"]
    assert all(r["speed_tps"] is None for r in rows)


# ---------------------------------------------------------------------------
# 5. resolve_channel 两分支
# ---------------------------------------------------------------------------

def test_resolve_channel_after_enabled_uses_base_url():
    # 相等也算启用后 (>=)
    assert claudecode_api.resolve_channel(
        "claude-sonnet-4-5", ENABLED_TS, ENABLED_TS, "relay.example.com"
    ) == "relay.example.com"
    # settings 缺失 → base_url=None → 官方
    assert claudecode_api.resolve_channel(
        "glm-4.6", ENABLED_TS + 1, ENABLED_TS, None
    ) == "官方"


def test_resolve_channel_before_enabled_heuristic():
    assert claudecode_api.resolve_channel(
        "claude-3-opus", ENABLED_TS - 1, ENABLED_TS, "relay.example.com"
    ) == "官方"                                     # 历史启发: claude-* → 官方
    assert claudecode_api.resolve_channel(
        "Claude-Sonnet-4-5", ENABLED_TS - 1, ENABLED_TS, None
    ) == "官方"                                     # claude-* 判定大小写不敏感
    assert claudecode_api.resolve_channel(
        "glm-4.6", ENABLED_TS - 1, ENABLED_TS, None
    ) == "glm"                                      # 模型名首段
    assert claudecode_api.resolve_channel(
        "Deepseek-R1", ENABLED_TS - 1, ENABLED_TS, None
    ) == "deepseek"                                 # 统一小写, 避免大小写分裂
    assert claudecode_api.resolve_channel(
        "deepseek/deepseek-v3", ENABLED_TS - 1, ENABLED_TS, None
    ) == "deepseek"                                 # 含 "/" 取首个 "/" 前段
    assert claudecode_api.resolve_channel(
        "meta/muse", ENABLED_TS - 1, ENABLED_TS, None
    ) == "meta"


# ---------------------------------------------------------------------------
# 6. read_base_url (settings.json 存在/缺失/非法/api.anthropic.com)
# ---------------------------------------------------------------------------

def _write_settings(payload):
    claudecode_api.CLAUDE_SETTINGS.write_text(json.dumps(payload),
                                              encoding="utf-8")


def test_base_url_hostname_extracted():
    _write_settings({"env": {"ANTHROPIC_BASE_URL": "https://relay.example.com/v1"}})
    assert claudecode_api.read_base_url() == "relay.example.com"


def test_base_url_official_host_returns_none():
    _write_settings({"env": {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}})
    assert claudecode_api.read_base_url() is None


def test_base_url_missing_or_invalid_cases():
    assert claudecode_api.read_base_url() is None          # 文件缺失
    claudecode_api.CLAUDE_SETTINGS.write_text("{broken", encoding="utf-8")
    assert claudecode_api.read_base_url() is None          # 非法 JSON
    _write_settings({})
    assert claudecode_api.read_base_url() is None          # env 缺失
    _write_settings({"env": {"OTHER": "x"}})
    assert claudecode_api.read_base_url() is None          # 键缺失
    _write_settings({"env": {"ANTHROPIC_BASE_URL": "not a url"}})
    assert claudecode_api.read_base_url() is None          # 非法 URL


# ---------------------------------------------------------------------------
# 7. parse 增量: 只读新增字节 / 半行悬挂
# ---------------------------------------------------------------------------

def test_parse_reads_only_new_bytes(tmp_path):
    f = tmp_path / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="m1"), _line(msg_id="m2")])
    rows, offset = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["m1", "m2"]
    assert offset == f.stat().st_size
    # 追加一行后从上次偏移续读: 只消费新增行
    _write_jsonl(f, [_line(msg_id="m3")], mode="a")
    rows, offset2 = _parse(f, offset)
    assert [r["dedupe_key"] for r in rows] == ["m3"]
    assert offset2 == f.stat().st_size


def test_parse_partial_line_hangs_until_complete(tmp_path):
    f = tmp_path / "s.jsonl"
    first = _line(msg_id="m1")
    f.write_bytes(first.encode("utf-8") + b"\n"
                  + b'{"type":"assistant","timestamp":"2026-06-12T19:')
    rows, offset = _parse(f)
    assert [r["dedupe_key"] for r in rows] == ["m1"]   # 半行不消费
    assert offset == len(first) + 1                    # 停在最后完整行末尾 (含换行)
    # 追加补全该行 (时间戳两段拼回 "2026-06-12T19:12:00.759Z", 新行 m2)
    _write_jsonl(f, [
        b'12:00.759Z","message":{"id":"m2","model":"claude-sonnet-4-5",'
        b'"usage":{"input_tokens":1,"output_tokens":2,'
        b'"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}',
    ], mode="a")
    rows, offset2 = _parse(f, offset)
    assert [r["dedupe_key"] for r in rows] == ["m2"]   # 补全后消费
    assert offset2 == f.stat().st_size


# ---------------------------------------------------------------------------
# 8. import_incremental: 批次结构 / channel 盖章 / 续读 / 变短重扫 / 节流
# ---------------------------------------------------------------------------

def test_import_incremental_batch_shape_and_channel_stamp(cc_projects):
    f = cc_projects / "proj" / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="old", model="glm-4.6", ts=TS_BEFORE),
                     _line(msg_id="new", model="glm-4.6", ts=TS_AFTER)])
    _write_settings({"env": {"ANTHROPIC_BASE_URL": "https://relay.example.com/v1"}})
    batches = claudecode_api.import_incremental(ENABLED_TS, {}, force=True)
    assert len(batches) == 1
    b = batches[0]
    assert b["path"] == str(f)
    assert b["size"] == f.stat().st_size
    assert b["new_offset"] == f.stat().st_size
    rows = {r["dedupe_key"]: r for r in b["rows"]}
    assert set(rows["old"]) == {           # 14 键契约 (含 speed_tps 与盖章的 channel)
        "dedupe_key", "session_id", "project_path", "model", "channel",
        "started_at", "input_tokens", "output_tokens", "cache_read_tokens",
        "cache_write_tokens", "total_tokens", "duration_ms", "speed_tps",
        "file_path",
    }
    assert rows["old"]["channel"] == "glm"                 # 启用前 → 模型名启发
    assert rows["new"]["channel"] == "relay.example.com"   # 启用后 → settings 快照


def test_import_incremental_resume_and_no_change(cc_projects):
    f = cc_projects / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="m1")])
    first = claudecode_api.import_incremental(0, {}, force=True)
    assert len(first) == 1
    progress = {first[0]["path"]: (first[0]["new_offset"], first[0]["size"])}
    # 无新增 → 不产批次
    assert claudecode_api.import_incremental(0, progress, force=True) == []
    # 追加新行 → 只含新增
    _write_jsonl(f, [_line(msg_id="m2")], mode="a")
    second = claudecode_api.import_incremental(0, progress, force=True)
    assert [r["dedupe_key"] for r in second[0]["rows"]] == ["m2"]


def test_import_incremental_partial_line_waits(cc_projects):
    f = cc_projects / "s.jsonl"
    full = _line(msg_id="m1")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(full.encode("utf-8") + b"\n" + b'{"type":"assistant","t')
    batches = claudecode_api.import_incremental(0, {}, force=True)
    # 完整行照常消费, 半行不消费; 批次照产 (推进 progress 的 size)
    assert len(batches) == 1
    assert [r["dedupe_key"] for r in batches[0]["rows"]] == ["m1"]
    assert batches[0]["new_offset"] == len(full) + 1
    assert batches[0]["size"] == f.stat().st_size


def test_import_incremental_shrunk_file_reread_from_start(cc_projects):
    f = cc_projects / "s.jsonl"
    _write_jsonl(f, [_line(msg_id="m1"), _line(msg_id="m2")])
    first = claudecode_api.import_incremental(0, {}, force=True)[0]
    progress = {first["path"]: (first["new_offset"], first["size"])}
    # 文件被重写 (变短): 从头重读, 幂等靠去重键
    _write_jsonl(f, [_line(msg_id="m9")])
    second = claudecode_api.import_incremental(0, progress, force=True)
    assert [r["dedupe_key"] for r in second[0]["rows"]] == ["m9"]
    assert second[0]["new_offset"] == f.stat().st_size


def test_import_incremental_projects_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(claudecode_api, "CLAUDE_PROJECTS",
                        tmp_path / "nonexistent")
    assert claudecode_api.import_incremental(0, {}, force=True) == []


def test_import_single_file_failure_skipped(cc_projects, monkeypatch):
    f1 = cc_projects / "a" / "1.jsonl"
    f2 = cc_projects / "b" / "2.jsonl"
    _write_jsonl(f1, [_line(msg_id="m1")])
    _write_jsonl(f2, [_line(msg_id="m2")])
    real_parse = claudecode_api.parse_session_file

    def flaky(path, offset):
        if path.name == "1.jsonl":
            raise RuntimeError("boom")
        return real_parse(path, offset)

    monkeypatch.setattr(claudecode_api, "parse_session_file", flaky)
    batches = claudecode_api.import_incremental(0, {}, force=True)
    assert [Path(b["path"]).name for b in batches] == ["2.jsonl"]  # 不中断整体


def test_import_orchestration_error_swallowed(cc_projects, monkeypatch):
    _write_jsonl(cc_projects / "s.jsonl", [_line(msg_id="m1")])

    def boom():
        raise RuntimeError("scan failed")

    monkeypatch.setattr(claudecode_api, "scan_session_files", boom)
    assert claudecode_api.import_incremental(0, {}, force=True) == []  # 不外抛


# ---------------------------------------------------------------------------
# 9. 5 秒节流与 force (失败也计入窗口)
# ---------------------------------------------------------------------------

def test_throttle_blocks_within_window_and_force_bypasses(cc_projects,
                                                          monkeypatch):
    monkeypatch.setattr(claudecode_api, "IMPORT_INTERVAL_SECONDS", 3600.0)
    _write_jsonl(cc_projects / "s.jsonl", [_line(msg_id="m1")])
    assert len(claudecode_api.import_incremental(0, {}, force=True)) == 1
    assert claudecode_api.import_incremental(0, {}) == []             # 窗口内被挡
    assert len(claudecode_api.import_incremental(0, {}, force=True)) == 1  # force 绕过


def test_throttle_window_counts_failures(cc_projects, monkeypatch):
    monkeypatch.setattr(claudecode_api, "IMPORT_INTERVAL_SECONDS", 3600.0)
    _write_jsonl(cc_projects / "s.jsonl", [_line(msg_id="m1")])
    calls = []
    real_scan = claudecode_api.scan_session_files

    def flaky_scan():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return real_scan()

    monkeypatch.setattr(claudecode_api, "scan_session_files", flaky_scan)
    assert claudecode_api.import_incremental(0, {}) == []   # 首次失败: 吞掉不外抛
    assert claudecode_api.import_incremental(0, {}) == []   # 失败计入窗口 → 被挡
    assert len(calls) == 1                                  # 第二次未真正扫描
    assert len(claudecode_api.import_incremental(0, {}, force=True)) == 1
    assert len(calls) == 2
