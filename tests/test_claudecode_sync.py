"""Claude Code 本地用量落库层测试: 建表迁移/导入幂等/总量大者胜/进度/启用时刻/聚合.

全部走临时目录 + monkeypatch, 不读本机真实 ~/.claude 文件.
fixture 模式照 test_zcode_sync.py 的 tmp_db.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import claudecode_api
from app import db
from app import server

# 手工定价表 (每百万 token 的 USD 价), 不依赖本机真实定价文件:
# cost_raw = round((inp*1 + out*3 + cr*0.2 + cw*0.5) / 1e6 * 1e8)
PRICING = [
    {
        "modelId": "glm-5.3",
        "inputCostPerMillion": 1.0,
        "outputCostPerMillion": 3.0,
        "cacheReadCostPerMillion": 0.2,
        "cacheCreationCostPerMillion": 0.5,
    },
]


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时 GoGauge 库: 重定向 data_dir 并重置模块级连接."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


def _row(dedupe_key, started_at="2026-08-01T12:00:00Z", **overrides):
    """构造一行采集层产出的行 dict (§6 键契约; 默认值对应 cost_raw=39250)."""
    values = {
        "dedupe_key": dedupe_key,
        "session_id": "sess-1",
        "project_path": "C:\\proj",
        "model": "glm-5.3",
        "channel": "官方",
        "started_at": started_at,
        "input_tokens": 50,
        "output_tokens": 100,
        "cache_read_tokens": 200,
        "cache_write_tokens": 5,
        "total_tokens": 355,
        "duration_ms": 1000,
        "speed_tps": None,
        "file_path": "C:\\fake\\.claude\\projects\\p\\sess-1.jsonl",
    }
    values.update(overrides)
    return values


def _count(table="claudecode_usage") -> int:
    return int(db.get_db().execute(
        f"SELECT COUNT(*) AS c FROM {table}"
    ).fetchone()["c"])


# ---------------------------------------------------------------------------
# 1. 建表迁移 (两张表 + 三个索引; 重复初始化幂等且数据保留)
# ---------------------------------------------------------------------------


def test_schema_created_and_migration_idempotent(tmp_db):
    names = {r["name"] for r in db.get_db().execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table', 'index')"
    ).fetchall()}
    assert {"claudecode_usage", "claude_file_progress",
            "idx_cc_time", "idx_cc_channel", "idx_cc_model"} <= names
    # 写入一行后关闭重开: CREATE IF NOT EXISTS 幂等, 数据保留
    assert db.import_claudecode_usage([_row("m1")], PRICING) == 1
    db.close_db()
    assert _count() == 1


# ---------------------------------------------------------------------------
# 2. 导入与幂等
# ---------------------------------------------------------------------------


def test_first_import_and_cost_estimation(tmp_db):
    # 手算: (50*1 + 100*3 + 200*0.2 + 5*0.5)/1e6*1e8 = 39250; 未收录模型 → 0
    assert db.import_claudecode_usage([
        _row("m1", "2024-09-02T18:00:00Z"),
        _row("m2", "2024-09-02T18:00:01Z", model="unknown-model"),
    ], PRICING) == 2
    r = db.get_db().execute(
        "SELECT * FROM claudecode_usage WHERE dedupe_key = 'm1'"
    ).fetchone()
    assert r["session_id"] == "sess-1"
    assert r["project_path"] == "C:\\proj"
    assert r["model"] == "glm-5.3"
    assert r["channel"] == "官方"
    assert r["started_at"] == "2024-09-02T18:00:00Z"   # 采集层已转好, 原样落库
    assert r["input_tokens"] == 50
    assert r["output_tokens"] == 100
    assert r["cache_read_tokens"] == 200
    assert r["cache_write_tokens"] == 5
    assert r["total_tokens"] == 355
    assert r["duration_ms"] == 1000
    assert r["speed_tps"] is None                    # 解析层算好, 缺省 NULL
    assert r["file_path"].endswith("sess-1.jsonl")
    assert r["cost_raw"] == 39250
    assert r["updated_at"] is None                     # 首插不写修订标记
    assert r["synced_at"].endswith("Z")
    r2 = db.get_db().execute(
        "SELECT cost_raw FROM claudecode_usage WHERE dedupe_key = 'm2'"
    ).fetchone()
    assert r2["cost_raw"] == 0                         # 未收录模型 cost 0


def test_import_empty_rows(tmp_db):
    assert db.import_claudecode_usage([], PRICING) == 0
    assert _count() == 0


def test_idempotent_reimport(tmp_db):
    rows = [_row("m1"), _row("m2", "2026-08-01T12:00:01Z")]
    assert db.import_claudecode_usage(rows, PRICING) == 2
    assert db.import_claudecode_usage(rows, PRICING) == 0  # 同批重复导入 → 新增 0
    assert _count() == 2


def test_revision_winner_is_larger_total(tmp_db, monkeypatch):
    # 固定 _now_iso, 使各次导入的 synced_at/updated_at 可断言
    clock = ["2026-01-01T00:00:00Z"]
    monkeypatch.setattr(db, "_now_iso", lambda: clock[0])
    assert db.import_claudecode_usage([_row("m1")], PRICING) == 1
    r = db.get_db().execute(
        "SELECT * FROM claudecode_usage WHERE dedupe_key = 'm1'"
    ).fetchone()
    assert r["synced_at"] == "2026-01-01T00:00:00Z"
    assert r["updated_at"] is None

    # 同键更大 total → 修订: token/cost/model/speed_tps/updated_at 更新, 归属列首插为准
    clock[0] = "2026-01-02T00:00:00Z"
    assert db.import_claudecode_usage([
        # (60*1 + 200*3 + 300*0.2 + 10*0.5)*100 = 72500
        # (model 用大小写变体: 证明 model 参与覆盖, 且费用按归一后的 glm-5.3 计)
        _row("m1", "2026-01-02T10:00:00Z", model="GLM-5.3",
             channel="中转X", session_id="sess-9", project_path="D:\\other",
             file_path="D:\\other.jsonl", input_tokens=60, output_tokens=200,
             cache_read_tokens=300, cache_write_tokens=10, total_tokens=570,
             duration_ms=2000, speed_tps=250.0),
    ], PRICING) == 0                                # 修订不算新增
    r = db.get_db().execute(
        "SELECT * FROM claudecode_usage WHERE dedupe_key = 'm1'"
    ).fetchone()
    assert _count() == 1
    assert r["total_tokens"] == 570
    assert (r["input_tokens"], r["output_tokens"],
            r["cache_read_tokens"], r["cache_write_tokens"]) == (60, 200, 300, 10)
    assert r["model"] == "GLM-5.3"                  # model 参与覆盖
    assert r["duration_ms"] == 2000
    assert r["speed_tps"] == 250.0                  # speed_tps 随大者胜更新
    assert r["started_at"] == "2026-01-02T10:00:00Z"
    assert r["cost_raw"] == 72500                   # 修订行同步重算费用
    assert r["updated_at"] == "2026-01-02T00:00:00Z"  # 修订标记
    assert r["channel"] == "官方"                   # 归属列首插为准
    assert r["session_id"] == "sess-1"
    assert r["project_path"] == "C:\\proj"
    assert r["file_path"].endswith("sess-1.jsonl")
    assert r["synced_at"] == "2026-01-01T00:00:00Z"  # synced_at 首插为准

    # 更小 total → 不修订 (历史/分叉行不打回已累计的终值; speed_tps 也不被打回)
    clock[0] = "2026-01-03T00:00:00Z"
    db.import_claudecode_usage([
        _row("m1", input_tokens=1, output_tokens=2,
             cache_read_tokens=0, cache_write_tokens=0, total_tokens=3,
             speed_tps=999.0),
    ], PRICING)
    r = db.get_db().execute(
        "SELECT total_tokens, cost_raw, speed_tps, updated_at FROM claudecode_usage"
        " WHERE dedupe_key = 'm1'"
    ).fetchone()
    assert r["total_tokens"] == 570
    assert r["cost_raw"] == 72500
    assert r["speed_tps"] == 250.0                    # 小者不胜 → 不更新
    assert r["updated_at"] == "2026-01-02T00:00:00Z"  # 修订标记不被触碰

    # 相等 total → 同样不修订 (幂等)
    clock[0] = "2026-01-04T00:00:00Z"
    db.import_claudecode_usage([
        _row("m1", input_tokens=60, output_tokens=200,
             cache_read_tokens=300, cache_write_tokens=10, total_tokens=570),
    ], PRICING)
    r = db.get_db().execute(
        "SELECT updated_at FROM claudecode_usage WHERE dedupe_key = 'm1'"
    ).fetchone()
    assert r["updated_at"] == "2026-01-02T00:00:00Z"


# ---------------------------------------------------------------------------
# 3. 启用时刻 (settings payload 白名单外键)
# ---------------------------------------------------------------------------


def test_enabled_at_roundtrip(tmp_db):
    assert db.get_claudecode_enabled_at() == 0      # 缺失 → 0
    db.save_claudecode_enabled_at(1725300000123)
    assert db.get_claudecode_enabled_at() == 1725300000123
    # 白名单外键不污染设置 API
    assert "claudecode_enabled_at" not in db.get_settings()
    # 保存设置不丢启用时刻 (save_settings 保留非白名单键)
    db.save_settings({"sync_interval_sec": 60})
    assert db.get_claudecode_enabled_at() == 1725300000123


# ---------------------------------------------------------------------------
# 4. 文件续读进度 (推进/回退均原样存储, 回退由采集编排侧决定)
# ---------------------------------------------------------------------------


def test_file_progress_roundtrip(tmp_db):
    assert db.get_claude_file_progress_all() == {}
    db.save_claude_file_progress("p1.jsonl", 100, 500)
    db.save_claude_file_progress("p2.jsonl", 0, 10)
    assert db.get_claude_file_progress_all() == {
        "p1.jsonl": (100, 500),
        "p2.jsonl": (0, 10),
    }
    # 推进
    db.save_claude_file_progress("p1.jsonl", 300, 500)
    assert db.get_claude_file_progress_all()["p1.jsonl"] == (300, 500)
    # 回退 (文件被重写变小 → 编排侧重置 offset=0 全量重读)
    db.save_claude_file_progress("p1.jsonl", 0, 100)
    assert db.get_claude_file_progress_all() == {
        "p1.jsonl": (0, 100),
        "p2.jsonl": (0, 10),
    }


# ---------------------------------------------------------------------------
# 5. 最近导入时刻
# ---------------------------------------------------------------------------


def test_last_import_at(tmp_db, monkeypatch):
    assert db.claudecode_last_import_at() is None   # 空表 → None
    clock = ["2026-01-01T00:00:00Z"]
    monkeypatch.setattr(db, "_now_iso", lambda: clock[0])
    db.import_claudecode_usage([_row("m1")], PRICING)
    clock[0] = "2026-01-02T00:00:00Z"
    db.import_claudecode_usage([_row("m2", "2026-08-01T12:00:01Z")], PRICING)
    # 修订导入也推进 synced_at? 否: synced_at 首插为准 → MAX 取最后一次新增
    assert db.claudecode_last_import_at() == "2026-01-02T00:00:00Z"


# ---------------------------------------------------------------------------
# 6. 秒速聚合 (存储列语义: speed_tps 由采集解析时按实施文档 §2 口径算好随行
#    落库, 查询侧仅 AVG/MAX, NULL 不参与聚合; 解析层的逐行计算与噪声过滤
#    覆盖见 test_claudecode_api.py)
# ---------------------------------------------------------------------------


def test_speed_metrics_hand_computed(tmp_db):
    assert db.import_claudecode_usage([
        _row("a", speed_tps=100.0),
        _row("b", speed_tps=200.0),
        _row("c", speed_tps=None),                  # NULL 不参与 AVG/MAX
    ], PRICING) == 3
    t = db.claudecode_totals("all")
    assert t["avg_tps"] == 150.0                    # (100+200)/2
    assert t["max_tps"] == 200.0


def test_speed_no_trusted_samples_returns_none(tmp_db):
    # 全部行 speed_tps 为 NULL (单行/解析层噪声过滤): AVG/MAX 忽略 NULL → None
    assert db.import_claudecode_usage([
        _row("x", speed_tps=None),
    ], PRICING) == 1
    t = db.claudecode_totals("all")
    assert t["avg_tps"] is None
    assert t["max_tps"] is None
    # 无 reasoning 维度 (与 zcode totals 的字段差异)
    assert "total_reasoning_tokens" not in t


# ---------------------------------------------------------------------------
# 7. period 过滤 (today / all / Nd)
# ---------------------------------------------------------------------------


def test_period_filters(tmp_db):
    local_midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    today_iso = datetime.fromtimestamp(
        (local_midnight + timedelta(minutes=30)).timestamp(), timezone.utc
    ).isoformat().replace("+00:00", "Z")
    days_ago_iso = lambda d: (datetime.now(timezone.utc) - timedelta(days=d)) \
        .isoformat().replace("+00:00", "Z")
    db.import_claudecode_usage([
        _row("today_row", today_iso),
        _row("recent_row", days_ago_iso(5)),
        _row("old_row", days_ago_iso(40)),
    ], PRICING)
    assert db.claudecode_totals("all")["request_count"] == 3
    assert db.claudecode_totals("7d")["request_count"] == 2     # today + 5d
    assert db.claudecode_totals()["request_count"] == 2         # 默认 30d
    assert db.claudecode_totals("today")["request_count"] == 1  # 本地今天
    assert db.claudecode_totals("today")["total_tokens"] == 355
    assert db.claudecode_channel_stats("today")[0]["channel"] == "官方"
    assert [m["model"] for m in db.claudecode_model_stats("today")] == ["glm-5.3"]


# ---------------------------------------------------------------------------
# 8. 四层聚合数值 (手算)
# ---------------------------------------------------------------------------


def test_four_layer_aggregates(tmp_db):
    # r1: cost_raw = (100*1 + 200*3 + 50*0.2 + 10*0.5)*100 = 71500
    #     speed_tps = 250 (解析时算好落库)
    # r2: model m2 未收录定价表 → cost_raw = 0; speed_tps = 80
    db.import_claudecode_usage([
        _row("r1", "2025-12-30T10:00:00Z", channel="官方", model="glm-5.3",
             input_tokens=100, output_tokens=200, cache_read_tokens=50,
             cache_write_tokens=10, total_tokens=360, duration_ms=800,
             speed_tps=250.0),
        _row("r2", "2025-12-31T10:00:00Z", channel="glm", model="m2",
             input_tokens=20, output_tokens=40, cache_read_tokens=0,
             cache_write_tokens=0, total_tokens=60, duration_ms=500,
             speed_tps=80.0),
    ], PRICING)

    # --- totals ---
    t = db.claudecode_totals("all")
    assert t["request_count"] == 2
    assert t["total_input_tokens"] == 180           # (100+50+10) + 20
    assert t["uncached_input_tokens"] == 120        # 100 + 20
    assert t["cache_hit_tokens"] == 50
    assert t["cache_write_tokens"] == 10
    assert t["total_output_tokens"] == 240          # 200 + 40
    assert t["total_tokens"] == 420                 # 360 + 60
    assert t["total_cost_usd"] == 0.000715          # (71500+0)/1e8
    assert t["avg_tps"] == 165.0                    # (250+80)/2
    assert t["max_tps"] == 250.0

    # --- channel stats (按 输入+输出 降序) ---
    channels = db.claudecode_channel_stats("all")
    assert [c["channel"] for c in channels] == ["官方", "glm"]
    c1, c2 = channels
    assert c1["request_count"] == 1
    assert c1["total_input_tokens"] == 160
    assert c1["total_output_tokens"] == 200
    assert c1["total_tokens"] == 360
    assert c1["total_cost_usd"] == 0.000715
    assert c1["avg_tps"] == 250.0
    assert c1["max_tps"] == 250.0
    assert c2["total_cost_usd"] == 0.0
    assert c2["avg_tps"] == 80.0

    # --- model stats (按 输入+输出 降序) ---
    models = db.claudecode_model_stats("all")
    assert [m["model"] for m in models] == ["glm-5.3", "m2"]
    assert models[0]["request_count"] == 1
    assert models[0]["total_tokens"] == 360
    assert models[0]["total_cost_usd"] == 0.000715
    assert models[1]["total_cost_usd"] == 0.0

    # --- daily (固定窗口, 两天各一行) ---
    daily = db.claudecode_daily(365)
    assert [d["date"] for d in daily] == ["2025-12-30", "2025-12-31"]
    assert [d["request_count"] for d in daily] == [1, 1]
    assert [d["total_tokens"] for d in daily] == [360, 60]
    assert [d["total_cost_usd"] for d in daily] == [0.000715, 0.0]
    assert "avg_tps" not in daily[0]                # daily 无速度列


# ---------------------------------------------------------------------------
# 9. 跨本地日归组
# ---------------------------------------------------------------------------


def test_daily_groups_by_local_day(tmp_db):
    local_midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    to_iso = lambda dt: datetime.fromtimestamp(
        dt.timestamp(), timezone.utc
    ).isoformat().replace("+00:00", "Z")
    # 本地今天 00:30 与本地昨天 23:30 各一行 → 归入两个不同的本地日
    db.import_claudecode_usage([
        _row("today_row", to_iso(local_midnight + timedelta(minutes=30))),
        _row("yest_row", to_iso(local_midnight - timedelta(minutes=30))),
    ], PRICING)
    daily = db.claudecode_daily(days=7)
    assert [d["date"] for d in daily] == [
        (local_midnight - timedelta(days=1)).strftime("%Y-%m-%d"),
        local_midnight.strftime("%Y-%m-%d"),
    ]
    assert [d["request_count"] for d in daily] == [1, 1]


# ---------------------------------------------------------------------------
# 10. 空表 / 无数据
# ---------------------------------------------------------------------------


def test_empty_aggregates(tmp_db):
    t = db.claudecode_totals("30d")
    assert t["request_count"] == 0
    assert t["total_input_tokens"] == 0
    assert t["total_output_tokens"] == 0
    assert t["total_tokens"] == 0
    assert t["total_cost_usd"] == 0.0
    assert t["avg_tps"] is None
    assert t["max_tps"] is None
    assert db.claudecode_daily(7) == []
    assert db.claudecode_channel_stats("30d") == []
    assert db.claudecode_model_stats("30d") == []


# ---------------------------------------------------------------------------
# 11. cc-switch 代理差集对账 (merge_proxy_gap 纯函数; 采集出口集成属后续任务)
# ---------------------------------------------------------------------------

# created_at Unix 秒基准: 1757255520 = 2025-09-07T14:32:00.000Z (UTC)
PROXY_TS = 1_757_255_520
PROXY_TS_ISO = "2025-09-07T14:32:00.000Z"


def _proxy_row(**overrides):
    """构造一条 cc-switch proxy 记录 (键名逐字照 proxy_request_logs 采集契约)."""
    values = {
        "request_id": "session:msg_gap_1",
        "session_id": "sess-proxy",
        "model": "glm-5.3",
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_tokens": 30,
        "cache_creation_tokens": 4,
        "total_cost_usd": 0.0000123,
        "created_at": PROXY_TS,
        "status_code": 200,
        "data_source": "proxy",
        "app_type": "claude",
    }
    values.update(overrides)
    return values


def test_proxy_gap_id_match_skipped():
    """场景 1: proxy msg id 已在 jsonl_keys → 同一次调用, 不产出."""
    rows = claudecode_api.merge_proxy_gap({"msg_gap_1"}, [_proxy_row()])
    assert rows == []


def test_proxy_gap_row_built_for_missing_id():
    """场景 2: 差集补充 → 产出行, dedupe_key 无前缀/四项/total/started_at 正确;
    token 四项 NULL→0, 行内无 cost 键 (import 层按定价表自算)."""
    rows = claudecode_api.merge_proxy_gap({"msg_other"}, [
        _proxy_row(request_id="session:msg_gap_1"),
        _proxy_row(request_id="session:msg_null_tok", input_tokens=None,
                   output_tokens=None, cache_read_tokens=None,
                   cache_creation_tokens=None),
    ])
    assert len(rows) == 2
    row = rows[0]
    assert row["dedupe_key"] == "msg_gap_1"   # 不加 session: 前缀 (共用键空间)
    assert row["session_id"] == "sess-proxy"
    assert row["project_path"] is None
    assert row["model"] == "glm-5.3"
    assert row["channel"] is None             # channel 判定不在本函数做
    assert row["started_at"] == PROXY_TS_ISO
    assert (row["input_tokens"], row["output_tokens"],
            row["cache_read_tokens"], row["cache_write_tokens"]) == (10, 20, 30, 4)
    assert row["total_tokens"] == 64          # 四项之和
    assert row["duration_ms"] is None
    assert row["speed_tps"] is None           # 快照 token 不参与速度统计
    assert row["file_path"] == "cc-switch:proxy"
    assert "total_cost_usd" not in row and "cost_raw" not in row
    # NULL token → 0
    assert (rows[1]["input_tokens"], rows[1]["output_tokens"],
            rows[1]["cache_read_tokens"],
            rows[1]["cache_write_tokens"]) == (0, 0, 0, 0)
    assert rows[1]["total_tokens"] == 0


def test_proxy_gap_filter_criteria():
    """场景 3: 过滤口径 — app_type 非 claude / data_source 非 proxy /
    status_code≠200 → 不产出 (末行基准对照, 证明非全跳)."""
    rows = claudecode_api.merge_proxy_gap(set(), [
        _proxy_row(app_type="codex"),
        _proxy_row(data_source="api"),
        _proxy_row(status_code=500),
        _proxy_row(status_code=None),
        _proxy_row(),
    ])
    assert len(rows) == 1
    assert rows[0]["dedupe_key"] == "msg_gap_1"


def test_proxy_gap_nonstandard_request_id_skipped():
    """场景 4: request_id None/空串/裸 UUID/前缀后为空 → 不产出."""
    rows = claudecode_api.merge_proxy_gap(set(), [
        _proxy_row(request_id=None),
        _proxy_row(request_id=""),
        _proxy_row(request_id="3f2a9c1e-8b4d-4c3a-9e2f-1a2b3c4d5e6f"),
        _proxy_row(request_id="session:"),
    ])
    assert rows == []


def test_proxy_gap_same_id_on_both_sides_skipped():
    """场景 5: 键融合自愈前置 — 同 msg id 两侧都有 (token 不同) → 差集行不
    产出 (id 相同即跳过, JSONL 最终值为准; upsert 覆盖属 import 层既有测试)."""
    proxy_rows = [_proxy_row(
        request_id="session:msg_both",
        input_tokens=1, output_tokens=2,
        cache_read_tokens=0, cache_creation_tokens=0,
    )]
    assert claudecode_api.merge_proxy_gap({"msg_both"}, proxy_rows) == []


def test_proxy_gap_started_at_unix_seconds_to_utc_iso():
    """场景 6: created_at Unix 秒 → UTC ISO (Z 后缀, 毫秒精度, 同 JSONL 行)."""
    rows = claudecode_api.merge_proxy_gap(
        set(), [_proxy_row(created_at=1_725_300_000)]  # 2024-09-02T18:00:00Z
    )
    assert rows[0]["started_at"] == "2024-09-02T18:00:00.000Z"


# ---------------------------------------------------------------------------
# 12. 采集出口集成 (cc-switch 差集补录: 只读读取 → 对账 → 落库 → 水位;
#     proxy 读取一律 monkeypatch 注入/路径重定向, 不触真 ~/.cc-switch 库)
# ---------------------------------------------------------------------------

_PROXY_COLS = ("request_id", "session_id", "model", "input_tokens",
               "output_tokens", "cache_read_tokens", "cache_creation_tokens",
               "total_cost_usd", "created_at", "status_code", "data_source",
               "app_type")


def _install_proxy_db(path, rows) -> None:
    """临时 cc-switch 形状库 (仅采集 SQL 用到的 12 列), 供路径重定向测试."""
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE proxy_request_logs (
               request_id TEXT, session_id TEXT, model TEXT,
               input_tokens INTEGER, output_tokens INTEGER,
               cache_read_tokens INTEGER, cache_creation_tokens INTEGER,
               total_cost_usd REAL, created_at INTEGER, status_code INTEGER,
               data_source TEXT, app_type TEXT)"""
    )
    conn.executemany(
        "INSERT INTO proxy_request_logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [tuple(r[k] for k in _PROXY_COLS) for r in rows],
    )
    conn.commit()
    conn.close()


