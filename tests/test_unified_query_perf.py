"""归一查询 (_unified_source_sql 族) 的特征化基线与查询计划断言。

特征化 (characterization) 用意: 本计划把"四表全量 UNION + 外层过滤排序"改写为
"按来源裁剪分段 + 过滤/排序/LIMIT 下推到基表", 要求返回值逐字段不变。这里先把
改写前的真实输出固化成断言, 重构时它们就是安全网 —— 不追求断言业务正确性,
只追求锁死当前行为。

造数风格对齐 tests/test_report_api.py:48-80 (直接 INSERT, 不引入 factory 库)。
"""
from __future__ import annotations

import pytest

from app import db

# 固定时间轴: 全部落在"今天"往前数几小时/几天内, 且一律 UTC 'Z' 字面量 ——
# 这正是 Task 5 要依赖的存储不变量。不用固定日期造数, 避免用例随真实日期过期;
# days 过滤的用例改为按"相对今天的天数"造行。
#
# 窗口内的行都在 2.5 天内, 越窗的行放到 300 天外 —— 刻意留出巨大间隔, 使
# CASES 里 days ∈ {1, 30} 的命中集在任何执行日都完全相同, 快照不会跨日漂移。
import datetime as _dt


def _iso(days_ago: float) -> str:
    """相对当前 UTC 时刻往前 days_ago 天的 ISO 'Z' 字面量 (毫秒精度)."""
    t = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days_ago)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


