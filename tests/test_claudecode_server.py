"""Claude Code 服务层测试: 导入编排/enabled_at 首写/异常吞并/summary 形状/防抖/与 zcode 互不干扰.

全部走临时目录 + monkeypatch, 不读本机真实 ~/.claude 文件, 不起真实网络请求.
fixture 模式参照 test_zcode_sync.py 的 tmp_db 与 test_zcode_server.py 的状态复位.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app import claudecode_api, db, server, zcode_api

# 手工定价表 (内容不重要, 仅断言"预载一次并原样传给 import")
PRICING = [{"modelId": "claude-sonnet-4-5"}]


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时 GoGauge 库: 重定向 data_dir 并重置模块级连接."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


@pytest.fixture()
def claude_state(monkeypatch):
    """复位 server 的 claude 模块级状态, 隔离用例间污染."""
    monkeypatch.setattr(server, "_cc_sync_error", "")
    monkeypatch.setattr(server, "_cc_last_import_trigger", 0.0)


@pytest.fixture()
def zcode_state(monkeypatch):
    """复位 server 的 zcode 模块级状态 (互不干扰用例需要)."""
    monkeypatch.setattr(server, "_zcode_sync_error", "")
    monkeypatch.setattr(server, "_zcode_last_import_trigger", 0.0)


def _existing_projects_dir(tmp_db, monkeypatch):
    """CLAUDE_PROJECTS 指向一个真实存在的目录 (db_found=True 分支)."""
    path = tmp_db / "projects"
    path.mkdir()
    monkeypatch.setattr(claudecode_api, "CLAUDE_PROJECTS", path)
    return path


def _patch_aggregates(monkeypatch):
    """把四个 db 聚合换成记录 period/days 入参的桩."""
    monkeypatch.setattr(db, "claudecode_totals",
                        lambda period="30d": {"request_count": 3, "period": period})
    monkeypatch.setattr(db, "claudecode_daily",
                        lambda days=7: [{"date": "2026-09-01", "days": days}])
    monkeypatch.setattr(db, "claudecode_channel_stats",
                        lambda period="30d": [{"channel": "官方", "period": period}])
    monkeypatch.setattr(db, "claudecode_model_stats",
                        lambda period="30d": [{"model": "claude-sonnet-4-5", "period": period}])


# ---------------------------------------------------------------------------
# 1. _sync_claude_local 编排: enabled_at 首写 / 进度快照 / 逐批导入+推进
# ---------------------------------------------------------------------------


def test_sync_claude_local_first_run_writes_enabled_at(tmp_db, claude_state, monkeypatch):
    """enabled_at 为 0 → 取当前 epoch ms 写入 (= 启用时刻) 并传给采集; 二次运行不再写."""
    assert db.get_claudecode_enabled_at() == 0  # 尚未启用
    seen = {}

    def fake_import(enabled_at, progress, force=False):
        seen["enabled_at"] = enabled_at
        return []

    monkeypatch.setattr(claudecode_api, "import_incremental", fake_import)
    before = int(time.time() * 1000)
    assert server._sync_claude_local() == 0
    after = int(time.time() * 1000)

    saved_at = db.get_claudecode_enabled_at()
    assert before <= saved_at <= after  # 写入的是当前时刻
    assert seen["enabled_at"] == saved_at  # 采集收到同一启用时刻

    # 二次运行: 已有启用时刻, 不改写 (fake 闭包内 saved_at 已固化, 直接断言不变)
    assert server._sync_claude_local() == 0
    assert db.get_claudecode_enabled_at() == saved_at


def test_sync_claude_local_orchestration(tmp_db, claude_state, monkeypatch):
    """进度快照传入采集; 逐批"导入+推进"两步提交; 定价表预载一次; 错误清空."""
    monkeypatch.setattr(db, "get_claudecode_enabled_at", lambda: 1_000_000_000_000)
    saved_enabled = []
    monkeypatch.setattr(db, "save_claudecode_enabled_at",
                        lambda ms: saved_enabled.append(ms))  # 已启用: 不应再写
    progress_snapshot = {"/p/a.jsonl": (0, 0)}
    monkeypatch.setattr(db, "get_claude_file_progress_all",
                        lambda: progress_snapshot)
    seen = {}

    def fake_import(enabled_at, progress, force=False):
        seen["enabled_at"] = enabled_at
        seen["progress"] = progress
        return [
            {"path": "/p/a.jsonl", "rows": [{"dedupe_key": "k1"}],
             "new_offset": 120, "size": 120},
            {"path": "/p/b.jsonl", "rows": [{"dedupe_key": "k2"}, {"dedupe_key": "k3"}],
             "new_offset": 80, "size": 80},
        ]

    monkeypatch.setattr(claudecode_api, "import_incremental", fake_import)
    pricing_calls = []
    monkeypatch.setattr(server, "_load_model_pricing",
                        lambda: pricing_calls.append(1) or PRICING)
    imports, saved_progress = [], []

    def fake_import_rows(rows, pricing):
        imports.append((rows, pricing))
        return len(rows)

    monkeypatch.setattr(db, "import_claudecode_usage", fake_import_rows)
    monkeypatch.setattr(db, "save_claude_file_progress",
                        lambda path, offset, size: saved_progress.append((path, offset, size)))

    assert server._sync_claude_local() == 3
    assert seen["enabled_at"] == 1_000_000_000_000
    assert seen["progress"] is progress_snapshot  # 快照原样传入
    assert saved_enabled == []  # 已启用: 不重写 enabled_at
    # 每批一行导入 + 一次进度推进 (两步提交)
    assert imports == [
        ([{"dedupe_key": "k1"}], PRICING),
        ([{"dedupe_key": "k2"}, {"dedupe_key": "k3"}], PRICING),
    ]
    assert saved_progress == [("/p/a.jsonl", 120, 120), ("/p/b.jsonl", 80, 80)]
    assert pricing_calls == [1]  # 预载一次, 两批共用
    assert server._cc_sync_error == ""  # 成功 → 错误文案清空


def test_sync_claude_local_empty_short_circuit(tmp_db, claude_state, monkeypatch):
    """空批次: 不调 import/推进进度、不清错误."""
    monkeypatch.setattr(server, "_cc_sync_error", "上次错误")
    monkeypatch.setattr(db, "get_claudecode_enabled_at", lambda: 1_000)
    monkeypatch.setattr(db, "get_claude_file_progress_all", lambda: {})
    monkeypatch.setattr(claudecode_api, "import_incremental",
                        lambda enabled_at, progress, force=False: [])
    import_called, saved_progress = [], []
    monkeypatch.setattr(db, "import_claudecode_usage",
                        lambda *a, **k: import_called.append(a) or 0)
    monkeypatch.setattr(db, "save_claude_file_progress",
                        lambda *a: saved_progress.append(a))

    assert server._sync_claude_local() == 0
    assert not import_called
    assert saved_progress == []
    assert server._cc_sync_error == "上次错误"  # 空采集不清错误


# ---------------------------------------------------------------------------
# 2. 异常吞并: 不外抛 / 记录文案 / 不推进进度 / 下次成功后清空
# ---------------------------------------------------------------------------


def test_sync_claude_local_swallows_exception(tmp_db, claude_state, monkeypatch):
    monkeypatch.setattr(db, "get_claudecode_enabled_at", lambda: 1_000)
    monkeypatch.setattr(db, "get_claude_file_progress_all", lambda: {})

    def boom(enabled_at, progress, force=False):
        raise RuntimeError("claude projects unreadable")

    monkeypatch.setattr(claudecode_api, "import_incremental", boom)
    saved_progress = []
    monkeypatch.setattr(db, "save_claude_file_progress",
                        lambda *a: saved_progress.append(a))

    # 不抛, 返回 0
    assert server._sync_claude_local() == 0
    assert "claude projects unreadable" in server._cc_sync_error
    assert saved_progress == []  # 异常: 进度不推进

    # 下次成功 (有批次导入) 后错误清空
    monkeypatch.setattr(claudecode_api, "import_incremental",
                        lambda enabled_at, progress, force=False: [
                            {"path": "/p/a.jsonl", "rows": [{"dedupe_key": "k1"}],
                             "new_offset": 10, "size": 10},
                        ])
    monkeypatch.setattr(server, "_load_model_pricing", lambda: PRICING)
    monkeypatch.setattr(db, "import_claudecode_usage", lambda rows, pricing: 1)
    monkeypatch.setattr(db, "save_claude_file_progress", lambda *a: None)
    assert server._sync_claude_local() == 1
    assert server._cc_sync_error == ""


# ---------------------------------------------------------------------------
# 3. _claudecode_summary_payload: 形状 / db_found 两分支 / range 映射
# ---------------------------------------------------------------------------


def test_summary_payload_shape(tmp_db, claude_state, monkeypatch):
    _existing_projects_dir(tmp_db, monkeypatch)
    _patch_aggregates(monkeypatch)
    # 插入一行使 MAX(synced_at) 有值
    conn = db.get_db()
    conn.execute(
        "INSERT INTO claudecode_usage (dedupe_key, started_at, synced_at)"
        " VALUES ('t1', '2026-01-01T00:00:00.000Z', '2026-01-02T03:04:05.000Z')"
    )
    conn.commit()

    payload = server._claudecode_summary_payload("7d")
    assert set(payload.keys()) == {
        "db_found", "last_import_at", "error", "range",
        "totals", "daily7", "channels", "models",
    }
    assert payload["db_found"] is True
    assert payload["last_import_at"] == "2026-01-02T03:04:05.000Z"
    assert payload["error"] == ""
    assert payload["range"] == "7d"  # range 原文
    assert payload["totals"] == {"request_count": 3, "period": "7d"}
    assert payload["daily7"] == [{"date": "2026-09-01", "days": 7}]  # 固定 7 天
    assert payload["channels"] == [{"channel": "官方", "period": "7d"}]
    assert payload["models"] == [{"model": "claude-sonnet-4-5", "period": "7d"}]


def test_summary_payload_range_mapping(tmp_db, claude_state, monkeypatch):
    _existing_projects_dir(tmp_db, monkeypatch)
    _patch_aggregates(monkeypatch)
    # today / 7d / all 照原文传 period, 无效值 → 30d 口径
    assert server._claudecode_summary_payload("today")["totals"]["period"] == "today"
    assert server._claudecode_summary_payload("7d")["totals"]["period"] == "7d"
    assert server._claudecode_summary_payload("all")["totals"]["period"] == "all"
    assert server._claudecode_summary_payload("30d")["totals"]["period"] == "30d"
    assert server._claudecode_summary_payload("banana")["totals"]["period"] == "30d"
    assert server._claudecode_summary_payload("banana")["range"] == "banana"


def test_summary_payload_db_missing(tmp_db, claude_state, monkeypatch):
    monkeypatch.setattr(claudecode_api, "CLAUDE_PROJECTS", tmp_db / "missing")
    monkeypatch.setattr(server, "_cc_sync_error", "历史错误文案")
    payload = server._claudecode_summary_payload("30d")
    assert payload["db_found"] is False
    assert payload["last_import_at"] is None
    assert payload["error"] == "历史错误文案"
    assert payload["range"] == "30d"
    # 空结构
    assert payload["totals"] == {}
    assert payload["daily7"] == []
    assert payload["channels"] == []
    assert payload["models"] == []


# ---------------------------------------------------------------------------
# 4. 防抖: 60s 内多次 payload 请求只触发一次导入, 超 60s 再触发
# ---------------------------------------------------------------------------


def test_summary_import_debounce(tmp_db, claude_state, monkeypatch):
    triggers = []
    monkeypatch.setattr(server, "claude_import_async", lambda: triggers.append(1))
    clock = {"now": 1000.0}
    # 只替换 server 模块内的 time 引用, 不动 stdlib time 模块
    monkeypatch.setattr(server, "time", SimpleNamespace(time=lambda: clock["now"]))

    server._maybe_trigger_claude_import()  # 初值 0.0, 距今远超 60s → 触发
    assert triggers == [1]
    clock["now"] = 1030.0  # 30s 后: 不触发
    server._maybe_trigger_claude_import()
    assert triggers == [1]
    clock["now"] = 1060.0  # 恰好 60s (边界 <=): 不触发
    server._maybe_trigger_claude_import()
    assert triggers == [1]
    clock["now"] = 1061.0  # 超过 60s: 再触发
    server._maybe_trigger_claude_import()
    assert triggers == [1, 1]


# ---------------------------------------------------------------------------
# 5. 与 zcode 端点互不干扰: 状态/防抖/db_found 判定彼此独立
# ---------------------------------------------------------------------------


def test_claude_and_zcode_endpoints_independent(
    tmp_db, zcode_state, claude_state, monkeypatch
):
    # zcode 侧: 库文件缺失; claude 侧: projects 目录存在 → db_found 各自判定
    monkeypatch.setattr(zcode_api, "ZCODE_DB", tmp_db / "missing.sqlite")
    _existing_projects_dir(tmp_db, monkeypatch)
    _patch_aggregates(monkeypatch)
    monkeypatch.setattr(server, "_zcode_sync_error", "zc-err")
    monkeypatch.setattr(server, "_cc_sync_error", "cc-err")

    zc = server._zcode_summary_payload("all")
    cc = server._claudecode_summary_payload("all")
    assert zc["db_found"] is False
    assert zc["error"] == "zc-err"
    assert cc["db_found"] is True
    assert cc["error"] == "cc-err"
    assert cc["totals"]["period"] == "all"

    # 防抖触发互不影响: 各自只触发自己的导入入口
    triggers = []
    monkeypatch.setattr(server, "zcode_import_async", lambda: triggers.append("zcode"))
    monkeypatch.setattr(server, "claude_import_async", lambda: triggers.append("claude"))
    server._maybe_trigger_zcode_import()
    server._maybe_trigger_claude_import()
    assert triggers == ["zcode", "claude"]
    # zcode 触发不占用 claude 的防抖窗口, 反之亦然 (各自时间戳独立)
    server._maybe_trigger_zcode_import()
    server._maybe_trigger_claude_import()
    assert triggers == ["zcode", "claude"]