def _proxy_file_count() -> int:
    return int(db.get_db().execute(
        "SELECT COUNT(*) AS c FROM claudecode_usage WHERE file_path = 'cc-switch:proxy'"
    ).fetchone()["c"])


def test_proxy_gap_end_to_end_imported_and_totals_grow(tmp_db, monkeypatch):
    """差集行端到端: 注入假 proxy 行 (monkeypatch read_proxy_rows) →
    server._sync_cc_proxy_gap 对账落库 → totals 请求数/token 增加;
    对账基准 = claudecode_usage 全集 (JSONL 已有 m1 跳过, 非本次增量 rows);
    落库前盖 channel 章 (同 JSONL 行判定口径)."""
    assert db.import_claudecode_usage([_row("m1")], PRICING) == 1  # JSONL 侧已有
    db.save_claudecode_enabled_at((PROXY_TS - 10) * 1000)  # 启用先于差集行
    monkeypatch.setattr(claudecode_api, "read_base_url",
                        lambda: "relay.example.com")     # 每轮渠道快照
    fake_rows = [
        _proxy_row(request_id="session:m1", created_at=PROXY_TS),  # JSONL 已有 → 跳过
        _proxy_row(request_id="session:gap_a", created_at=PROXY_TS,
                   input_tokens=100, output_tokens=200,
                   cache_read_tokens=0, cache_creation_tokens=0),  # total 300
        _proxy_row(request_id="session:gap_b", created_at=PROXY_TS + 1,
                   input_tokens=1, output_tokens=2,
                   cache_read_tokens=3, cache_creation_tokens=4),  # total 10
    ]
    monkeypatch.setattr(claudecode_api, "read_proxy_rows",
                        lambda since: (fake_rows, None))

    assert server._sync_cc_proxy_gap(PRICING) == (2, None)

    t = db.claudecode_totals("all")
    assert t["request_count"] == 3                    # m1 + gap_a + gap_b
    assert t["total_tokens"] == 355 + 300 + 10        # 665
    r = db.get_db().execute(
        "SELECT file_path, channel FROM claudecode_usage WHERE dedupe_key = 'gap_a'"
    ).fetchone()
    assert r["file_path"] == "cc-switch:proxy"        # 溯源标记
    assert r["channel"] == "relay.example.com"        # 已盖章 (启用后 → base_url)
    assert db.get_cc_proxy_watermark() == PROXY_TS + 1  # 本批最大 created_at
    # 白名单外键真验证: 原始 payload 实际存了该键, 设置 API 白名单不暴露
    assert "claudecode_proxy_watermark" in db._raw_payload(db.get_db())
    assert "claudecode_proxy_watermark" not in db.get_settings()


