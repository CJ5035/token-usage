"""dsh_api 后台化单测 (EVOLUTION-5 §1): TTL 过期返 stale + 后台重扫 / 防重入 /
冷启动空态 / 失败退避 / 热态失败保 stale / scan_sync 语义 (§3.4 锁 + Condition 防重入).

线程同步策略 (计划测试点 1 指定): monkeypatch threading.Thread 捕获 target,
由测试手动执行或同步执行, 杜绝真实 daemon 线程的断言时序不稳定.
全部走临时目录 + monkeypatch 伪造 ~/.dsh/sessions, 不读本机真实 dsh 日志.
"""
from __future__ import annotations

import json
import threading

import pytest
import zstandard

from app import dsh_api


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _install_fake_thread(monkeypatch, run_immediately: bool) -> list:
    """monkeypatch threading.Thread 捕获 spawn 的 target, 返回 spawned 列表.

    run_immediately=True 时 start() 内同步执行 target (失败路径需立即生效);
    False 时仅捕获不执行, 由测试手动调 spawned[0]() 控制时机.
    """
    spawned: list = []

    class _FakeThread:
        def __init__(self, target=None, daemon=False, name=None):
            self._target = target

        def start(self):
            spawned.append(self._target)
            if run_immediately:
                self._target()

    monkeypatch.setattr(threading, "Thread", _FakeThread)
    return spawned


def _boom() -> dict:
    raise RuntimeError("scan failed")


