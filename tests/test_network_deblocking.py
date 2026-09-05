"""网络去阻塞回归测试 (EVOLUTION-3 Task 1): 汇率后台化 + ZCode 统一单飞.

覆盖计划 §2.1/§2.2:
- 汇率: TTL 内读零网络; 过期读触发后台刷新且本次返回旧值; 失败写缓存 6h;
  刷新防重入.
- ZCode 单飞: 并发 N 请求仅 1 次外呼共享结果; 预热 worker 与请求路径并发
  仅 1 次; 过期缓存后台刷新真实外呼更新 (§1.2.1 v3 修正回归); 等待者超时
  返回错误占位并入队后台刷新.
- §3 (Task 3 验收回归补充): 启动预热行为与 main.py 接线; 前端无 DOM 自动化
  设施, 以源码级契约测试锁跨语言漂移点 + node --check.

全部 monkeypatch/打桩, 不起真实网络请求.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from app import server, zcode_api

CREDENTIAL_ERROR_PREFIX = zcode_api.CREDENTIAL_ERROR_PREFIX
_APP_JS = Path(server.__file__).parent / "web" / "app.js"


class _FakeResp:
    """urlopen 返回值的上下文管理器桩."""

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


def _stub_urlopen(monkeypatch, calls, body=None, error=None):
    """把 urlopen 换成记录调用的桩 (_refresh_usd_cny 内 import 同一模块对象)."""

    def fake_urlopen(req, timeout=None):
        calls.append({"url": req.full_url, "timeout": timeout})
        if error is not None:
            raise error
        return _FakeResp(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)


def _wait_until(predicate, timeout=5.0):
    """轮询等待后台线程完成 (带截止时间, 避免用例挂死)."""
    deadline = time.time() + timeout
    while not predicate():
        if time.time() > deadline:
            return False
        time.sleep(0.01)
    return True


@pytest.fixture()
def net_state(monkeypatch):
    """复位 server 的汇率/ZCode 模块级状态与单飞锁, 隔离用例间污染."""
    monkeypatch.setattr(server, "_exchange_cache", {"at": 0.0, "usd_cny": 7.2})
    monkeypatch.setattr(server, "_exchange_refreshing", False)
    monkeypatch.setattr(server, "_zcode_quota_cache", {"at": 0.0, "data": None})
    monkeypatch.setattr(server, "_zcode_quota_refreshing", False)
    monkeypatch.setattr(server, "_zcode_first_fetch_lock", threading.Lock())
    monkeypatch.setattr(server, "_ZCODE_FETCH_WAIT", zcode_api.QUOTA_TIMEOUT + 2)


# ---------------------------------------------------------------------------
# 1. 汇率后台化: 纯缓存读 / 过期触发后台刷新 / 失败写缓存 6h / 防重入
# ---------------------------------------------------------------------------


def test_exchange_ttl_read_zero_network(net_state, monkeypatch):
    """TTL 内读缓存: 零网络调用."""
    server._exchange_cache.update(at=time.time(), usd_cny=6.5)
    calls = []
    _stub_urlopen(monkeypatch, calls, body={"rates": {"CNY": 7.44}})
    assert server._fetch_usd_cny() == 6.5
    assert calls == []


def test_exchange_stale_read_returns_old_value_and_triggers_refresh(net_state, monkeypatch):
    """过期读: 请求线程零外呼, 本次返回旧值, 防重入触发后台刷新."""
    server._exchange_cache.update(
        at=time.time() - server._EXCHANGE_TTL - 1, usd_cny=6.5)
    calls = []
    _stub_urlopen(monkeypatch, calls, body={"rates": {"CNY": 7.44}})
    triggered = []
    monkeypatch.setattr(server, "_ensure_exchange_refresh_async",
                        lambda: triggered.append(1))
    assert server._fetch_usd_cny() == 6.5  # 本次仍返回旧值
    assert calls == []  # 请求线程未外呼
    assert triggered == [1]


def test_exchange_background_refresh_updates_cache(net_state, monkeypatch):
    """后台刷新成功: 真实外呼一次并更新缓存汇率."""
    calls = []
    _stub_urlopen(monkeypatch, calls, body={"rates": {"CNY": 7.44}})
    server._ensure_exchange_refresh_async()
    assert _wait_until(lambda: server._exchange_refreshing is False)
    assert len(calls) == 1
    assert server._exchange_cache["usd_cny"] == 7.44


def test_exchange_refresh_failure_keeps_old_value_6h(net_state, monkeypatch):
    """刷新失败: 保留旧值且推进 at (6h 内不再试)."""
    server._exchange_cache.update(at=100.0, usd_cny=6.5)
    calls = []
    _stub_urlopen(monkeypatch, calls, error=OSError("network down"))
    before = time.time()
    server._refresh_usd_cny()
    assert len(calls) == 1
    assert server._exchange_cache["usd_cny"] == 6.5  # 旧值保留
    assert server._exchange_cache["at"] >= before  # 失败也写 at


def test_exchange_refresh_no_reentry(net_state, monkeypatch):
    """刷新进行中 (防重入布尔为 True): 不再起多余刷新线程."""
    calls = []
    _stub_urlopen(monkeypatch, calls, body={"rates": {"CNY": 7.44}})
    monkeypatch.setattr(server, "_exchange_refreshing", True)
    server._ensure_exchange_refresh_async()
    assert calls == []
    assert server._exchange_refreshing is True


# ---------------------------------------------------------------------------
# 2. ZCode 统一单飞: 并发单呼 / worker+请求单呼 / 过期刷新真实外呼 / 超时占位
# ---------------------------------------------------------------------------


def test_zcode_concurrent_requests_single_flight(net_state, monkeypatch):
    """并发 N 个首采请求: 仅 1 次外呼, 全部共享同一结果."""
    calls = []

    def slow_fetch():
        calls.append(1)
        time.sleep(0.15)
        return {"success": True, "windows": []}

    monkeypatch.setattr(zcode_api, "fetch_quota", slow_fetch)

    results = []
    barrier = threading.Barrier(4)

    def hit():
        barrier.wait()
        results.append(server._zcode_quota_payload())

    threads = [threading.Thread(target=hit) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(calls) == 1
    assert results == [{"success": True, "windows": []}] * 4


def test_zcode_worker_and_request_single_flight(net_state, monkeypatch):
    """预热 worker 与请求路径并发: 仅 1 次外呼, 请求方共享 worker 结果."""
    calls = []

    def slow_fetch():
        calls.append(1)
        time.sleep(0.1)
        return {"success": True, "windows": []}

    monkeypatch.setattr(zcode_api, "fetch_quota", slow_fetch)

    with server._zcode_first_fetch_lock:  # 模拟拉取窗口: 先占住单飞锁
        server._ensure_zcode_quota_async()  # worker 排上 (bool=True), 阻塞等锁
        assert server._zcode_quota_refreshing is True
        results = []
        req = threading.Thread(
            target=lambda: results.append(server._zcode_quota_payload()))
        req.start()
        time.sleep(0.05)  # 让请求线程进入等锁
        assert calls == []  # 锁未放, 无人外呼
    # 放锁: worker 与请求路径只有一个真正拉取, 另一方锁内复查后共享
    req.join(timeout=10)
    assert not req.is_alive()
    assert _wait_until(lambda: server._zcode_quota_refreshing is False)
    assert len(calls) == 1
    assert results == [{"success": True, "windows": []}]


def test_zcode_stale_cache_refreshes_in_background(net_state, monkeypatch):
    """过期缓存 (data 非空且超 TTL): 本次返回旧值, 后台刷新真实外呼更新.

    §1.2.1 v3 修正回归: 单飞锁内复查对过期数据照常拉取, 缓存不滞留旧值.
    """
    old = {"success": True, "windows": ["old"]}
    new = {"success": True, "windows": ["new"]}
    server._zcode_quota_cache.update(
        at=time.time() - server.QUOTA_CACHE_TTL - 1, data=old)
    calls = []

    def slow_fetch():
        calls.append(1)
        time.sleep(0.2)  # 慢于请求返回路径: payload 返回时后台尚未完成
        return new

    monkeypatch.setattr(zcode_api, "fetch_quota", slow_fetch)

    assert server._zcode_quota_payload() == old  # 过期: 本次返回旧值
    assert _wait_until(lambda: server._zcode_quota_refreshing is False)
    assert calls == [1]  # 后台刷新真实外呼
    assert server._zcode_quota_cache["data"] is new  # 缓存已更新
    assert server._zcode_quota_payload() is new  # 下次拉取见新值


def test_zcode_fetch_under_lock_stale_still_fetches(net_state, monkeypatch):
    """单飞原语直接验证: 缓存过期时锁内照常拉取; 有效时复查直返不外呼."""
    server._zcode_quota_cache.update(at=1.0, data={"success": True, "old": True})
    calls = []
    monkeypatch.setattr(
        zcode_api, "fetch_quota", lambda: calls.append(1) or {"success": True})

    assert server._zcode_fetch_under_lock() is True
    assert calls == [1]  # 过期刷新者照常拉取

    calls.clear()
    assert server._zcode_fetch_under_lock() is True
    assert calls == []  # 缓存有效: 复查直返


def test_zcode_waiter_timeout_returns_placeholder_and_enqueues(net_state, monkeypatch):
    """等待者超时: 返回错误占位 (避开凭证前缀) 并入队后台刷新, 不自行拉取."""
    monkeypatch.setattr(server, "_ZCODE_FETCH_WAIT", 0.05)  # 注入极短等待
    calls = []
    monkeypatch.setattr(
        zcode_api, "fetch_quota", lambda: calls.append(1) or {"success": True})
    enqueued = []
    monkeypatch.setattr(server, "_ensure_zcode_quota_async",
                        lambda: enqueued.append(1))

    with server._zcode_first_fetch_lock:  # 他人持锁拉取中
        payload = server._zcode_quota_payload()
    assert payload == {"success": False, "error": "额度查询超时，请稍后重试"}
    assert not payload["error"].startswith(CREDENTIAL_ERROR_PREFIX)  # 防误路由登录引导
    assert calls == []  # 超时者不自行再拉取
    assert enqueued == [1]  # 已入队后台刷新


# ---------------------------------------------------------------------------
# 3. 验收回归补充 (Task 3): 启动预热接线 + 前后端源码级契约
# ---------------------------------------------------------------------------


def test_zcode_quota_warmup_enqueues_single_background_fetch(net_state, monkeypatch):
    """启动预热入口 (main.py 挂载 zcode_quota_warmup): 排一次后台刷新并外呼一次."""
    calls = []
    monkeypatch.setattr(
        zcode_api, "fetch_quota", lambda: calls.append(1) or {"success": True})
    server.zcode_quota_warmup()
    assert _wait_until(lambda: server._zcode_quota_refreshing is False)
    assert calls == [1]
    assert server._zcode_quota_cache["data"] == {"success": True}


def test_warmup_threads_mounted_in_main():
    """main.py 启动预热线程接线 (计划 §1.1.2 必改项) 未被回归掉.

    main() 为 GUI 入口无法单测, 以源码级断言锁接线.
    """
    src = Path(server.__file__).parent.joinpath("main.py").read_text(encoding="utf-8")
    assert "server.zcode_quota_warmup" in src
    assert "server._refresh_usd_cny" in src


def test_frontend_credential_prefix_contract():
    """前端 renderZcodeQuota 的 includes 路由字面量与后端前缀一致 (跨语言契约).

    两端漂移会把凭证缺失误渲染为错误占位 (或反之), 计划 §1.2.3 的伴生约束.
    """
    js = _APP_JS.read_text(encoding="utf-8")
    assert f'err.includes("{CREDENTIAL_ERROR_PREFIX}")' in js


def test_frontend_i18n_timeout_and_retry_keys():
    """requestTimeout / retry 两键 zh+en 字典各一份, 且 api()/占位的接线在位."""
    js = _APP_JS.read_text(encoding="utf-8")
    assert len(re.findall(r"requestTimeout:\s*\"", js)) == 2
    assert len(re.findall(r"(?<![A-Za-z])retry:\s*\"", js)) == 2
    assert 'e.name === "TimeoutError"' in js
    assert 't("requestTimeout")' in js
    assert 't("retry")' in js


def test_app_js_syntax_node_check():
    """node --check app/web/app.js (计划 §2.3 前端自动化检查; 无 node 环境跳过)."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node 不可用")
    proc = subprocess.run(
        [node, "--check", str(_APP_JS)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