def test_proxy_gap_then_jsonl_larger_total_overwrites_tokens_keeps_channel(
        tmp_db, monkeypatch):
    """组合端到端: 先落差集行 (小 total, 已盖 channel 章), 再走 JSONL 落库
    路径导入同 msg id、更大 total 的行 → token 大者胜被覆盖, channel 归属
    列首插为准 (保持差集行盖章值, 不被打回 NULL/JSONL 侧值)."""
    db.save_claudecode_enabled_at((PROXY_TS - 10) * 1000)
    monkeypatch.setattr(claudecode_api, "read_base_url",
                        lambda: "relay.example.com")
    monkeypatch.setattr(
        claudecode_api, "read_proxy_rows",
        lambda since: ([_proxy_row(request_id="session:m_both",
                                   input_tokens=10, output_tokens=20,
                                   cache_read_tokens=30,
                                   cache_creation_tokens=4)], None))  # total 64

    assert server._sync_cc_proxy_gap(PRICING) == (1, None)
    r = db.get_db().execute(
        "SELECT total_tokens, channel, file_path FROM claudecode_usage"
        " WHERE dedupe_key = 'm_both'").fetchone()
    assert r["total_tokens"] == 64
    assert r["channel"] == "relay.example.com"        # F1 盖章已生效
    assert r["file_path"] == "cc-switch:proxy"

    # JSONL 后到: 同 msg id、更大 total (355)、channel 不同 → token 覆盖,
    # channel/file_path 归属列首插为准
    assert db.import_claudecode_usage(
        [_row("m_both", channel="官方")], PRICING) == 0   # 修订不算新增
    r = db.get_db().execute(
        "SELECT total_tokens, channel, file_path FROM claudecode_usage"
        " WHERE dedupe_key = 'm_both'").fetchone()
    assert r["total_tokens"] == 355                   # 大者胜
    assert r["channel"] == "relay.example.com"        # 保持差集行盖章值
    assert r["file_path"] == "cc-switch:proxy"


