"""ZCode 服务层测试: 导入编排/异常吞并/空采集短路径/summary 形状/防抖/quota 缓存.

全部走临时目录 + monkeypatch, 不读本机真实 ZCode 文件, 不起真实网络请求.
fixture 模式参照 test_db_multiuser.py 的 tmp_db.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app import db, server, zcode_api

# 手工定价表 (内容不重要, 仅断言"预载一次并原样传给 import")
PRICING = [{"modelId": "glm-5.3"}]


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时 GoGauge 库: 重定向 data_dir 并重置模块级连接."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


@pytest.fixture()
def zcode_state(monkeypatch):
    """复位 server 的 zcode 模块级状态, 隔离用例间污染."""
    monkeypatch.setattr(server, "_zcode_sync_error", "")
    monkeypatch.setattr(server, "_zcode_quota_cache", {"at": 0.0, "data": None})
    monkeypatch.setattr(server, "_zcode_quota_refreshing", False)
    monkeypatch.setattr(server, "_zcode_last_import_trigger", 0.0)


def _zcode_row(row_id, started_ms):
    """构造一行 model_usage 记录 (14 键, 与 zcode_api._USAGE_COLUMNS 一致)."""
    return {
        "id": row_id, "started_at": started_ms, "session_id": "sess-1",
        "provider_id": "p1", "model_id": "glm-5.3", "status": "success",
        "input_tokens": 10, "output_tokens": 20, "reasoning_tokens": 0,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "computed_total_tokens": 30, "duration_ms": 500,
        "time_to_first_token_ms": 100,
    }


# ---------------------------------------------------------------------------
# 1. _sync_zcode_local 编排: 水位重叠窗口 / 预载定价 / 水位推进 / 返回新增数
# ---------------------------------------------------------------------------


def test_sync_zcode_local_orchestration(tmp_db, zcode_state, monkeypatch):
    wm_value = 1_000_000_000_000
    monkeypatch.setattr(db, "get_zcode_watermark", lambda: wm_value)
    saved = []
    monkeypatch.setattr(db, "save_zcode_watermark", saved.append)
    rows = [_zcode_row("u1", 1_000_000_500_000), _zcode_row("u2", 1_000_000_999_000)]
    seen = {}

    def fake_collect(since_ms):
        seen["since_ms"] = since_ms
        return [dict(r) for r in rows]

    monkeypatch.setattr(zcode_api, "collect_local_usage", fake_collect)
    monkeypatch.setattr(zcode_api, "read_provider_names", lambda: {"p1": "Plan A"})
    monkeypatch.setattr(server, "_load_model_pricing", lambda: PRICING)
    calls = {}

    def fake_import(rows_arg, names, pricing):
        calls["rows"] = rows_arg
        calls["names"] = names
        calls["pricing"] = pricing
        return 2

    monkeypatch.setattr(db, "import_zcode_usage", fake_import)

    assert server._sync_zcode_local() == 2
    # since_ms = 水位 - 10 分钟重叠窗口
    assert seen["since_ms"] == wm_value - 10 * 60 * 1000
    # import 收到渠道名快照与预载定价表
    assert calls["names"] == {"p1": "Plan A"}
    assert calls["pricing"] is PRICING
    assert len(calls["rows"]) == 2
    # 水位推进 = 本批最大 started_at
    assert saved == [1_000_000_999_000]
    # 成功 → 错误文案清空
    assert server._zcode_sync_error == ""


# ---------------------------------------------------------------------------
# 2. 异常吞并: 不外抛 / 记录文案 / 不推进水位 / 下次成功后清空
# ---------------------------------------------------------------------------


def test_sync_zcode_local_swallows_exception(tmp_db, zcode_state, monkeypatch):
    monkeypatch.setattr(db, "get_zcode_watermark", lambda: 0)
    saved = []
    monkeypatch.setattr(db, "save_zcode_watermark", saved.append)

    def boom(since_ms):
        raise RuntimeError("zcode db locked")

    monkeypatch.setattr(zcode_api, "collect_local_usage", boom)
    # 不抛, 返回 0
    assert server._sync_zcode_local() == 0
    assert "zcode db locked" in server._zcode_sync_error
    assert saved == []  # 异常: 水位不推进

    # 下次成功 (有数据导入) 后错误清空
    monkeypatch.setattr(zcode_api, "collect_local_usage",
                        lambda since_ms: [_zcode_row("u1", 5000)])
    monkeypatch.setattr(zcode_api, "read_provider_names", lambda: {})
    monkeypatch.setattr(server, "_load_model_pricing", lambda: PRICING)
    monkeypatch.setattr(db, "import_zcode_usage", lambda rows, names, pricing: 1)
    assert server._sync_zcode_local() == 1
    assert server._zcode_sync_error == ""


# ---------------------------------------------------------------------------
# 3. 空采集短路径: 不调 read_provider_names/import、不清错误、不推进水位
# ---------------------------------------------------------------------------


def test_sync_zcode_local_empty_short_circuit(tmp_db, zcode_state, monkeypatch):
    monkeypatch.setattr(server, "_zcode_sync_error", "上次错误")
    monkeypatch.setattr(db, "get_zcode_watermark", lambda: 500_000)
    seen = {}

    def fake_collect(since_ms):
        seen["since_ms"] = since_ms
        return []

    monkeypatch.setattr(zcode_api, "collect_local_usage", fake_collect)
    names_called, import_called, saved = [], [], []
    monkeypatch.setattr(zcode_api, "read_provider_names",
                        lambda: names_called.append(1))
    monkeypatch.setattr(db, "import_zcode_usage",
                        lambda *a, **k: import_called.append(a) or 0)
    monkeypatch.setattr(db, "save_zcode_watermark", saved.append)

    assert server._sync_zcode_local() == 0
    assert seen["since_ms"] == 500_000 - 10 * 60 * 1000
    assert not names_called
    assert not import_called
    assert saved == []
    # 空采集不清错误、不推进水位
    assert server._zcode_sync_error == "上次错误"


# ---------------------------------------------------------------------------
# 4. _zcode_summary_payload: 形状 / db_found 两分支 / last_import_at / range 映射
# ---------------------------------------------------------------------------


def _patch_aggregates(monkeypatch):
    """把四个 db 聚合换成记录 period 入参的桩."""
    monkeypatch.setattr(db, "zcode_totals",
                        lambda period="30d": {"request_count": 3, "period": period})
    monkeypatch.setattr(db, "zcode_daily",
                        lambda days=7: [{"date": "2026-09-01", "days": days}])
    monkeypatch.setattr(db, "zcode_provider_stats",
                        lambda period="30d": [{"provider_id": "p1", "period": period}])
    monkeypatch.setattr(db, "zcode_model_stats",
                        lambda period="30d": [{"model_id": "m1", "period": period}])


def _existing_zcode_db(tmp_db, monkeypatch):
    """ZCODE_DB 指向一个真实存在的文件 (db_found=True 分支)."""
    path = tmp_db / "zcode.sqlite"
    path.touch()
    monkeypatch.setattr(zcode_api, "ZCODE_DB", path)
    return path


def test_summary_payload_shape(tmp_db, zcode_state, monkeypatch):
    _existing_zcode_db(tmp_db, monkeypatch)
    _patch_aggregates(monkeypatch)
    # 插入一行 zcode_usage 使 MAX(synced_at) 有值
    conn = db.get_db()
    conn.execute(
        "INSERT INTO zcode_usage (id, started_at, synced_at)"
        " VALUES ('t1', '2026-01-01T00:00:00Z', '2026-01-02T03:04:05Z')"
    )
    conn.commit()

    payload = server._zcode_summary_payload("7d")
    assert set(payload.keys()) == {
        "db_found", "last_import_at", "error", "range",
        "totals", "daily7", "providers", "models",
    }
    assert payload["db_found"] is True
    assert payload["last_import_at"] == "2026-01-02T03:04:05Z"
    assert payload["error"] == ""
    assert payload["range"] == "7d"  # range 原文
    assert payload["totals"] == {"request_count": 3, "period": "7d"}
    assert payload["daily7"] == [{"date": "2026-09-01", "days": 7}]
    assert payload["providers"] == [{"provider_id": "p1", "period": "7d"}]
    assert payload["models"] == [{"model_id": "m1", "period": "7d"}]


def test_summary_payload_range_mapping(tmp_db, zcode_state, monkeypatch):
    _existing_zcode_db(tmp_db, monkeypatch)
    _patch_aggregates(monkeypatch)
    # today / 7d / all 照原文传 period, 无效值 → 30d 口径
    assert server._zcode_summary_payload("today")["totals"]["period"] == "today"
    assert server._zcode_summary_payload("7d")["totals"]["period"] == "7d"
    assert server._zcode_summary_payload("all")["totals"]["period"] == "all"
    assert server._zcode_summary_payload("30d")["totals"]["period"] == "30d"
    assert server._zcode_summary_payload("banana")["totals"]["period"] == "30d"
    assert server._zcode_summary_payload("banana")["range"] == "banana"


def test_summary_payload_db_missing(tmp_db, zcode_state, monkeypatch):
    monkeypatch.setattr(zcode_api, "ZCODE_DB", tmp_db / "missing.sqlite")
    monkeypatch.setattr(server, "_zcode_sync_error", "历史错误文案")
    payload = server._zcode_summary_payload("30d")
    assert payload["db_found"] is False
    assert payload["last_import_at"] is None
    assert payload["error"] == "历史错误文案"
    assert payload["range"] == "30d"
    # 空结构
    assert payload["totals"] == {}
    assert payload["daily7"] == []
    assert payload["providers"] == []
    assert payload["models"] == []


# ---------------------------------------------------------------------------
# 5. 防抖: 60s 内多次 payload 请求只触发一次导入, 超 60s 再触发
# ---------------------------------------------------------------------------


def test_summary_import_debounce(tmp_db, zcode_state, monkeypatch):
    triggers = []
    monkeypatch.setattr(server, "zcode_import_async", lambda: triggers.append(1))
    clock = {"now": 1000.0}
    # 只替换 server 模块内的 time 引用, 不动 stdlib time 模块
    monkeypatch.setattr(server, "time", SimpleNamespace(time=lambda: clock["now"]))

    server._maybe_trigger_zcode_import()  # 初值 0.0, 距今远超 60s → 触发
    assert triggers == [1]
    clock["now"] = 1030.0  # 30s 后: 不触发
    server._maybe_trigger_zcode_import()
    assert triggers == [1]
    clock["now"] = 1060.0  # 恰好 60s (边界 <=): 不触发
    server._maybe_trigger_zcode_import()
    assert triggers == [1]
    clock["now"] = 1061.0  # 超过 60s: 再触发
    server._maybe_trigger_zcode_import()
    assert triggers == [1, 1]


# ---------------------------------------------------------------------------
# 6. quota 缓存: 首次同步获取 / TTL 内直返 / 过期返回旧值+后台刷新
# ---------------------------------------------------------------------------


def test_zcode_quota_cache_states(tmp_db, zcode_state, monkeypatch):
    calls = []
    results = [
        {"success": True, "level": "pro", "windows": []},
        {"success": True, "level": "pro2", "windows": []},
    ]

    def fake_fetch():
        calls.append(1)
        return results[len(calls) - 1]

    monkeypatch.setattr(zcode_api, "fetch_quota", fake_fetch)

    # 首次: 同步获取一次并缓存
    first = server._zcode_quota_payload()
    assert first == results[0]
    assert len(calls) == 1
    # TTL 内: 直返缓存, 不再调用
    assert server._zcode_quota_payload() is first
    assert len(calls) == 1

    # 过期: 注入"只记录不起线程"的 Thread (消除真实线程竞态), 确定性验证
    # 请求线程返回现有缓存旧值, 且后台刷新任务恰好排了一次
    launched = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            launched.append(target)

        def start(self) -> None:
            pass  # 不真正执行

    monkeypatch.setattr(server.threading, "Thread", _FakeThread)
    server._zcode_quota_cache["at"] = time.time() - (server.QUOTA_CACHE_TTL + 1)
    stale = server._zcode_quota_payload()
    assert stale is first  # 过期: 返回现有缓存值
    assert len(calls) == 1  # 请求线程未再调用
    assert len(launched) == 1 and callable(launched[0])

    # 注入同步执行刷新 worker (fetch_quota 合同不抛异常, 错误 dict 即占位结果)
    launched[0]()
    assert len(calls) == 2
    assert server._zcode_quota_cache["data"] == results[1]
    assert server._zcode_quota_refreshing is False  # 防重入标志已复位
    # 刷新完成后 TTL 内: 直返新值
    assert server._zcode_quota_payload() == results[1]
    assert len(calls) == 2


def test_zcode_quota_refresh_no_reentry(tmp_db, zcode_state, monkeypatch):
    """刷新进行中 (防重入标志为 True) 再次过期: 不重复排刷新任务."""
    monkeypatch.setattr(zcode_api, "fetch_quota",
                        lambda: {"success": True, "level": "x", "windows": []})
    launched = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            launched.append(target)

        def start(self) -> None:
            pass

    monkeypatch.setattr(server.threading, "Thread", _FakeThread)
    server._zcode_quota_cache.update(at=1.0, data={"success": True})
    server._zcode_quota_payload()  # 过期 → 排一次刷新
    server._zcode_quota_payload()  # 刷新未完成再次过期 → 防重入, 不再排
    assert len(launched) == 1