@pytest.fixture()
def unified_db(tmp_db):
    """四来源都有数据的临时库。

    刻意包含这些边界, 因为它们正是下推改写最容易踩的地方:
      - 三个远程渠道 (opencode/bai/commandcode) 共用 usage_records, 靠 accounts.source 区分;
      - 一行 usage_records 的 account_id 指向不存在的账号 (a.source 为 NULL),
        旧口径 COALESCE(a.source,'opencode') 把它算作 opencode —— 下推后必须保持;
      - zcode/codex 各有两行 started_at 完全相同 (并列), 用于验证 top-N 下推
        在页边界上的取舍与外层 source_record_id 次序一致;
      - 同一 model 名跨来源出现 (shared-model), 用于验证模型筛选不串来源。
    """
    ids = {
        "opencode": db.add_account("tok-oc", "ws-oc"),
        "bai": db.add_account("cookie-bai", "bai-user-1", switch=False,
                              source="bai", dedupe_key="bai-user-1"),
        "commandcode": db.add_account("tok-cc", "cc-user-1", switch=False,
                                      source="commandcode", dedupe_key="cc-user-1"),
    }
    conn = db.get_db()
    # --- usage_records: 每渠道 2 行 + 1 行孤儿账号 ---
    rows = []
    for name, acct in ids.items():
        for k in (0, 1):
            rows.append((f"{name}-{k}", _iso(k + 0.1), "shared-model" if k else f"{name}-m",
                         "anthropic", 100 + k, 20 + k, 0, 5, 1, 2, 0, 0.25, None,
                         f"sess-{name}", None, "2026-09-01T00:00:00", acct))
    rows.append(("orphan-0", _iso(0.2), "orphan-m", "anthropic", 7, 3, 0, 0, 0, 0,
                 0, 0.01, None, None, None, "2026-09-01T00:00:00", 99999))
    conn.executemany(
        "INSERT INTO usage_records (usg_id, created_at, model, provider, input_tokens,"
        " output_tokens, reasoning_tokens, cache_read_tokens, cache_write_5m_tokens,"
        " cache_write_1h_tokens, cost_raw, cost_usd, key_id, session_id, plan,"
        " synced_at, account_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    # --- zcode_usage: 4 行, 其中 z2/z3 的 started_at 完全并列; z4 在 300 天外 (越窗) ---
    tie = _iso(1.5)
    conn.executemany(
        "INSERT INTO zcode_usage (id, started_at, session_id, provider_id, provider_name,"
        " model_id, status, input_tokens, output_tokens, reasoning_tokens,"
        " cache_write_tokens, cache_read_tokens, total_tokens, duration_ms, ttft_ms,"
        " cost_raw, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("z1", _iso(0.3), "sess-z-1", "p1", "Provider1", "glm-4.6", "ok", 300, 120, 10,
          0, 50, 430, 4000, 500, 12_000_000, "2026-09-01T00:00:00"),
         ("z2", tie, "sess-z-1", "p1", "Provider1", "shared-model", "ok", 200, 80, 0,
          0, 20, 280, 3000, 400, 8_000_000, "2026-09-01T00:00:00"),
         ("z3", tie, "sess-z-2", "p1", "Provider1", "glm-4.6", "ok", 100, 40, 0,
          0, 10, 140, 2000, 300, 4_000_000, "2026-09-01T00:00:00"),
         ("z4", _iso(300), "sess-z-2", "p1", "Provider1", "glm-4.6", "ok", 90, 30, 0,
          0, 0, 120, 1500, 250, 3_000_000, "2026-09-01T00:00:00")])
    # --- claudecode_usage: 2 行, 一行落在 30 天窗口外 ---
    conn.executemany(
        "INSERT INTO claudecode_usage (dedupe_key, session_id, model, channel, started_at,"
        " input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, total_tokens,"
        " duration_ms, speed_tps, cost_raw, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [("cc1", "sess-cc-1", "claude-x", "api", _iso(0.4), 210, 90, 30, 0, 330,
          None, None, 9_000_000, "2026-09-01T00:00:00"),
         ("cc2", "sess-cc-2", "shared-model", "api", _iso(300), 110, 40, 0, 0, 150,
          None, None, 5_000_000, "2026-09-01T00:00:00")])
    conn.commit()
    # --- codex_usage: 走正式导入入口, 含一对 started_at 并列行 ---
    ctie = _iso(2.5)
    db.import_codex_usage([
        {"id": "cs:1", "session_id": "cs", "event_seq": 1, "event_mode": "token_count",
         "response_id": None, "started_at": _iso(0.5), "model": "gpt-5",
         "provider_id": "codex", "input_tokens": 400, "cache_read_tokens": 60,
         "cache_write_tokens": 0, "output_tokens": 150, "reasoning_tokens": 20,
         "total_tokens": 570, "duration_ms": 5000, "speed_tps": 30.0,
         "speed_source": "duration", "request_count_exact": True,
         "model_revision_at": 0, "cost_raw": None, "file_path": "f.jsonl"},
        {"id": "cs:2", "session_id": "cs", "event_seq": 2, "event_mode": "token_count",
         "response_id": None, "started_at": ctie, "model": "shared-model",
         "provider_id": "codex", "input_tokens": 100, "cache_read_tokens": 0,
         "cache_write_tokens": 0, "output_tokens": 40, "reasoning_tokens": 0,
         "total_tokens": 140, "duration_ms": None, "speed_tps": None,
         "speed_source": None, "request_count_exact": False,
         "model_revision_at": 0, "cost_raw": None, "file_path": "f.jsonl"},
        {"id": "cs:3", "session_id": "cs", "event_seq": 3, "event_mode": "token_count",
         "response_id": None, "started_at": ctie, "model": "gpt-5",
         "provider_id": "codex", "input_tokens": 90, "cache_read_tokens": 0,
         "cache_write_tokens": 0, "output_tokens": 30, "reasoning_tokens": 0,
         "total_tokens": 120, "duration_ms": None, "speed_tps": None,
         "speed_source": None, "request_count_exact": False,
         "model_revision_at": 0, "cost_raw": None, "file_path": "f.jsonl"},
    ])
    yield tmp_db


SOURCES = ("all", "opencode", "bai", "commandcode", "zcode", "claudecode", "codex")