def _write_session(root, ws, sid, out_tokens=1) -> None:
    """写一个最小会话日志 (每事件一帧, 拼接为多帧 zstd 流)."""
    events = [
        {"type": "request/context", "time": 0, "data": {"provider": "p", "model": "m"}},
        {"type": "assistant/message", "time": 1000, "data": {"turn": 1, "step": 1,
         "usage": {"inputTokens": 1, "outputTokens": out_tokens}}},
    ]
    d = root / ws / sid
    d.mkdir(parents=True, exist_ok=True)
    frames = b"".join(
        zstandard.compress((json.dumps(e) + "\n").encode("utf-8")) for e in events
    )
    (d / "session.jsonl.zstd").write_bytes(frames)


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前后重置模块级缓存与后台状态, 避免用例间互相污染."""
    _wipe()
    yield
    _wipe()


def _wipe() -> None:
    dsh_api._cache_payload = None
    dsh_api._cache_ts = 0.0
    dsh_api._refreshing = False
    dsh_api._fail_count = 0
    dsh_api._last_fail_ts = 0.0
    dsh_api._round_error = None


def _expire_cache() -> None:
    """把缓存时间戳回拨到 TTL 之外 (模拟热态过期)."""
    dsh_api._cache_ts -= dsh_api.CACHE_TTL_SECONDS + 1


# ---------------------------------------------------------------------------
# 1. TTL 过期: 返 stale + 触发后台刷新
# ---------------------------------------------------------------------------

def test_ttl_expired_returns_stale_and_spawns_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    spawned = _install_fake_thread(monkeypatch, run_immediately=False)
    _write_session(tmp_path, "ws", "s1")

    dsh_api.scan_sync()          # 同步扫描建立热态缓存
    stale = dsh_api._cache_payload
    _expire_cache()

    _write_session(tmp_path, "ws", "s2")
    r = dsh_api.get_dsh_usage()
    assert r is not stale                   # 过期即返 stale 的公开副本
    assert r["sessions_count"] == stale["sessions_count"]
    assert r["sessions_count"] == 1
    assert spawned == [dsh_api._rescan_worker]   # 且触发了后台刷新 (仅 spawn 未执行)
    assert dsh_api._refreshing is True

    spawned[0]()                            # 同步驱动后台扫描完成
    assert dsh_api._refreshing is False
    r2 = dsh_api.get_dsh_usage()            # 下一次调用取到新数据 (无自动轮询)
    assert r2 is not stale
    assert r2["sessions_count"] == 2


# ---------------------------------------------------------------------------
# 2. 防重入: 重扫进行中并发调用仅一次扫描
# ---------------------------------------------------------------------------

def test_no_reentrant_spawn_while_refreshing(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    spawned = _install_fake_thread(monkeypatch, run_immediately=False)
    _write_session(tmp_path, "ws", "s1")
    dsh_api.scan_sync()
    _expire_cache()

    dsh_api.get_dsh_usage()     # 第一次: spawn (_refreshing=True, target 未执行)
    dsh_api.get_dsh_usage()     # 第二次: _refreshing 守卫拦截, 不再 spawn
    dsh_api.get_dsh_usage()
    assert len(spawned) == 1

    spawned[0]()                # 收尾: 释放 _refreshing, 不依赖 fixture 兜底


# ---------------------------------------------------------------------------
# 3. 冷启动: 返回 found=false 空态, 不抛错
# ---------------------------------------------------------------------------

def test_cold_start_returns_empty_state_no_raise(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    spawned = _install_fake_thread(monkeypatch, run_immediately=False)

    r = dsh_api.get_dsh_usage()   # 无缓存 + 目录不存在, 不抛错不阻塞
    assert r["found"] is False
    assert r["sessions_count"] == 0
    assert dsh_api._cache_payload is None      # worker 未执行, 缓存仍空
    assert spawned == [dsh_api._rescan_worker]


# ---------------------------------------------------------------------------
# 4. 失败退避: 失败记 _last_fail_ts, 60s 内不再 spawn, 窗外恢复; 无永久拦截
# ---------------------------------------------------------------------------

def test_fail_backoff_blocks_spawn_within_window(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    fake = {"now": 1000.0}
    monkeypatch.setattr(dsh_api.time, "time", lambda: fake["now"])
    monkeypatch.setattr(dsh_api, "scan", _boom)
    spawned = _install_fake_thread(monkeypatch, run_immediately=True)

    dsh_api.get_dsh_usage()     # 冷启动失败: _fail_count=1, 记 _last_fail_ts
    assert dsh_api._fail_count == 1
    assert dsh_api._last_fail_ts == pytest.approx(1000.0)

    fake["now"] += 1            # 退避窗内 (1s < 60s)
    dsh_api.get_dsh_usage()     # 失败退避守卫拦截, 不再 spawn
    assert len(spawned) == 1

    fake["now"] += dsh_api._FAIL_BACKOFF_SECONDS   # 退避窗过后恢复 spawn
    dsh_api.get_dsh_usage()
    assert len(spawned) == 2
    assert dsh_api._fail_count == 2


def test_no_permanent_gate_after_three_failures(tmp_path, monkeypatch):
    """§3.4: 删除 `_fail_count >= 3` 永久拦截 — 连续 3 次失败后, 退避窗外仍恢复自动刷新."""
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    fake = {"now": 2000.0}
    monkeypatch.setattr(dsh_api.time, "time", lambda: fake["now"])
    monkeypatch.setattr(dsh_api, "scan", _boom)
    spawned = _install_fake_thread(monkeypatch, run_immediately=True)

    for _ in range(3):          # 连续 3 次失败 (旧代码在此之后永久停止自动刷新)
        fake["now"] += dsh_api._FAIL_BACKOFF_SECONDS
        dsh_api.get_dsh_usage()
    assert dsh_api._fail_count == 3
    assert len(spawned) == 3

    fake["now"] += dsh_api._FAIL_BACKOFF_SECONDS   # 无永久拦截: 退避窗外继续 spawn
    dsh_api.get_dsh_usage()
    assert len(spawned) == 4


# ---------------------------------------------------------------------------
# 5. 热态失败: 保留 stale 真数据, 不被空态覆盖
# ---------------------------------------------------------------------------

def test_hot_failure_keeps_stale_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    _install_fake_thread(monkeypatch, run_immediately=True)
    _write_session(tmp_path, "ws", "s1")

    dsh_api.scan_sync()         # 建立热态 (found=true 真数据)
    hot = dsh_api._cache_payload
    assert hot["found"] is True
    monkeypatch.setattr(dsh_api, "scan", _boom)   # 热态建立后再注入扫描失败
    _expire_cache()

    dsh_api.get_dsh_usage()     # 后台扫描失败 (同步驱动)
    assert dsh_api._fail_count == 1
    assert dsh_api._cache_payload is hot     # 热态失败保留 stale, 不被 _empty_result 覆盖
    assert dsh_api._cache_payload["found"] is True


# ---------------------------------------------------------------------------
# 6. 冷启动失败: 写 _empty_result 空态 (found=false)
# ---------------------------------------------------------------------------

def test_cold_failure_writes_empty_result(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    monkeypatch.setattr(dsh_api, "scan", _boom)
    _install_fake_thread(monkeypatch, run_immediately=True)

    r = dsh_api.get_dsh_usage()   # 冷启动 + 扫描失败 → 写空态兜底, 不抛错
    assert r["found"] is False
    assert dsh_api._cache_payload is not r     # 公开副本不暴露可变缓存
    assert dsh_api._cache_payload["found"] is r["found"]
    assert dsh_api._fail_count == 1


# ---------------------------------------------------------------------------
# 7. scan_sync 成功: 复位失败计数/退避并写缓存
# ---------------------------------------------------------------------------

def test_scan_sync_success_resets_fail_state(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    _write_session(tmp_path, "ws", "s1")
    dsh_api._fail_count = 3
    dsh_api._last_fail_ts = 123.0
    dsh_api._cache_payload = {"old": True}
    dsh_api._cache_ts = 1.0

    payload = dsh_api.scan_sync()
    assert payload["found"] is True
    assert dsh_api._cache_payload is not payload  # 写缓存，返回公开副本
    assert dsh_api._cache_payload["found"] is payload["found"]
    assert dsh_api._cache_ts > 0
    assert dsh_api._fail_count == 0            # 复位失败计数
    assert dsh_api._last_fail_ts == 0.0        # 退出退避窗


# ---------------------------------------------------------------------------
# 8. scan_sync 失败: 异常向上抛, 缓存与计数均不变
# ---------------------------------------------------------------------------

def test_scan_sync_failure_raises_without_cache_write(tmp_path, monkeypatch):
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    monkeypatch.setattr(dsh_api, "scan", _boom)
    dsh_api._cache_payload = {"old": True}
    dsh_api._cache_ts = 1.0
    dsh_api._fail_count = 2

    with pytest.raises(RuntimeError):
        dsh_api.scan_sync()
    assert dsh_api._cache_payload == {"old": True}   # 缓存不变 (不写不清)
    assert dsh_api._cache_ts == 1.0
    assert dsh_api._fail_count == 2                  # 计数不变 (不置零不累加)


# ---------------------------------------------------------------------------
# 9. §3.4 并发防重入: scan_sync 与 worker 共用 Condition, 并发只一轮扫描
# ---------------------------------------------------------------------------

def _trace_condition_wait(monkeypatch) -> threading.Event:
    """包装 _scan_cond.wait, 返回在等待方真正进入 Condition 等待时置位的事件
    (保证 gate 释放时等待方已挂起, 消除线程调度竞态)。"""
    waiter_waiting = threading.Event()
    original_wait = dsh_api._scan_cond.wait

    def traced_wait(timeout=None):
        waiter_waiting.set()
        return original_wait(timeout)

    monkeypatch.setattr(dsh_api._scan_cond, "wait", traced_wait)
    return waiter_waiting


def test_concurrent_scan_sync_waiters_run_exactly_one_scan(tmp_path, monkeypatch):
    """V4 缺口闭合: scan_sync 与在途轮共用防重入 — 两个并发调用只执行一次扫描,
    且双方都拿到同一发布快照。"""
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    gate = threading.Event()
    started = threading.Event()
    waiter_waiting = _trace_condition_wait(monkeypatch)
    calls = []

    def gated_scan() -> dict:
        calls.append(1)
        started.set()
        assert gate.wait(timeout=5)
        return {"found": True, "updated_at": "sync", "sessions_count": 7,
                "total": {}, "today": {}, "providers": [], "models": [], "unkeyed_steps": 0}

    monkeypatch.setattr(dsh_api, "scan", gated_scan)

    results = {}

    def first_caller():
        results["first"] = dsh_api.scan_sync()

    first = threading.Thread(target=first_caller)
    first.start()
    assert started.wait(timeout=5)          # 第一轮扫描已在途 (scan_sync 自身执行)

    def second_caller():
        results["second"] = dsh_api.scan_sync()

    second = threading.Thread(target=second_caller)
    second.start()
    assert waiter_waiting.wait(timeout=5)   # 第二个调用方已挂起等待在途轮
    gate.set()                              # 放行在途轮
    first.join(timeout=5)
    second.join(timeout=5)

    assert len(calls) == 1                  # 并发只一轮扫描
    assert results["first"]["sessions_count"] == 7
    assert results["second"]["sessions_count"] == 7   # 等待方拿到同一发布快照
    assert dsh_api._refreshing is False
    assert dsh_api._fail_count == 0


def test_scan_sync_waits_for_in_flight_worker_round(tmp_path, monkeypatch):
    """scan_sync 等待在途 worker 轮而非并行扫描: 成功时返回其发布快照, 不再自行扫描."""
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    gate = threading.Event()
    started = threading.Event()
    waiter_waiting = _trace_condition_wait(monkeypatch)
    calls = []

    def gated_scan() -> dict:
        calls.append(1)
        started.set()
        assert gate.wait(timeout=5)
        return {"found": True, "updated_at": "worker", "sessions_count": 9,
                "total": {}, "today": {}, "providers": [], "models": [], "unkeyed_steps": 0}

    monkeypatch.setattr(dsh_api, "scan", gated_scan)

    dsh_api._cache_payload = {"found": True, "updated_at": "old", "sessions_count": 1}
    dsh_api._cache_ts = 1.0                 # 过期 → 后台 spawn 真实 worker 线程
    dsh_api.get_dsh_usage()
    assert dsh_api._refreshing is True
    assert started.wait(timeout=5)          # worker 已在途 (卡在 gate)
    assert dsh_api._cache_payload["updated_at"] == "old"   # 扫描被 gate 挡住, 尚未发布

    outcome = {}

    def sync_caller():
        outcome["result"] = dsh_api.scan_sync()

    waiter = threading.Thread(target=sync_caller)
    waiter.start()
    assert waiter_waiting.wait(timeout=5)   # scan_sync 已挂起等待 worker 轮
    gate.set()                              # 放行 worker 轮
    waiter.join(timeout=5)

    assert len(calls) == 1                  # 等待方未启动第二次扫描
    assert outcome["result"]["sessions_count"] == 9   # 拿到 worker 发布的新快照


def test_scan_sync_waiter_raises_worker_round_failure(tmp_path, monkeypatch):
    """§3.4: 在途轮失败时, 等待中的 scan_sync 抛出该轮错误 (完成或失败后返回/抛错)."""
    monkeypatch.setattr(dsh_api, "sessions_root", lambda: tmp_path)
    gate = threading.Event()
    started = threading.Event()
    waiter_waiting = _trace_condition_wait(monkeypatch)
    calls = []

    def gated_scan() -> dict:
        calls.append(1)
        started.set()
        assert gate.wait(timeout=5)
        raise RuntimeError("worker failed")

    monkeypatch.setattr(dsh_api, "scan", gated_scan)

    dsh_api._cache_payload = {"found": True, "updated_at": "old", "sessions_count": 1}
    dsh_api._cache_ts = 1.0
    dsh_api.get_dsh_usage()                 # 后台 spawn 真实 worker 线程
    assert started.wait(timeout=5)

    outcome = {}

    def sync_caller():
        try:
            outcome["result"] = dsh_api.scan_sync()
        except Exception as exc:  # noqa: BLE001
            outcome["error"] = exc

    waiter = threading.Thread(target=sync_caller)
    waiter.start()
    assert waiter_waiting.wait(timeout=5)   # scan_sync 已挂起等待 worker 轮
    gate.set()                              # 放行失败的 worker 轮
    waiter.join(timeout=5)

    assert len(calls) == 1
    assert isinstance(outcome.get("error"), RuntimeError)   # 失败轮错误向等待方抛出
    assert dsh_api._fail_count == 1          # 热态失败保留 stale + 记退避
    assert dsh_api._cache_payload["updated_at"] == "old"
