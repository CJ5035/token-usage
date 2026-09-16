"""workbuddy_local_api.py 单测: 扫描/行过滤/去重键/会话归属/增量续读/节流/定价归一.

全部走临时目录 + monkeypatch (WORKBUDDY_PROJECTS 指向 tmp_path, 节流变量重置),
不读本机真实 ~/.workbuddy 文件.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import workbuddy_local_api


@pytest.fixture(autouse=True)
def wb_projects(tmp_path, monkeypatch):
    """伪造 ~/.workbuddy/projects 并重置模块级节流变量 (防用例间串扰)."""
    projects = tmp_path / "workbuddy" / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(workbuddy_local_api, "WORKBUDDY_PROJECTS", projects)
    workbuddy_local_api._last_import_at = None
    yield projects
    workbuddy_local_api._last_import_at = None


def _exp(model="deepseek-v4.1-flash", hit=100, miss=200, out=50, think=0, credit=0.85):
    """构造 providerData.rawUsage (含 WorkBuddy 特有字段)."""
    return {
        "prompt_tokens": hit + miss, "completion_tokens": out,
        "total_tokens": hit + miss + out,
        "prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": miss,
        "prompt_cache_write_tokens": 0, "completion_thinking_tokens": think,
        "credit": credit,
    }


def _line(message_id="msg_1", ts=1789525034418, raw_usage=None, model="deepseek-v4.1-flash",
          session_id="child-uuid", type_="function_call"):
    """构造一条 WorkBuddy JSONL 记录 (顶层 camelCase, usage 在 providerData.rawUsage)."""
    rec = {"type": type_, "timestamp": ts, "sessionId": session_id, "cwd": "F:\\proj"}
    if raw_usage is not None:
        rec["providerData"] = {
            "messageId": message_id, "model": model,
            "requestModelName": "Deepseek-V4.1-Flash",
            "traceId": "trace-abc", "rawUsage": raw_usage,
        }
    return json.dumps(rec)


def _write_jsonl(path: Path, lines, mode="w"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode + "b") as f:
        for line in lines:
            f.write(line.encode("utf-8") if isinstance(line, str) else line)
            f.write(b"\n")


def test_scan_skips_rollback_files(wb_projects):
    _write_jsonl(wb_projects / "proj-a" / "s1.jsonl", [_line()])
    _write_jsonl(wb_projects / "proj-a" / "s1.file-rollback.ndjson", [_line()])
    _write_jsonl(wb_projects / "proj-b" / "s2.jsonl", [_line()])
    found = [p.name for p in workbuddy_local_api.scan_session_files()]
    assert found == ["s1.jsonl", "s2.jsonl"]


def test_session_id_for_uses_path_not_row_session_id(wb_projects):
    """R1 回归: 子代理会话 id 取祖父目录名, 绝不取行内 sessionId."""
    main = wb_projects / "proj" / "0ae6d6ce-parent.jsonl"
    sub = wb_projects / "proj" / "0ae6d6ce-parent" / "subagents" / "agent-057ca85f.jsonl"
    _write_jsonl(main, [_line(session_id="0ae6d6ce-parent")])
    _write_jsonl(sub, [_line(session_id="e87508b9-child")])
    assert workbuddy_local_api.session_id_for(main) == "0ae6d6ce-parent"
    assert workbuddy_local_api.session_id_for(sub) == "0ae6d6ce-parent"


def _rows_of(path, start=0):
    rows, new_offset = workbuddy_local_api.parse_session_file(path, start)
    return rows, new_offset


def test_parse_maps_fields_and_derives_session_from_path(wb_projects):
    sub = wb_projects / "proj" / "0ae6d6ce-parent" / "subagents" / "agent-1.jsonl"
    _write_jsonl(sub, [_line(message_id="m1", raw_usage=_exp(hit=100, miss=200, out=50, think=7),
                             session_id="child-uuid")])
    rows, _ = _rows_of(sub)
    assert len(rows) == 1
    r = rows[0]
    assert r["dedupe_key"] == "m1"
    assert r["session_id"] == "0ae6d6ce-parent"      # 路径判定, 非 child-uuid
    assert r["input_tokens"] == 200                  # ← miss
    assert r["cache_read_tokens"] == 100             # ← hit
    assert r["output_tokens"] == 43                  # R8: completion 50 − thinking 7
    assert r["reasoning_tokens"] == 7
    assert r["cache_write_tokens"] == 0              # 恒 0
    assert r["total_tokens"] == 350
    assert r["credit"] == 0.85
    assert r["started_at"].endswith("Z")
    # R8 恒等式: 三项相加 == 原生 total_tokens (前端「总 TOKEN 消耗」卡即用此三键求和)
    assert (r["input_tokens"] + r["cache_read_tokens"]
            + r["output_tokens"] + r["reasoning_tokens"]) == r["total_tokens"]


def test_parse_output_excludes_thinking_tokens(wb_projects):
    """R8 回归: completion_thinking_tokens 已含在 completion_tokens 内, 必须扣除,
    否则前端 total_input + total_output + total_reasoning 会重复计数思考 token."""
    p = wb_projects / "proj" / "s.jsonl"
    _write_jsonl(p, [
        _line(message_id="with-think", raw_usage=_exp(hit=0, miss=100, out=500, think=450)),
        _line(message_id="no-think", raw_usage=_exp(hit=0, miss=100, out=500, think=0)),
        _line(message_id="think-clamped", raw_usage=_exp(hit=0, miss=10, out=5, think=5)),
    ])
    rows = {r["dedupe_key"]: r for r in _rows_of(p)[0]}
    assert rows["with-think"]["output_tokens"] == 50     # 500 − 450
    assert rows["with-think"]["reasoning_tokens"] == 450
    assert rows["no-think"]["output_tokens"] == 500
    assert rows["think-clamped"]["output_tokens"] == 0   # max(0, 5 − 5)
    for r in rows.values():
        assert r["output_tokens"] >= 0


def test_parse_skips_rows_without_usage_or_zero_total(wb_projects):
    p = wb_projects / "proj" / "s.jsonl"
    _write_jsonl(p, [
        _line(message_id="no-provider", raw_usage=None),                   # 无 providerData
        _line(message_id="zero", raw_usage=_exp(hit=0, miss=0, out=0)),    # total 0
        _line(message_id="reasoning-only", type_="reasoning"),             # reasoning 型无 providerData
        _line(message_id="ok", raw_usage=_exp()),
    ])
    rows, _ = _rows_of(p)
    assert [r["dedupe_key"] for r in rows] == ["ok"]


def test_parse_does_not_consume_dangling_half_line(wb_projects):
    p = wb_projects / "proj" / "s.jsonl"
    _write_jsonl(p, [_line(message_id="m1", raw_usage=_exp())])
    full_size = p.stat().st_size
    with open(p, "ab") as f:
        f.write(b'{"type": "function_call", "providerData": {"mes')  # 半行
    rows, new_offset = _rows_of(p)
    assert len(rows) == 1
    assert new_offset == full_size          # 只推进到最后一条完整行末尾


def test_parse_resumes_from_offset(wb_projects):
    p = wb_projects / "proj" / "s.jsonl"
    _write_jsonl(p, [_line(message_id="m1", raw_usage=_exp())])
    _, offset = _rows_of(p)
    _write_jsonl(p, [_line(message_id="m2", raw_usage=_exp())], mode="a")
    rows, _ = _rows_of(p, offset)
    assert [r["dedupe_key"] for r in rows] == ["m2"]


# 定价表 fixture: deepseek-v4.1-flash 只有带 provider 前缀的条目 (复现 §3.7 缺口)
_PRICING = [
    {"modelId": "deepseek/deepseek-v4.1-flash", "inputCostPerMillion": "0.15",
     "outputCostPerMillion": "0.6", "cacheReadCostPerMillion": "0.003",
     "cacheCreationCostPerMillion": "0"},
    {"modelId": "deepseek-v4-flash", "inputCostPerMillion": "0.15",
     "outputCostPerMillion": "0.6", "cacheReadCostPerMillion": "0.003",
     "cacheCreationCostPerMillion": "0"},
    {"modelId": "deepseek/deepseek-v4-flash", "inputCostPerMillion": "0.99",
     "outputCostPerMillion": "0.99", "cacheReadCostPerMillion": "0.99",
     "cacheCreationCostPerMillion": "0"},
]


def test_estimate_cost_raw_falls_back_to_model_id_tail():
    """尾段归一: 入参 deepseek-v4.1-flash 命中表键 deepseek/deepseek-v4.1-flash."""
    cost, available = workbuddy_local_api.estimate_cost_raw(
        "deepseek-v4.1-flash", 1_000_000, 1_000_000, 0, _PRICING)
    assert available is True
    # 1e6 tok × ($0.15/M in + $0.6/M out) = $0.75; cost_raw 单位 1e-8 USD → 75_000_000 (R31)
    assert cost == int(round((1_000_000 * 0.15 + 1_000_000 * 0.6) / 1e6 * 1e8)) == 75_000_000


def test_estimate_cost_raw_prefers_exact_match_over_tail():
    """精确优先: deepseek-v4-flash 必须命中纯名条目 (0.15/0.6), 而非前缀条目 (0.99)."""
    cost, available = workbuddy_local_api.estimate_cost_raw(
        "deepseek-v4-flash", 1_000_000, 0, 0, _PRICING)
    assert available is True
    # $0.15 → cost_raw = 15_000_000 (1e-8 USD 单位, R31)
    assert cost == int(round(1_000_000 * 0.15 / 1e6 * 1e8)) == 15_000_000
    assert cost < int(round(1_000_000 * 0.99 / 1e6 * 1e8))


def test_estimate_cost_raw_marks_unpriced_model():
    """未收录模型 → (0, False), 供 db 层区分"未收录"与"真 0"."""
    cost, available = workbuddy_local_api.estimate_cost_raw("hy3", 1000, 10, 0, _PRICING)
    assert cost == 0
    assert available is False


def test_import_incremental_returns_batch_and_skips_unchanged(wb_projects, monkeypatch):
    monkeypatch.setattr(workbuddy_local_api, "load_pricing_models", lambda *_: _PRICING)
    p = wb_projects / "proj" / "s.jsonl"
    _write_jsonl(p, [_line(message_id="m1", raw_usage=_exp())])
    batches = workbuddy_local_api.import_incremental({}, force=True)
    assert len(batches) == 1
    assert batches[0]["path"] == str(p)
    assert len(batches[0]["rows"]) == 1
    assert batches[0]["rows"][0]["cost_available"] == 1
    # 用返回的偏移再跑一次 → 无新增内容, 不产批次
    progress = {batches[0]["path"]: (batches[0]["new_offset"], batches[0]["size"])}
    assert workbuddy_local_api.import_incremental(progress, force=True) == []


def test_import_incremental_rereads_from_head_when_file_shrinks(wb_projects, monkeypatch):
    monkeypatch.setattr(workbuddy_local_api, "load_pricing_models", lambda *_: _PRICING)
    p = wb_projects / "proj" / "s.jsonl"
    _write_jsonl(p, [_line(message_id="m1-original-long-id", raw_usage=_exp())])
    batches = workbuddy_local_api.import_incremental({}, force=True)
    progress = {batches[0]["path"]: (batches[0]["new_offset"], batches[0]["size"])}
    _write_jsonl(p, [_line(message_id="m2", raw_usage=_exp())])
    assert p.stat().st_size < batches[0]["size"]  # 明确证明真的变短
    batches = workbuddy_local_api.import_incremental(progress, force=True)
    assert [r["dedupe_key"] for r in batches[0]["rows"]] == ["m2"]


def test_import_incremental_throttles_without_force(wb_projects, monkeypatch):
    monkeypatch.setattr(workbuddy_local_api, "load_pricing_models", lambda *_: _PRICING)
    _write_jsonl(wb_projects / "proj" / "s.jsonl", [_line(raw_usage=_exp())])
    assert len(workbuddy_local_api.import_incremental({})) == 1
    _write_jsonl(wb_projects / "proj" / "s2.jsonl", [_line(message_id="m2", raw_usage=_exp())])
    assert workbuddy_local_api.import_incremental({}) == []          # 5s 窗口内被节流


def test_import_incremental_survives_missing_projects_dir(wb_projects, monkeypatch):
    monkeypatch.setattr(workbuddy_local_api, "WORKBUDDY_PROJECTS", wb_projects / "nope")
    assert workbuddy_local_api.import_incremental({}, force=True) == []


def test_import_incremental_cost_uses_full_completion(wb_projects, monkeypatch):
    """R26 回归: 费用基数必须是完整 completion (落库 output + reasoning), 不可只用 output.

    思考 token 在落库 output_tokens 里已被扣掉 (R8), 但厂商按完整 completion 计费,
    故此处必须回加, 否则思考占比高的模型费用被显著低算。
    """
    monkeypatch.setattr(workbuddy_local_api, "load_pricing_models", lambda *_: _PRICING)
    p = wb_projects / "proj" / "s.jsonl"
    _write_jsonl(p, [_line(message_id="m1",
                           raw_usage=_exp(hit=0, miss=0, out=1_000_000, think=400_000))])
    row = workbuddy_local_api.import_incremental({}, force=True)[0]["rows"][0]
    assert row["output_tokens"] == 600_000            # 落库口径已扣 thinking
    assert row["reasoning_tokens"] == 400_000
    # _PRICING 里 deepseek-v4.1-flash 输出 $0.6/M → 完整 completion 1e6 → 0.6 USD
    assert row["cost_raw"] == int(round(0.6 * 1e8))
    assert row["cost_raw"] != int(round(0.36 * 1e8))  # 误用 output_tokens 才会得到 0.36


def test_parse_bad_timestamp_does_not_drop_valid_following_row(wb_projects):
    p = wb_projects / "proj" / "bad.jsonl"
    _write_jsonl(p, [_line(message_id="bad", ts=10**30, raw_usage=_exp()),
                     _line(message_id="inf", ts=float("inf"), raw_usage=_exp()),
                     _line(message_id="ok", raw_usage=_exp())])
    assert [r["dedupe_key"] for r in _rows_of(p)[0]] == ["ok"]


def test_parse_rejects_inconsistent_token_totals(wb_projects):
    p = wb_projects / "proj" / "bad-token.jsonl"
    _write_jsonl(p, [_line(message_id="bad", raw_usage=_exp(out=5, think=6)),
                     _line(message_id="ok", raw_usage=_exp())])
    assert [r["dedupe_key"] for r in _rows_of(p)[0]] == ["ok"]


def test_estimate_invalid_price_is_unknown_but_zero_is_available():
    for value in (None, "bad", "NaN", "Infinity", "-1"):
        models = [{"modelId": "m", "inputCostPerMillion": value}]
        assert workbuddy_local_api.estimate_cost_raw("m", 1, 0, 0, models) == (0, False)
    assert workbuddy_local_api.estimate_cost_raw(
        "m", 1, 0, 0, [{"modelId": "m", "inputCostPerMillion": "0"}]) == (0, True)


def test_process_read_error_does_not_commit_progress(wb_projects, monkeypatch):
    p = wb_projects / "proj" / "s.jsonl"
    _write_jsonl(p, [_line(raw_usage=_exp())])
    def fail(*args):
        raise OSError("unreadable")
    monkeypatch.setattr(workbuddy_local_api, "parse_session_file", fail)
    assert workbuddy_local_api.import_incremental({}, pricing_models=[], force=True) == []
