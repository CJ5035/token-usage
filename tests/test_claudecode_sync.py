"""Claude Code 本地用量落库层测试: 建表迁移/导入幂等/总量大者胜/进度/启用时刻/聚合.

全部走临时目录 + monkeypatch, 不读本机真实 ~/.claude 文件.
fixture 模式照 test_zcode_sync.py 的 tmp_db.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import db

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