def test_proxy_gap_degraded_missing_db_sync_still_succeeds(tmp_db, monkeypatch):
    """降级: cc-switch.db 不存在 (改名验证的等价注入) → 同步成功且结果与纯
    JSONL 一致, 不记错误 (未装 cc-switch 属正常形态); 库文件损坏 (打开失败)
    → 仍成功完成同步, 错误文案可见, JSONL 数据不受影响."""
    monkeypatch.setattr(server, "_cc_sync_error", "")
    monkeypatch.setattr(db, "get_claudecode_enabled_at", lambda: 1_000)
    monkeypatch.setattr(db, "get_claude_file_progress_all", lambda: {})
    monkeypatch.setattr(server, "_load_model_pricing", lambda: PRICING)
    monkeypatch.setattr(claudecode_api, "import_incremental",
                        lambda enabled_at, progress, force=False: [
                            {"path": "/p/a.jsonl", "rows": [_row("m_jsonl")],
                             "new_offset": 10, "size": 10}])
    monkeypatch.setattr(claudecode_api, "CC_SWITCH_DB_PATH",
                        tmp_db / "cc-switch" / "missing.db")

    assert server._sync_claude_local() == 1           # JSONL 行照常落库
    assert server._cc_sync_error == ""                # 缺文件静默降级不报错
    t = db.claudecode_totals("all")
    assert t["request_count"] == 1 and t["total_tokens"] == 355  # 纯 JSONL 口径
    assert _proxy_file_count() == 0

    # 打开/查询失败 (坏库文件) → 记错误文案, 不中断不崩
    bad = tmp_db / "bad.db"
    bad.write_bytes(b"not a sqlite database")
    monkeypatch.setattr(claudecode_api, "CC_SWITCH_DB_PATH", bad)
    monkeypatch.setattr(claudecode_api, "import_incremental",
                        lambda enabled_at, progress, force=False: [])
    assert server._sync_claude_local() == 0
    assert server._cc_sync_error                      # 错误已记录
    assert db.claudecode_totals("all")["request_count"] == 1


