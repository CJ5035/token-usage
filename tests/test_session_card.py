"""单会话统计卡片的后端契约: ttft_ms 投影 / hit_rate 口径 / group_id 过滤 / 路由。

造数风格对齐 tests/test_report_api.py:48-80 (直接 INSERT, 不引入 factory 库)。
时间一律用 UTC 'Z' 字面量, 与四张表的存储形态一致。
"""
from __future__ import annotations

import datetime as _dt

import pytest

from app import db


def _iso(days_ago: float = 0.0) -> str:
    """相对当前 UTC 时刻往前 days_ago 天的 ISO 'Z' 字面量 (毫秒精度)."""
    t = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


@pytest.fixture()
def card_db(tmp_db):
    """四来源造数, 刻意覆盖 TTFT 与命中率的全部分支。

    zcode 段 (唯一有 ttft_ms 的表) 造两个会话:

    sess-z 四行:
      - z1 ttft=200  duration=2000  -> 有效 (0 <= 200 <= 2000)
      - z2 ttft=400  duration=3000  -> 有效
      - z3 ttft=NULL duration=1000  -> 无效 (NULL 不参与 AVG/COUNT)
      - z4 ttft=9999 duration=1000  -> 无效 (ttft > duration, 被 _ZCODE_TTFT_SQL 排除)
    故 sess-z 的 avg_ttft_ms 应为 (200+400)/2 = 300.0, ttft_samples = 2。

    sess-z2 两行 (z5/z6), **started_at 比 sess-z 全部行都新**, ttft 为 NULL。
    这个"更新的干扰会话"是故意的: 性能计划 Task 3 的 top-N 下推让各段基表先取
    "全表最新 N 行"。若 group_id 过滤没关掉下推, 查 sess-z 第 1 页 (page_size=2)
    时各段只捞到 z6/z5, 外层按 sess-z 一筛就空了 —— 会话有 4 行却返回空页。
    没有这个干扰会话, 该 bug 在测试里完全隐形 (单会话时所有行都属于它)。
    守卫用例: test_group_id_filter_survives_row_limit_pushdown。

    另造 claudecode / codex / usage_records 各一个会话, 用于验证它们的
    ttft_ms 恒 NULL、avg_ttft_ms 为 None、ttft_samples 为 0。
    """
    acct = db.add_account("tok-oc", "ws-oc")
    conn = db.get_db()
    # --- zcode: sess-z 四行 + sess-z2 两行(更新, 作为下推干扰) ---
    # 命中率口径核对用: hit=cache_read 合计, miss=SUM(input-cache_read), cw=cache_write 合计
    conn.executemany(
        "INSERT INTO zcode_usage (id, started_at, session_id, provider_id, provider_name,"
        " model_id, status, input_tokens, output_tokens, reasoning_tokens,"
        " cache_write_tokens, cache_read_tokens, total_tokens, duration_ms, ttft_ms,"
        " cost_raw, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("z1", _iso(0.4), "sess-z", "p1", "Provider1", "glm-4.6", "ok",
          1000, 200, 0, 50, 800, 1250, 2000, 200, 1_000_000, "2026-09-01T00:00:00"),
         ("z2", _iso(0.3), "sess-z", "p1", "Provider1", "glm-4.6", "ok",
          1000, 300, 0, 50, 700, 1350, 3000, 400, 1_000_000, "2026-09-01T00:00:00"),
         ("z3", _iso(0.2), "sess-z", "p1", "Provider1", "glm-4.6", "ok",
          1000, 100, 0, 0, 500, 1100, 1000, None, 1_000_000, "2026-09-01T00:00:00"),
         ("z4", _iso(0.1), "sess-z", "p1", "Provider1", "glm-4.6", "ok",
          1000, 100, 0, 0, 500, 1100, 1000, 9999, 1_000_000, "2026-09-01T00:00:00"),
         # 干扰会话: 比 sess-z 全部行都新
         ("z5", _iso(0.05), "sess-z2", "p1", "Provider1", "glm-4.6", "ok",
          10, 5, 0, 0, 0, 15, 1000, None, 100_000, "2026-09-01T00:00:00"),
         ("z6", _iso(0.02), "sess-z2", "p1", "Provider1", "glm-4.6", "ok",
          10, 5, 0, 0, 0, 15, 1000, None, 100_000, "2026-09-01T00:00:00")])
    # --- claudecode: 一个会话 2 行 (无 ttft 列) ---
    conn.executemany(
        "INSERT INTO claudecode_usage (dedupe_key, session_id, model, channel, started_at,"
        " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, total_tokens,"
        " duration_ms, speed_tps, cost_raw, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("cc1", "sess-cc", "claude-x", "api", _iso(0.5), 200, 90, 30, 10, 330,
          3000, 30.0, 1_000_000, "2026-09-01T00:00:00"),
         ("cc2", "sess-cc", "claude-x", "api", _iso(0.45), 100, 40, 20, 0, 160,
          2000, 20.0, 500_000, "2026-09-01T00:00:00")])
    # --- usage_records: 一个会话 2 行 ---
    conn.executemany(
        "INSERT INTO usage_records (usg_id, created_at, model, provider, input_tokens,"
        " output_tokens, reasoning_tokens, cache_read_tokens, cache_write_5m_tokens,"
        " cache_write_1h_tokens, cost_raw, cost_usd, key_id, session_id, plan,"
        " synced_at, account_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("oc1", _iso(0.6), "m1", "anthropic", 100, 20, 0, 40, 5, 5, 0, 0.25,
          None, "sess-oc", None, "2026-09-01T00:00:00", acct),
         ("oc2", _iso(0.55), "m1", "anthropic", 100, 30, 0, 60, 0, 0, 0, 0.25,
          None, "sess-oc", None, "2026-09-01T00:00:00", acct)])
    conn.commit()
    # --- codex: 一个会话 2 行, 走正式导入入口 ---
    db.import_codex_usage([
        {"id": "sess-cx:1", "session_id": "sess-cx", "event_seq": 1,
         "event_mode": "token_count", "response_id": None, "started_at": _iso(0.7),
         "model": "gpt-5", "provider_id": "codex", "input_tokens": 300,
         "cache_read_tokens": 100, "cache_write_tokens": 0, "output_tokens": 80,
         "reasoning_tokens": 10, "total_tokens": 390, "duration_ms": 4000,
         "speed_tps": 20.0, "speed_source": "duration", "request_count_exact": True,
         "model_revision_at": 0, "cost_raw": None, "file_path": "f.jsonl"},
        {"id": "sess-cx:2", "session_id": "sess-cx", "event_seq": 2,
         "event_mode": "token_count", "response_id": None, "started_at": _iso(0.65),
         "model": "gpt-5", "provider_id": "codex", "input_tokens": 200,
         "cache_read_tokens": 50, "cache_write_tokens": 0, "output_tokens": 40,
         "reasoning_tokens": 0, "total_tokens": 240, "duration_ms": None,
         "speed_tps": None, "speed_source": None, "request_count_exact": False,
         "model_revision_at": 0, "cost_raw": None, "file_path": "f.jsonl"},
    ])
    yield tmp_db


