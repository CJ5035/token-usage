import os
import sys

# 让 pytest 能从 tests/ 目录导入仓库根下的 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone
import pytest
from app import db

@pytest.fixture
def tmp_codex_db(tmp_path, monkeypatch):
    db.close_db()
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    yield tmp_path
    db.close_db()

@pytest.fixture
def local_iso():
    def make(days=0):
        local = datetime.now() - timedelta(days=days)
        local = local.replace(hour=12, minute=0, second=0, microsecond=0)
        return local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return make

@pytest.fixture
def codex_row(local_iso):
    def make(row_id="s:1", **overrides):
        sid, seq = row_id.rsplit(":", 1)
        row = dict(id=row_id, session_id=sid, event_seq=int(seq),
                   event_mode="token_count", response_id=None,
                   started_at=local_iso(), model="m1", provider_id="codex",
                   input_tokens=100, cache_read_tokens=20, cache_write_tokens=0,
                   output_tokens=30, reasoning_tokens=4, total_tokens=130,
                   duration_ms=None, speed_tps=None, speed_source=None,
                   request_count_exact=False, model_revision_at=0,
                   cost_raw=None, file_path="fixture.jsonl")
        row.update(overrides)
        return row
    return make


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """把 db 数据目录指向临时目录 (通用版, 同 tmp_codex_db 模式)."""
    db.close_db()
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    yield tmp_path
    db.close_db()


@pytest.fixture(autouse=True)
def isolate_workbuddy_scan_root(tmp_path, monkeypatch):
    """默认把 WorkBuddy 本地采集根重定向到空临时目录, 并重置触发/节流全局.

    读取端点 (/api/dashboard?scope=all, /api/report/* 等) 会触发后台导入线程,
    其扫描根默认是真实机器的 ~/.workbuddy/projects —— 线程会把真实用量行写进
    当前用例的临时库, 断言随即读到上万级 token (仅按子集执行时暴露, 全量运行被
    掩盖; 见 doc/20260917-WorkBuddy本地导入测试隔离缺陷修复实施计划.md)。

    自守卫: 仅当当前值指向本用例 tmp 之外时才重定向, 故已自行把该常量指向
    tmp 的用例 (test_workbuddy_local_api / test_workbuddy_local_server) 不受影响,
    无论两者实例化顺序如何。
    """
    from app import server, workbuddy_local_api

    current = str(getattr(workbuddy_local_api, "WORKBUDDY_PROJECTS", ""))
    if not current.startswith(str(tmp_path)):
        empty = tmp_path / "_empty_wb_projects"
        empty.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(workbuddy_local_api, "WORKBUDDY_PROJECTS", empty)
    monkeypatch.setattr(server, "_wb_last_import_trigger", None)
    monkeypatch.setattr(workbuddy_local_api, "_last_import_at", None)


@pytest.fixture
def wb_row(local_iso):
    """WorkBuddy 本地用量行工厂; total_tokens 由四项相加推出, 保证行内恒等式成立 (R8).

    注意: output_tokens 是"非思考输出"(已完成 R8 扣减), 与 reasoning_tokens 互不重叠。
    started_at 默认取"今天本地 12:00 的 UTC 表示"(local_iso), 使范围查询用例长期稳定,
    不随真实日期漂移。
    """
    def make(dedupe_key="m1", session_id="s1", credit=0.85, cost_raw=1000, available=1,
             input_tokens=200, cache_read_tokens=100, output_tokens=50, reasoning_tokens=7,
             started_at=None, **overrides):
        row = dict(
            dedupe_key=dedupe_key, session_id=session_id, model="deepseek-v4.1-flash",
            model_name="Deepseek-V4.1-Flash", trace_id="t1",
            started_at=started_at or local_iso(),
            input_tokens=input_tokens, output_tokens=output_tokens,
            reasoning_tokens=reasoning_tokens, cache_read_tokens=cache_read_tokens,
            cache_write_tokens=0,
            total_tokens=input_tokens + cache_read_tokens + output_tokens + reasoning_tokens,
            credit=credit, cost_raw=cost_raw, cost_available=available,
            file_path="C:\\wb\\s1.jsonl")
        row.update(overrides)
        return row
    return make


@pytest.fixture(autouse=True)
def isolate_kiro_sources(tmp_path, monkeypatch):
    """默认把 Kiro 本机数据源指向本用例 tmp 下不存在的路径 (理由同
    isolate_workbuddy_scan_root: 读取端点会触发后台导入)。需要真实目录的用例在
    用例体内自行 monkeypatch 覆盖 (autouse 先于用例体执行)。"""
    from app import kiro_local_api

    monkeypatch.setattr(kiro_local_api, "KIRO_SESSIONS_DIR", tmp_path / "_no_kiro_sessions")
    monkeypatch.setattr(kiro_local_api, "_last_import_at", None)
    from app import kiro_api

    monkeypatch.setattr(kiro_api, "KIRO_DATA_DB", tmp_path / "_no_kiro_data.sqlite3")
    monkeypatch.setattr(kiro_api, "_last_good", None)
    from app import server

    monkeypatch.setattr(server, "_kiro_last_import_trigger", None)
    monkeypatch.setattr(server, "_kiro_sync_error", "")
    monkeypatch.setattr(server, "_kiro_quota_cache", {"at": 0.0, "data": None})


@pytest.fixture
def kiro_row(local_iso):
    """Kiro 本地用量行工厂 (字段对齐 kiro_local_api 行契约); cost_raw 按 credits × 0.04 USD 推出。
    started_at 默认取今天本地 12:00 的 UTC 表示, 范围查询长期稳定。"""
    def make(dedupe_key="s1:t1", session_id="s1", model="claude-opus-5", credits=2.5,
             request_count=3, duration_ms=60_000, started_at=None, **overrides):
        started = started_at or local_iso()
        row = dict(dedupe_key=dedupe_key, session_id=session_id, model=model,
                   started_at=started, ended_at=started, duration_ms=duration_ms,
                   request_count=request_count, credits=credits,
                   cost_raw=int(round(credits * 0.04 * 1e8)), context_pct=12.5,
                   file_path="C:\\kiro\\s1.json")
        row.update(overrides)
        return row
    return make
