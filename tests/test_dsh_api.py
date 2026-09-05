"""dsh_api.py 单测: 多帧解压 / 解析口径 / 秒速窗口 / 全量聚合 / TTL 缓存.

全部走临时目录 + monkeypatch 伪造 ~/.dsh/sessions, 不读本机真实 dsh 日志.
"""
from __future__ import annotations

import json
import time as time_mod

import pytest
import zstandard

from app import dsh_api


# ---------------------------------------------------------------------------
# 测试数据与工具
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_cache():
    """每个测试前后重置模块级缓存, 避免用例间互相污染."""
    dsh_api._cache_payload = None
    yield
    dsh_api._cache_payload = None


def _ev(etype, time_ms, data):
    return {"type": etype, "time": time_ms, "data": data}


def _ctx(provider, model, time_ms=0):
    return _ev("request/context", time_ms, {"provider": provider, "model": model})


def _step_start(turn, step, time_ms):
    return _ev("step/start", time_ms, {"turn": turn, "step": step})


def _chunk(turn, step, time_ms, usage):
    chunk = {"type": "usage", "usage": usage}
    return _ev("assistant/chunk", time_ms, {"turn": turn, "step": step, "chunk": chunk})


def _msg(turn, step, time_ms, usage):
    return _ev("assistant/message", time_ms, {"turn": turn, "step": step, "usage": usage})


def _frames(*chunks: bytes) -> bytes:
    """多段文本 → 多帧 zstd 拼接流."""
    return b"".join(zstandard.compress(c) for c in chunks)


def _write_session(root, ws, sid, events):
    """写一个会话日志 (每事件一帧, 拼接为多帧流), 返回日志路径."""
    d = root / ws / sid
    d.mkdir(parents=True, exist_ok=True)
    path = d / "session.jsonl.zstd"
    path.write_bytes(
        _frames(*((json.dumps(e) + "\n").encode("utf-8") for e in events))
    )
    return path


def _patch_root(monkeypatch, tmp_path):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)


def _scan(tmp_path, monkeypatch, events, ws="ws", sid="session-1"):
    """单会话扫描快捷入口."""
    _patch_root(monkeypatch, tmp_path)
    _write_session(tmp_path, ws, sid, events)
    return dsh_api.scan()


# ---------------------------------------------------------------------------
# 1. 解压
# ---------------------------------------------------------------------------

class TestDecompressFrames:
    def test_multi_frame_concatenated(self):
        a = ("line-a\n" * 10).encode("utf-8")
        b = ("line-b\n" * 10).encode("utf-8")
        assert dsh_api.decompress_frames(_frames(a, b, a)) == (a + b + a).decode("utf-8")

    def test_bad_tail_frame_dropped(self):
        good = zstandard.compress("hello\n".encode("utf-8"))
        truncated_tail = zstandard.compress(b"tail-data")[:-6]
        # 尾帧不完整 (正在写入): 丢弃不抛错, 好帧照常解出
        assert dsh_api.decompress_frames(good + truncated_tail) == "hello\n"

    def test_plain_text_without_magic_gives_empty(self):
        assert dsh_api.decompress_frames(b"plain text, no zstd magic") == ""

    def test_scan_skips_plain_text_log(self, tmp_path, monkeypatch):
        _patch_root(monkeypatch, tmp_path)
        d = tmp_path / "ws" / "s1"
        d.mkdir(parents=True)
        (d / "session.jsonl.zstd").write_bytes(b"not zstd at all")
        r = dsh_api.scan()
        assert r["found"] is True
        assert r["sessions_count"] == 1
        assert r["total"]["output"] == 0
        assert r["providers"] == []


# ---------------------------------------------------------------------------
# 2. 解析口径
# ---------------------------------------------------------------------------