def _session_by(sessions: list[dict], source: str, session_id: str | None = None) -> dict:
    """从会话分页结果里挑出目标会话行。

    zcode 有两个会话 (sess-z 与作为下推干扰的 sess-z2), 所以查 zcode 时必须传
    session_id; 其余三个来源各只有一个会话, 不传即可。
    """
    hits = [s for s in sessions if s["source"] == source
            and (session_id is None or s["session_id"] == session_id)]
    assert len(hits) == 1, (f"{source}/{session_id} 应恰好匹配一个会话, "
                            f"实得 {len(hits)}: {[s['session_id'] for s in hits]}")
    return hits[0]


# 各来源的"主会话"标识: 供参数化用例统一取到同一个目标会话
MAIN_SESSION = {"zcode": "sess-z", "claudecode": "sess-cc",
                "codex": "sess-cx", "opencode": "sess-oc"}


def test_records_expose_ttft_for_zcode_only(card_db):
    """归一明细必须带 ttft_ms: zcode 取有效值, 其余来源恒 NULL。

    有效性沿用 _ZCODE_TTFT_SQL (0 <= ttft <= duration): 夹具里 z1/z2 有效,
    z3 (NULL) 与 z4 (9999 > duration 1000) 都必须落成 None —— 若实现漏了
    有效性判定, z4 会带着 9999 冒出来, 这里就会挂。
    """
    recs, total = db.unified_records_page("zcode", 1, 100)
    assert total == 6           # sess-z 四行 + 干扰会话 sess-z2 两行
    got = {r["source_record_id"]: r["ttft_ms"] for r in recs}
    assert got == {"zcode:z1": 200, "zcode:z2": 400, "zcode:z3": None,
                   "zcode:z4": None, "zcode:z5": None, "zcode:z6": None}
    for source in ("claudecode", "codex", "opencode"):
        rows, n = db.unified_records_page(source, 1, 100)
        assert n > 0, f"{source} 夹具没造数, 断言会空转"
        assert all(r["ttft_ms"] is None for r in rows), source


