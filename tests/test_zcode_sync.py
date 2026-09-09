"""ZCode 本地用量落库层测试: 导入/幂等/水位/秒速口径/四层聚合.

全部走临时目录 + monkeypatch, 不读本机真实 ZCode 文件.
fixture 模式参照 test_db_multiuser.py 的 tmp_db.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app import db, zcode_api

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


# 本机 ZCode model_usage 表的 14 列契约 (与 zcode_api._USAGE_COLUMNS 一致)
_ZCODE_COLS = (
    "id", "started_at", "session_id", "provider_id", "model_id", "status",
    "input_tokens", "output_tokens", "reasoning_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens",
    "computed_total_tokens", "duration_ms", "time_to_first_token_ms",
)
_TEXT_COLS = {"id", "session_id", "provider_id", "model_id", "status"}


def _zcode_row(row_id, started_ms=1000, **overrides):
    """构造一行 model_usage 记录.

    真实子集语义: input_tokens 为全量输入 (cache_read ⊆ input),
    computed_total = input + cache_creation + output (不含 reasoning 单列).
    默认值对应新口径 cost_raw=38250, 旧口径(修复前导入)=53250.
    """
    values = {
        "id": row_id, "started_at": started_ms, "session_id": "sess-1",
        "provider_id": "p1", "model_id": "glm-5.3", "status": "success",
        "input_tokens": 200, "output_tokens": 100, "reasoning_tokens": 10,
        "cache_creation_input_tokens": 5, "cache_read_input_tokens": 150,
        "computed_total_tokens": 305, "duration_ms": 1000,
        "time_to_first_token_ms": 200,
    }
    values.update(overrides)
    return values


def _create_zcode_db(path, rows=()):
    con = sqlite3.connect(str(path))
    cols_sql = ", ".join(
        f'"{c}" {"TEXT" if c in _TEXT_COLS else "INTEGER"}' for c in _ZCODE_COLS
    )
    con.execute(f"CREATE TABLE model_usage ({cols_sql})")
    if rows:
        _insert_zcode_rows(con, rows)
    con.commit()
    con.close()


def _insert_zcode_rows(con, rows):
    placeholders = ", ".join("?" for _ in _ZCODE_COLS)
    con.executemany(
        f"INSERT INTO model_usage VALUES ({placeholders})",
        [tuple(r[c] for c in _ZCODE_COLS) for r in rows],
    )


@pytest.fixture()
def zcode_source(tmp_path, monkeypatch):
    """临时 ZCode 本地库 (空 model_usage 表), 已 monkeypatch ZCODE_DB."""
    path = tmp_path / "zcode.sqlite"
    _create_zcode_db(path)
    monkeypatch.setattr(zcode_api, "ZCODE_DB", path)
    return path


def _append_zcode_rows(path, rows):
    con = sqlite3.connect(str(path))
    _insert_zcode_rows(con, rows)
    con.commit()
    con.close()


def _sync(provider_names=None) -> int:
    """collect → import 一步到位 (采集全量 + 按默认定价导入)."""
    if provider_names is None:
        provider_names = {"p1": "Plan A", "p2": "Plan B"}
    return db.import_zcode_usage(
        zcode_api.collect_local_usage(0), provider_names, PRICING
    )


# ---------------------------------------------------------------------------
# 1. 首次全量导入
# ---------------------------------------------------------------------------


def test_first_full_import(tmp_db, zcode_source):
    base_ms = int(datetime(2024, 9, 2, 18, 0, 0, tzinfo=timezone.utc).timestamp() * 1000)
    _append_zcode_rows(zcode_source, [
        _zcode_row("u1", base_ms),
        _zcode_row("u2", base_ms + 123, provider_id="p2"),
        # token 类 None → 0, duration/ttft None 保持 None
        _zcode_row("u3", base_ms + 456, reasoning_tokens=None,
                   duration_ms=None, time_to_first_token_ms=None,
                   computed_total_tokens=305),
    ])
    rows = zcode_api.collect_local_usage(0)
    assert len(rows) == 3
    assert _sync() == 3

    r = db.get_db().execute(
        "SELECT * FROM zcode_usage WHERE id = 'u1'"
    ).fetchone()
    # started_at: epoch ms → UTC ISO, 含 Z 后缀且与原始 ms 对应 (硬编码期望)
    assert r["started_at"] == "2024-09-02T18:00:00Z"
    assert r["provider_id"] == "p1"
    assert r["provider_name"] == "Plan A"          # config.json 快照
    assert r["model_id"] == "glm-5.3"
    assert r["input_tokens"] == 200
    assert r["output_tokens"] == 100
    assert r["reasoning_tokens"] == 10
    assert r["cache_write_tokens"] == 5            # ← cache_creation_input_tokens
    assert r["cache_read_tokens"] == 150
    assert r["total_tokens"] == 305                # ← computed_total_tokens (input+cache_creation+output)
    assert r["duration_ms"] == 1000
    assert r["ttft_ms"] == 200                     # ← time_to_first_token_ms
    # 手算: 未命中输入 200-150=50 → (50*1 + 100*3 + 150*0.2 + 5*0.5)/1e6*1e8 = 38250
    # (缓存命中 150 只按缓存读价 0.2 计一次, 不再随全额 input 重复计费)
    assert r["cost_raw"] == 38250
    assert r["synced_at"].endswith("Z")

    r2 = db.get_db().execute(
        "SELECT started_at, provider_name FROM zcode_usage WHERE id = 'u2'"
    ).fetchone()
    assert r2["started_at"] == "2024-09-02T18:00:00.123000Z"
    assert r2["provider_name"] == "Plan B"

    r3 = db.get_db().execute(
        "SELECT reasoning_tokens, duration_ms, ttft_ms, total_tokens"
        " FROM zcode_usage WHERE id = 'u3'"
    ).fetchone()
    assert r3["reasoning_tokens"] == 0             # None → 0
    assert r3["duration_ms"] is None               # None 保持 None
    assert r3["ttft_ms"] is None
    assert r3["total_tokens"] == 305


# ---------------------------------------------------------------------------
# 2. 二次增量 / 3. 幂等
# ---------------------------------------------------------------------------


def test_incremental_import(tmp_db, zcode_source):
    _append_zcode_rows(zcode_source, [
        _zcode_row("u1", 1000), _zcode_row("u2", 2000),
    ])
    assert _sync() == 2
    # 临时库追加 1 行后再同步: 仅新增 1 行, 旧行不重复
    _append_zcode_rows(zcode_source, [_zcode_row("u3", 3000)])
    assert _sync() == 1
    count = db.get_db().execute(
        "SELECT COUNT(*) AS c FROM zcode_usage"
    ).fetchone()["c"]
    assert count == 3


def test_idempotent_reimport(tmp_db, zcode_source):
    _append_zcode_rows(zcode_source, [_zcode_row("u1", 1000)])
    assert _sync() == 1
    assert _sync() == 0                            # 同批重复导入 → 新增 0
    count = db.get_db().execute(
        "SELECT COUNT(*) AS c FROM zcode_usage"
    ).fetchone()["c"]
    assert count == 1


# ---------------------------------------------------------------------------
# 4. 水位 (settings payload 白名单外键)
# ---------------------------------------------------------------------------


def test_watermark_roundtrip(tmp_db):
    assert db.get_zcode_watermark() == 0           # 缺失 → 0
    db.save_zcode_watermark(1725300000123)
    assert db.get_zcode_watermark() == 1725300000123
    # 白名单外键不污染设置 API
    assert "zcode_last_started_at" not in db.get_settings()
    # 保存设置不丢水位 (save_settings 保留非白名单键)
    db.save_settings({"sync_interval_sec": 60})
    assert db.get_zcode_watermark() == 1725300000123


# ---------------------------------------------------------------------------
# 5. 秒速口径 (手算: avg_tps=185.0, max_tps=200.0, avg_ttft=312.5)
#    a: gen=1000-200=800     → rate=100*1000/800=125     ttft 200 有效
#    b: ttft=950>=90%dur     → gen=950                   → rate=190*1000/950=200
#    c: output=5<10          → rate 不参与               ttft 100 有效
#    d: rate=100*1000/100=1000>500 → 不参与              ttft 0 有效
#    e: ttft=None            → gen=500 → rate=200        ttft 不参与
#    f: ttft=600>dur=500     → gen=500 → rate=200        ttft 不参与
#    g: ttft=-5<0            → gen=500 → rate=200        ttft 不参与
# ---------------------------------------------------------------------------


def _speed_rows():
    return [
        _zcode_row("a", input_tokens=10, output_tokens=100, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=110, duration_ms=1000,
                   time_to_first_token_ms=200),
        _zcode_row("b", input_tokens=10, output_tokens=190, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=200, duration_ms=1000,
                   time_to_first_token_ms=950),
        _zcode_row("c", input_tokens=10, output_tokens=5, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=15, duration_ms=1000,
                   time_to_first_token_ms=100),
        _zcode_row("d", input_tokens=10, output_tokens=100, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=110, duration_ms=100,
                   time_to_first_token_ms=0),
        _zcode_row("e", input_tokens=10, output_tokens=100, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=110, duration_ms=500,
                   time_to_first_token_ms=None),
        _zcode_row("f", input_tokens=10, output_tokens=100, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=110, duration_ms=500,
                   time_to_first_token_ms=600),
        _zcode_row("g", input_tokens=10, output_tokens=100, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=110, duration_ms=500,
                   time_to_first_token_ms=-5),
    ]


def test_speed_metrics_hand_computed(tmp_db, zcode_source):
    _append_zcode_rows(zcode_source, _speed_rows())
    assert _sync() == 7
    t = db.zcode_totals("all")
    assert t["avg_tps"] == 185.0                   # (125+200+200+200+200)/5
    assert t["max_tps"] == 200.0
    assert t["avg_ttft_ms"] == 312.5               # (200+950+0+100)/4


def test_speed_no_trusted_samples_returns_none(tmp_db, zcode_source):
    # 唯一一行 output<10 且 ttft 缺失: 无可信速率样本、无有效 TTFT
    _append_zcode_rows(zcode_source, [
        _zcode_row("x", input_tokens=10, output_tokens=5, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=15, duration_ms=None,
                   time_to_first_token_ms=None),
    ])
    assert _sync() == 1
    t = db.zcode_totals("all")
    assert t["avg_tps"] is None
    assert t["max_tps"] is None
    assert t["avg_ttft_ms"] is None


# ---------------------------------------------------------------------------
# 6. 跨本地日归组
# ---------------------------------------------------------------------------


def test_daily_groups_by_local_day(tmp_db, zcode_source):
    local_midnight = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    midnight_ms = round(local_midnight.timestamp() * 1000)
    # 本地今天 00:30 与本地昨天 23:30 各一行 → 归入两个不同的本地日
    _append_zcode_rows(zcode_source, [
        _zcode_row("today_row", midnight_ms + 30 * 60 * 1000),
        _zcode_row("yest_row", midnight_ms - 30 * 60 * 1000),
    ])
    assert _sync() == 2
    daily = db.zcode_daily(days=7)
    assert [d["date"] for d in daily] == [
        (local_midnight - timedelta(days=1)).strftime("%Y-%m-%d"),
        local_midnight.strftime("%Y-%m-%d"),
    ]
    assert [d["request_count"] for d in daily] == [1, 1]


# ---------------------------------------------------------------------------
# 7. 四层聚合数值 (手算)
# ---------------------------------------------------------------------------


def test_four_layer_aggregates(tmp_db, zcode_source, monkeypatch):
    # 固定 _now_iso, 使两次导入的 synced_at 有确定先后 → provider_name 取新不取旧
    clock = ["2026-01-01T00:00:00Z"]
    monkeypatch.setattr(db, "_now_iso", lambda: clock[0])
    # 第一次导入: p1 名为 "Plan A"
    _append_zcode_rows(zcode_source, [
        # cost_raw = (50*1 + 200*3 + 50*0.2 + 10*0.5)*100 = 66500  [未命中输入 100-50=50]
        _zcode_row("r1", input_tokens=100, output_tokens=200, reasoning_tokens=30,
                   cache_creation_input_tokens=10, cache_read_input_tokens=50,
                   computed_total_tokens=310, duration_ms=1000,
                   time_to_first_token_ms=200),
        # model m2 未收录定价表 → cost_raw = 0
        _zcode_row("r2", provider_id="p2", model_id="m2", input_tokens=20,
                   output_tokens=40, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=60, duration_ms=800,
                   time_to_first_token_ms=100),
    ])
    assert _sync() == 2
    # 第二次导入: p1 改名 "Plan A New" (改名不回写旧行, 聚合取最新快照)
    clock[0] = "2026-01-02T00:00:00Z"
    _append_zcode_rows(zcode_source, [
        # cost_raw = (10*1 + 20*3)*100 = 7000; rate = 20*1000/400 = 50
        _zcode_row("r3", input_tokens=10, output_tokens=20, reasoning_tokens=0,
                   cache_creation_input_tokens=0, cache_read_input_tokens=0,
                   computed_total_tokens=30, duration_ms=500,
                   time_to_first_token_ms=100),
    ])
    assert _sync({"p1": "Plan A New", "p2": "Plan B"}) == 1

    # --- totals ---
    t = db.zcode_totals("all")
    assert t["request_count"] == 3
    assert t["total_input_tokens"] == 140          # (100+10) + (20+0) + (10+0)  [input+cache_write]
    assert t["uncached_input_tokens"] == 80        # (100-50) + 20 + 10  [input-cache_read]
    assert t["total_reasoning_tokens"] == 30
    assert t["cache_hit_tokens"] == 50
    assert t["cache_write_tokens"] == 10
    assert t["total_output_tokens"] == 260         # 200 + 40 + 20
    assert t["total_tokens"] == 400                # 310 + 60 + 30
    assert t["total_cost_usd"] == 0.000735         # (66500+0+7000)/1e8

    # --- provider stats ---
    providers = db.zcode_provider_stats("all")
    assert [p["provider_id"] for p in providers] == ["p1", "p2"]  # 按 输入+输出 降序
    p1, p2 = providers
    assert p1["provider_name"] == "Plan A New"     # 取最新 synced_at 快照
    assert p1["request_count"] == 2
    assert p1["total_input_tokens"] == 120         # (100+10) + (10+0)
    assert p1["uncached_input_tokens"] == 60       # (100-50) + 10
    assert p1["total_reasoning_tokens"] == 30
    assert p1["cache_hit_tokens"] == 50
    assert p1["cache_write_tokens"] == 10
    assert p1["total_output_tokens"] == 220
    assert p1["total_cost_usd"] == 0.000735        # (66500+7000)/1e8
    # 行1 rate=200*1000/800=250, 行3 rate=20*1000/400=50 → avg=150, max=250
    assert p1["avg_tps"] == 150.0
    assert p1["max_tps"] == 250.0
    assert p1["avg_ttft_ms"] == 150.0              # (200+100)/2
    assert p2["provider_name"] == "Plan B"
    assert p2["request_count"] == 1
    assert p2["total_cost_usd"] == 0.0             # 未收录模型 cost 0

    # --- model stats ---
    models = db.zcode_model_stats("all")
    assert [(m["provider_id"], m["model_id"]) for m in models] == [
        ("p1", "glm-5.3"), ("p2", "m2"),
    ]
    m1, m2 = models
    assert m1["provider_name"] == "Plan A New"
    assert m1["hit_rate"] == 41.67                 # 50/(50+60+10)*100 = cache/(input+cache_write)
    assert m1["total_input_tokens"] == 120
    assert m2["hit_rate"] == 0.0                   # 0/(0+20)*100


# ---------------------------------------------------------------------------
# 8. 空表 / 无数据
# ---------------------------------------------------------------------------


def test_empty_aggregates(tmp_db):
    t = db.zcode_totals("30d")
    assert t["request_count"] == 0
    assert t["total_input_tokens"] == 0
    assert t["total_output_tokens"] == 0
    assert t["total_tokens"] == 0
    assert t["total_cost_usd"] == 0.0
    assert t["avg_tps"] is None
    assert t["max_tps"] is None
    assert t["avg_ttft_ms"] is None
    assert db.zcode_daily(7) == []
    assert db.zcode_provider_stats("30d") == []
    assert db.zcode_model_stats("30d") == []


# ---------------------------------------------------------------------------
# 9. 历史 cost_raw 一次性回填 (缓存子集口径修复)
# ---------------------------------------------------------------------------


def test_recompute_cost_raw_backfill(tmp_db, zcode_source):
    _append_zcode_rows(zcode_source, [_zcode_row("u1", 1000)])
    assert _sync() == 1
    # 模拟修复前导入的历史脏数据: 旧公式按全额 input 计费
    # (200*1 + 100*3 + 150*0.2 + 5*0.5)*100 = 53250
    db.get_db().execute("UPDATE zcode_usage SET cost_raw = 53250 WHERE id = 'u1'")
    db.get_db().commit()

    assert db.maybe_recompute_zcode_cost_raw(PRICING) == 1
    r = db.get_db().execute(
        "SELECT cost_raw FROM zcode_usage WHERE id = 'u1'"
    ).fetchone()["cost_raw"]
    assert r == 38250                     # 未命中输入 (200-150) 按输入价, 缓存只按缓存价

    # 幂等: 标记位已置, 二次调用 0 行
    assert db.maybe_recompute_zcode_cost_raw(PRICING) == 0
    assert db._raw_payload(db.get_db()).get(db._ZCODE_COST_RECALC_KEY) == 1


def test_recompute_cost_raw_empty_table(tmp_db):
    # 空表: 置标记位并返回 0 (保证新版启动后即使无新数据也完成口径切换)
    assert db.maybe_recompute_zcode_cost_raw(PRICING) == 0
    assert db._raw_payload(db.get_db()).get(db._ZCODE_COST_RECALC_KEY) == 1


def test_recompute_cost_raw_skips_without_pricing(tmp_db, zcode_source):
    # 定价表缺失/为空: 不回填、不置标记 (否则 estimate_cost_raw 全返回 0,
    # 会把全部历史 cost_raw 清零并误标"已完成", 不可逆)
    _append_zcode_rows(zcode_source, [_zcode_row("u1", 1000)])
    assert _sync() == 1
    db.get_db().execute("UPDATE zcode_usage SET cost_raw = 53250 WHERE id = 'u1'")
    db.get_db().commit()

    assert db.maybe_recompute_zcode_cost_raw([]) == 0
    r = db.get_db().execute(
        "SELECT cost_raw FROM zcode_usage WHERE id = 'u1'"
    ).fetchone()["cost_raw"]
    assert r == 53250                                     # 原值未动
    assert db._raw_payload(db.get_db()).get(db._ZCODE_COST_RECALC_KEY) is None