class TestParsing:
    def test_message_overrides_chunk_same_step(self, tmp_path, monkeypatch):
        events = [
            _ctx("p1", "m1"),
            _chunk(1, 1, 1000, {"inputTokens": 100, "outputTokens": 10}),
            _msg(1, 1, 2000, {"inputTokens": 200, "outputTokens": 20}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        # 同 turn:step 只计一次, message 覆盖 (不累加); input=billed 口径
        assert r["total"]["input"] == 200
        assert r["total"]["output"] == 20
        assert r["providers"][0]["steps"] == 1

    def test_context_switch_attributes_usage(self, tmp_path, monkeypatch):
        events = [
            _ctx("p1", "m1"),
            _chunk(1, 1, 1000, {"inputTokens": 10, "outputTokens": 5}),
            _ctx("p2", "m2"),
            _msg(1, 2, 2000, {"inputTokens": 20, "outputTokens": 8}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        providers = {row["provider"]: row for row in r["providers"]}
        assert providers["p1"]["input"] == 10
        assert providers["p1"]["output"] == 5
        assert providers["p2"]["input"] == 20
        assert providers["p2"]["output"] == 8
        models = {(row["provider"], row["model"]): row for row in r["models"]}
        assert set(models) == {("p1", "m1"), ("p2", "m2")}

    def test_cache_write_reasoning_default_zero(self, tmp_path, monkeypatch):
        events = [
            _ctx("p", "m"),
            _msg(1, 1, 100, {"inputTokens": 5, "outputTokens": 3}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        assert r["total"]["cache"] == 0
        assert r["total"]["reasoning"] == 0

    def test_usage_without_tokens_ignored(self, tmp_path, monkeypatch):
        events = [
            _ctx("p", "m"),
            _chunk(1, 1, 100, {}),
            _msg(1, 2, 200, {"inputTokens": 1, "outputTokens": 2}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        # usage 全缺 token 的行忽略, 只有 message 那条参与计数
        assert r["total"]["input"] == 1
        assert r["total"]["output"] == 2
        assert r["providers"][0]["steps"] == 1


# ---------------------------------------------------------------------------
# 3. 秒速
# ---------------------------------------------------------------------------

class TestSpeed:
    def test_window_seconds_and_tps(self, tmp_path, monkeypatch):
        events = [
            _ctx("p", "m"),
            _step_start(1, 1, 1_000_000),
            _msg(1, 1, 1_001_000, {"inputTokens": 0, "outputTokens": 100}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        # 窗口 = (1001000 − 1000000) ms = 1s, 速率 100 tok/s 参与计速
        assert r["total"]["seconds"] == pytest.approx(1.0)
        assert r["total"]["tps"] == pytest.approx(100.0)

    def test_output_below_10_excluded_but_counted(self, tmp_path, monkeypatch):
        events = [
            _ctx("p", "m"),
            _step_start(1, 1, 1_000_000),
            _msg(1, 1, 1_001_000, {"inputTokens": 0, "outputTokens": 9}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        # output<10 不参与秒速, token 照计
        assert r["total"]["seconds"] == 0.0
        assert r["total"]["tps"] == 0.0
        assert r["total"]["output"] == 9

    def test_zero_window_excluded(self, tmp_path, monkeypatch):
        events = [
            _ctx("p", "m"),
            _step_start(1, 1, 1_000_000),
            _msg(1, 1, 1_000_000, {"inputTokens": 0, "outputTokens": 100}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        assert r["total"]["seconds"] == 0.0
        assert r["total"]["output"] == 100

    def test_rate_over_500_excluded(self, tmp_path, monkeypatch):
        events = [
            _ctx("p", "m"),
            _step_start(1, 1, 1_000_000),
            _msg(1, 1, 1_001_000, {"inputTokens": 0, "outputTokens": 600}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        assert r["total"]["seconds"] == 0.0
        assert r["total"]["output"] == 600

    def test_missing_step_start_excluded(self, tmp_path, monkeypatch):
        events = [
            _ctx("p", "m"),
            _msg(1, 1, 1_001_000, {"inputTokens": 0, "outputTokens": 100}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        # 找不到同 turn:step 的 step/start (窗口缺失): 不计秒速, token 照计
        assert r["total"]["seconds"] == 0.0
        assert r["total"]["output"] == 100

    def test_weighted_aggregation_not_simple_average(self, tmp_path, monkeypatch):
        events = [
            _ctx("p", "m"),
            # 步 1: 窗口 2s / output 100 → 50 tok/s
            _step_start(1, 1, 0),
            _msg(1, 1, 2_000, {"inputTokens": 0, "outputTokens": 100}),
            # 步 2: 窗口 1s / output 300 → 300 tok/s
            _step_start(1, 2, 0),
            _msg(1, 2, 1_000, {"inputTokens": 0, "outputTokens": 300}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        # 加权 tps = Σoutput ÷ Σ秒 = 400/3, 不是简单平均 (50+300)/2=175
        assert r["total"]["seconds"] == pytest.approx(3.0)
        assert r["total"]["tps"] == pytest.approx(400 / 3)
        assert r["providers"][0]["seconds"] == pytest.approx(3.0)
        assert r["providers"][0]["tps"] == pytest.approx(400 / 3)


# ---------------------------------------------------------------------------
# 4. 聚合
# ---------------------------------------------------------------------------

class TestScanAggregation:
    def test_total_vs_today_split(self, tmp_path, monkeypatch):
        today_ms = int(time_mod.time() * 1000)
        yesterday_ms = today_ms - 2 * 86_400_000
        events = [
            _ctx("p", "m"),
            # 昨日样本, 无 step/start → 秒速剔除但 token 照计
            _msg(1, 1, yesterday_ms, {"inputTokens": 10, "outputTokens": 10}),
            _step_start(1, 2, today_ms - 1_000),
            _msg(1, 2, today_ms, {"inputTokens": 20, "outputTokens": 20}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        assert r["total"]["output"] == 30
        assert r["today"]["output"] == 20
        assert r["total"]["seconds"] == pytest.approx(1.0)
        assert r["today"]["seconds"] == pytest.approx(1.0)
        assert r["today"]["tps"] == pytest.approx(20.0)

    def test_provider_and_model_sorting(self, tmp_path, monkeypatch):
        events = [
            _ctx("p_a", "m1"),
            _msg(1, 1, 0, {"inputTokens": 0, "outputTokens": 5}),
            _ctx("p_a", "m2"),
            _msg(1, 2, 0, {"inputTokens": 0, "outputTokens": 50}),
            _ctx("p_b", "m3"),
            _msg(1, 3, 0, {"inputTokens": 0, "outputTokens": 500}),
        ]
        r = _scan(tmp_path, monkeypatch, events)
        # providers 按 output 降序
        assert [row["provider"] for row in r["providers"]] == ["p_b", "p_a"]
        # models 按 provider 升序 + output 降序
        assert [(row["provider"], row["model"]) for row in r["models"]] == [
            ("p_a", "m2"),
            ("p_a", "m1"),
            ("p_b", "m3"),
        ]

    def test_missing_dir_found_false(self, tmp_path, monkeypatch):
        _patch_root(monkeypatch, tmp_path)
        r = dsh_api.scan()  # root 本身不存在, 不抛异常
        assert r["found"] is False
        assert r["sessions_count"] == 0
        assert r["total"]["output"] == 0
        assert r["providers"] == []
        assert r["models"] == []

    def test_empty_dir_found_false(self, tmp_path, monkeypatch):
        _patch_root(monkeypatch, tmp_path)
        (tmp_path / "ws").mkdir()  # 空目录
        r = dsh_api.scan()
        assert r["found"] is False
        assert r["sessions_count"] == 0

    def test_corrupt_file_skipped_rest_aggregated(self, tmp_path, monkeypatch):
        _patch_root(monkeypatch, tmp_path)
        (tmp_path / "ws" / "broken").mkdir(parents=True)
        (tmp_path / "ws" / "broken" / "session.jsonl.zstd").write_bytes(b"junk-junk")
        good = [
            _ctx("p", "m"),
            _msg(1, 1, 0, {"inputTokens": 7, "outputTokens": 11}),
        ]
        _write_session(tmp_path, "ws", "session-ok", good)
        r = dsh_api.scan()
        # 损坏文件跳过 (sessions_count 仍计文件数), 正常文件聚合不受影响
        assert r["found"] is True
        assert r["sessions_count"] == 2
        assert r["total"]["input"] == 7
        assert r["total"]["output"] == 11


# ---------------------------------------------------------------------------
# 5. TTL 缓存
# ---------------------------------------------------------------------------

class TestCache:
    def test_ttl_within_cache_no_rescan(self, tmp_path, monkeypatch):
        """TTL 内直接复用缓存同一对象, 不重扫 (后台化后"过期返 stale + 后台重扫"
        行为由 test_dsh_background.py 覆盖; 冷启动不再同步扫, 热态用 scan_sync 建立)."""
        _patch_root(monkeypatch, tmp_path)
        events = [_ctx("p", "m"), _msg(1, 1, 0, {"inputTokens": 1, "outputTokens": 1})]
        _write_session(tmp_path, "ws", "session-1", events)

        dsh_api.scan_sync()  # 同步扫描建立热态缓存 (避免真实后台线程的时序不稳定)
        r1 = dsh_api.get_dsh_usage()
        assert r1["found"] is True
        assert r1["sessions_count"] == 1

        # TTL 内: 改文件后仍返回旧值 (同一对象, 不重扫)
        _write_session(tmp_path, "ws", "session-2", events)
        r2 = dsh_api.get_dsh_usage()
        assert r2 is r1
        assert r2["sessions_count"] == 1