def test_proxy_gap_watermark_advances_and_skips_refetched_batch(tmp_db, monkeypatch):
    """水位: 首刷 since=0 全量拉取并落库 → 水位推进为本批最大 created_at
    (含被过滤行 — 已拉取即推进); 第二次调用以水位为 since, 同批行不再进入
    对账, 库内差集行不重复."""
    proxy_rows = [
        _proxy_row(request_id="session:w1", created_at=PROXY_TS),
        _proxy_row(request_id="session:w2", created_at=PROXY_TS + 5,
                   input_tokens=7, output_tokens=8,
                   cache_read_tokens=9, cache_creation_tokens=1),
        _proxy_row(request_id="session:w3", created_at=PROXY_TS + 5,
                   status_code=500),                  # 过滤口径: 不产出差集行
    ]
    proxy_db = tmp_db / "cc-switch.db"
    _install_proxy_db(proxy_db, proxy_rows)
    monkeypatch.setattr(claudecode_api, "CC_SWITCH_DB_PATH", proxy_db)
    seen_since = []
    real_read = claudecode_api.read_proxy_rows

    def spy_read(since):
        seen_since.append(since)
        return real_read(since)

    monkeypatch.setattr(claudecode_api, "read_proxy_rows", spy_read)

    assert server._sync_cc_proxy_gap(PRICING) == (2, None)   # w3 失败请求不计
    assert db.get_cc_proxy_watermark() == PROXY_TS + 5
    assert seen_since == [0]
    assert _proxy_file_count() == 2

    assert server._sync_cc_proxy_gap(PRICING) == (0, None)   # 同批不再产出
    assert seen_since == [0, PROXY_TS + 5]                   # 第二次以水位为 since
    assert _proxy_file_count() == 2                          # 不重复落库
