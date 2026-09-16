"""WorkBuddy 本地导入编排与读取端点触发单测.

行数据由 conftest 的 wb_row fixture 提供 (tests/ 无 __init__.py, 不可跨文件 import).
"""
from __future__ import annotations

from pathlib import Path
import pytest

from app import server

ROOT = Path(__file__).resolve().parents[1]


def test_sync_workbuddy_local_persists_batches(tmp_db, wb_row, monkeypatch):
    """编排: 采一批 → 落库 → 推进游标; 返回新增行数."""
    batch = {"path": "C:\\wb\\s1.jsonl", "rows": [wb_row("m1"), wb_row("m2")],
             "new_offset": 400, "size": 400}
    monkeypatch.setattr(server.workbuddy_local_api, "import_incremental",
                        lambda progress, **kw: [batch])
    assert server._sync_workbuddy_local(force=True) == 2
    assert server.db.get_workbuddy_file_progress_all() == {"C:\\wb\\s1.jsonl": (400, 400)}


def test_sync_workbuddy_local_no_batches_is_noop(tmp_db, monkeypatch):
    monkeypatch.setattr(server.workbuddy_local_api, "import_incremental",
                        lambda progress, **kw: [])
    assert server._sync_workbuddy_local(force=True) == 0


def test_sync_workbuddy_local_swallows_errors(tmp_db, monkeypatch):
    def boom(progress, **kw):
        raise RuntimeError("采集炸了")

    monkeypatch.setattr(server.workbuddy_local_api, "import_incremental", boom)
    assert server._sync_workbuddy_local(force=True) == 0   # 异常不外抛


def test_maybe_trigger_is_debounced(monkeypatch):
    calls = []
    monkeypatch.setattr(server, "workbuddy_import_async", lambda: calls.append(1))
    server._wb_last_import_trigger = None
    server._maybe_trigger_workbuddy_import()
    server._maybe_trigger_workbuddy_import()     # 60s 窗口内不再触发
    assert len(calls) == 1


class _ApiHandler:
    command = "GET"

    def __init__(self):
        self.payload = None
        self.status = 200

    def send_response(self, status):
        self.status = status

    def send_header(self, *_):
        pass

    def end_headers(self):
        pass


def _call_api(monkeypatch, route, query):
    handler = _ApiHandler()
    captured = {}

    def mock_json_resp(h, payload, status=200):
        captured["payload"] = payload
        captured["status"] = status

    monkeypatch.setattr(server, "_json_response", mock_json_resp)
    server._handle_api(handler, route, query)
    return captured.get("payload")


@pytest.fixture(autouse=True)
def isolate_server_tests(tmp_path, monkeypatch):
    """测试隔离: projects 指向 tmp_path, 重置触发防抖与运行状态."""
    projects = tmp_path / "workbuddy" / "projects"
    projects.mkdir(parents=True)
    monkeypatch.setattr(server.workbuddy_local_api, "WORKBUDDY_PROJECTS", projects)
    monkeypatch.setattr(server, "_wb_last_import_trigger", None)
    monkeypatch.setattr(server, "_wb_sync_error", "")
    server._wb_import_running = False
    if server._wb_import_lock.locked():
        server._wb_import_lock.release()
    yield
    server._wb_import_running = False
    if server._wb_import_lock.locked():
        server._wb_import_lock.release()


@pytest.mark.parametrize("route,query", [
    ("/api/report/channel-overview", {"channel": ["workbuddy"]}),
    ("/api/report/channel-trend", {"channel": ["workbuddy"]}),
    ("/api/report/windows", {"channel": ["workbuddy"]}),
    ("/api/report/windows", {}),
    ("/api/report/daily", {"channel": ["workbuddy"]}),
    ("/api/report/daily", {}),
    ("/api/report/hourly", {"channel": ["workbuddy"]}),
    ("/api/report/hourly", {}),
    ("/api/report/channels", {}),
    ("/api/dashboard", {"scope": ["all"]}),
])
def test_read_entry_points_trigger_workbuddy_import(tmp_db, monkeypatch, route, query):
    calls = []
    monkeypatch.setattr(server, "workbuddy_import_async", lambda: calls.append(1))
    monkeypatch.setattr(server.dsh_api, "get_dsh_summary", lambda *args: {"found": False})
    monkeypatch.setattr(server.dsh_api, "get_dsh_summaries", lambda *args: {r: {"found": False} for r in args})
    _call_api(monkeypatch, route, query)
    assert len(calls) == 1