def test_unified_cols_include_ttft(card_db):
    """_UNIFIED_COLS 必须真的含 ttft_ms —— 会话聚合的 AVG(ttft_ms) 依赖它在投影里可见。"""
    assert "ttft_ms" in db._UNIFIED_COLS
    sql = db._unified_source_sql()
    sql = sql[0] if isinstance(sql, tuple) else sql   # 兼容性能计划已执行时的 (sql, params)
    rows = db.get_db().execute(
        f"SELECT ttft_ms FROM ({sql}) WHERE ttft_ms IS NOT NULL").fetchall()
    assert sorted(r["ttft_ms"] for r in rows) == [200, 400]


def test_session_ttft_aggregates_only_valid_samples(card_db):
    """zcode 会话的 avg_ttft_ms 只能由有效样本构成。

    夹具 sess-z 四行: ttft=200/400 有效, NULL 与 9999(>duration) 无效。
    故 avg = (200+400)/2 = 300.0, samples = 2 (不是 4, 也不是把 NULL 当 0 的 150)。
    """
    sessions, _ = db.unified_sessions_page("zcode", 1, 50)
    s = _session_by(sessions, "zcode", "sess-z")
    assert s["request_count"] == 4
    assert s["ttft_samples"] == 2
    assert s["avg_ttft_ms"] == 300.0


@pytest.mark.parametrize("source", ["claudecode", "codex", "opencode"])
def test_session_ttft_absent_for_non_zcode(card_db, source):
    """无 ttft 源列的来源: avg_ttft_ms 必须是 None 且 samples=0 (不可补 0)."""
    sessions, _ = db.unified_sessions_page(source, 1, 50)
    s = _session_by(sessions, source)
    assert s["avg_ttft_ms"] is None
    assert s["ttft_samples"] == 0


@pytest.mark.parametrize("source", ["zcode", "claudecode", "codex", "opencode"])
def test_session_hit_rate_uses_project_formula(card_db, source):
    """hit_rate 必须等于 hit/(hit+miss+cw)*100, 与 db.py 现有 15 处聚合同口径。

    这里不硬编码期望数字, 而是用同一行返回的三个分量现算再比对 —— 既锁死公式,
    又不会因为夹具调整而需要同步改期望值。若实现误用被否决的旧口径
    hit/(hit+miss), 分母少了 cw, 本断言立刻失败。
    """
    sessions, _ = db.unified_sessions_page(source, 1, 50)
    s = _session_by(sessions, source, MAIN_SESSION[source])
    hit = s["cache_hit_tokens"]
    miss = s["uncached_input_tokens"]
    cw = s["cache_write_tokens"]
    expected = round(hit / (hit + miss + cw) * 100, 2) if (hit + miss + cw) > 0 else 0.0
    assert s["hit_rate"] == expected
    assert 0.0 <= s["hit_rate"] <= 100.0


def test_session_hit_rate_denominator_includes_cache_write(card_db):
    """显式锁死"分母含 cache_write": 夹具 zcode 会话 cw=100 且不为 0,
    故正确口径必须严格小于漏掉 cw 的旧口径。"""
    sessions, _ = db.unified_sessions_page("zcode", 1, 50)
    s = _session_by(sessions, "zcode", "sess-z")
    hit, miss, cw = s["cache_hit_tokens"], s["uncached_input_tokens"], s["cache_write_tokens"]
    assert cw > 0, "夹具必须有 cache_write, 否则本断言空转"
    wrong_old = round(hit / (hit + miss) * 100, 2)
    assert s["hit_rate"] < wrong_old


def test_group_id_constant_is_single_source_of_truth(card_db):
    """会话聚合返回的 group_id 必须能由 _UNIFIED_GROUP_ID_SQL 在明细上重算出来。

    这是 Task 3 下钻的前提: 两处表达式若不一致, 过滤会静默漏行。
    """
    assert "_UNIFIED_GROUP_ID_SQL" in dir(db)
    sessions, _ = db.unified_sessions_page("all", 1, 50)
    got = {s["group_id"] for s in sessions}
    sql = db._unified_source_sql()
    sql = sql[0] if isinstance(sql, tuple) else sql
    rows = db.get_db().execute(
        f"SELECT DISTINCT {db._UNIFIED_GROUP_ID_SQL} AS g FROM ({sql})").fetchall()
    assert got == {r["g"] for r in rows}