# (source, model, days, page) 组合矩阵: 覆盖裁剪 / 模型筛选 / days 窗口 / 翻页与尾页
CASES: list[tuple[str, str | None, int | None, int]] = [
    *[(s, None, None, 1) for s in SOURCES],
    ("all", None, None, 2),
    ("all", None, None, 3),
    ("all", "shared-model", None, 1),
    ("all", None, 30, 1),
    ("all", "shared-model", 30, 1),
    ("zcode", "glm-4.6", None, 1),
    ("zcode", None, 30, 1),
    ("zcode", None, 1, 1),
    ("claudecode", None, 30, 1),
    ("codex", "gpt-5", None, 1),
    ("opencode", None, 30, 1),
    ("all", None, None, 99),          # 越界页: 必须空列表且 total 不变
]


def plan_of(sql: str, params: list) -> list[str]:
    """EXPLAIN QUERY PLAN 的人类可读描述行 (第 4 列)."""
    return [r[3] for r in db.get_db().execute("EXPLAIN QUERY PLAN " + sql, params)]


import json
import pathlib

SNAPSHOT = pathlib.Path(__file__).with_name("unified_query_snapshot.json")


def _capture() -> dict:
    """把 CASES 上三个公开出口的完整输出序列化 (排序稳定, 可逐字段比对).

    注意: 造数用相对"现在"的时间, 故快照里不能存 started_at 原值 —— 它每次运行都变。
    改存"除时间字段外的全部字段" + 各行时间的相对次序, 既锁死行为又不受运行时刻影响。
    """
    out: dict = {}
    for source, model, days, page in CASES:
        key = f"{source}|{model}|{days}|{page}"
        recs, total = db.unified_records_page(source, page, 7, model, days)
        sess, stotal = db.unified_sessions_page(source, page, 7, model, days)
        out[key] = {
            "records_total": total,
            "records": [{k: v for k, v in r.items() if k != "started_at"} for r in recs],
            "records_order": [r["source_record_id"] for r in recs],
            "sessions_total": stotal,
            "sessions": [{k: v for k, v in s.items() if k not in ("started_at", "last_at")}
                         for s in sess],
            "models": db.unified_models(source, days),
        }
    return out


def test_unified_output_matches_snapshot(unified_db):
    """归一查询三出口的输出必须与快照逐字段一致 (行为零变化的安全网).

    首次运行会写出快照并 skip; 之后每次运行都做严格比对。
    重构中若此用例失败, 说明改写改变了行为 —— 是 bug, 不要更新快照;
    只有在故意变更口径时才删除快照文件重生成, 且必须在 commit message 里说明。
    """
    current = _capture()
    if not SNAPSHOT.exists():
        SNAPSHOT.write_text(json.dumps(current, ensure_ascii=False, indent=2,
                                       sort_keys=True), encoding="utf-8")
        pytest.skip("快照已生成, 请复跑本用例以进入比对模式")
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert current == expected


TIME_COLUMNS = [("usage_records", "created_at"), ("zcode_usage", "started_at"),
                ("claudecode_usage", "started_at"), ("codex_usage", "started_at")]


@pytest.mark.parametrize("table,col", TIME_COLUMNS)
def test_time_columns_are_utc_z_literals(unified_db, table, col):
    """归一查询把 days 过滤做成字典序比较 (见 _unified_days_bound), 前提是这四列
    一律存 UTC ISO 'YYYY-MM-DDTHH:MM:SS[.ffffff]Z'。任何采集层改成本地时间或带
    '+08:00' 偏移, 都会让 days 窗口静默算错 —— 这个用例就是那道闸门。"""
    conn = db.get_db()
    total = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
    assert total > 0, "夹具未给该表造数, 断言会空转"
    bad = conn.execute(
        f"SELECT COUNT(*) c FROM {table} "
        f"WHERE {col} NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T*Z'"
    ).fetchone()["c"]
    assert bad == 0