@pytest.mark.parametrize("route,query", [
    ("/api/report/channel-overview", {"channel": ["opencode"]}),
    ("/api/report/channel-trend", {"channel": ["opencode"]}),
    ("/api/report/windows", {"channel": ["opencode"]}),
    ("/api/report/daily", {"channel": ["opencode"]}),
    ("/api/report/hourly", {"channel": ["opencode"]}),
    ("/api/workbuddy/summary", {}),
])
def test_other_channels_and_remote_summary_do_not_trigger_wb_import(tmp_db, monkeypatch, route, query):
    calls = []
    monkeypatch.setattr(server, "workbuddy_import_async", lambda: calls.append(1))
    monkeypatch.setattr(server.dsh_api, "get_dsh_summary", lambda *args: {"found": False})
    monkeypatch.setattr(server.dsh_api, "get_dsh_summaries", lambda *args: {r: {"found": False} for r in args})
    _call_api(monkeypatch, route, query)
    assert len(calls) == 0


def test_workbuddy_import_async_concurrency(monkeypatch):
    """并发触发只启动一个 worker."""
    import time
    started = []

    def fake_sync():
        started.append(1)
        time.sleep(0.05)

    monkeypatch.setattr(server, "_sync_workbuddy_local", fake_sync)
    server.workbuddy_import_async()
    server.workbuddy_import_async()
    assert server._wb_import_running is True
    with server._wb_import_lock:
        pass
    assert server._wb_import_running is False
    assert len(started) == 1


def test_lock_released_on_import_exception(monkeypatch):
    """导入内部抛出异常时释放锁并复位 running."""
    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(server, "_sync_workbuddy_local", boom)
    server.workbuddy_import_async()
    with server._wb_import_lock:
        pass
    assert server._wb_import_running is False
    assert not server._wb_import_lock.locked()


def test_lock_released_on_thread_start_exception(monkeypatch):
    """Thread.start 失败时释放锁并复位 running."""
    class BadThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            raise RuntimeError("thread fail")

    monkeypatch.setattr(server.threading, "Thread", BadThread)
    with pytest.raises(RuntimeError):
        server.workbuddy_import_async()
    assert server._wb_import_running is False
    assert not server._wb_import_lock.locked()


def test_running_snapshot_in_response(tmp_db, monkeypatch):
    """持有 worker 时 running=True, 结束后 False."""
    monkeypatch.setattr(server.dsh_api, "get_dsh_summary", lambda *args: {"found": False})
    monkeypatch.setattr(server.dsh_api, "get_dsh_summaries", lambda *args: {r: {"found": False} for r in args})
    server._wb_import_running = True
    payload = _call_api(monkeypatch, "/api/report/channel-overview", {"channel": ["workbuddy"]})
    assert payload["workbuddy_local"]["running"] is True
    server._wb_import_running = False
    payload = _call_api(monkeypatch, "/api/report/channel-overview", {"channel": ["workbuddy"]})
    assert payload["workbuddy_local"]["running"] is False


def test_sync_workbuddy_local_failure_does_not_advance_cursor(tmp_db, wb_row, monkeypatch):
    """行入库失败 (约束错误) 回滚, 不推进游标."""
    batch = {"path": "C:\\wb\\s1.jsonl", "rows": [wb_row("m1"), dict(wb_row("bad"), dedupe_key=None)],
             "new_offset": 400, "size": 400}
    monkeypatch.setattr(server.workbuddy_local_api, "import_incremental",
                        lambda progress, **kw: [batch])
    assert server._sync_workbuddy_local(force=True) == 0
    assert server.db.get_workbuddy_file_progress_all() == {}
