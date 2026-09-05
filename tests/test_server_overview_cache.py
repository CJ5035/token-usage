"""accounts/overview 组装缓存测试 (方案4②): TTL 内不重查库, 失效后重查."""
from __future__ import annotations

import pytest

from app import db, server


@pytest.fixture()
def tmp_report_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    yield tmp_path
    db.close_db()


@pytest.fixture()
def _no_side_effect(monkeypatch):
    """隔离组装路径的外部副作用: 配额后台刷新会发真实网络请求, 汇率缓存
    首次未命中会 urlopen(10s 超时) — 测试必须打桩."""
    monkeypatch.setattr(server, "_ensure_quota_async", lambda aid=None: None)
    monkeypatch.setattr(server, "_fetch_usd_cny", lambda: 7.2)


def test_overview_payload_cached_until_invalidated(tmp_report_db, _no_side_effect, monkeypatch):
    server._invalidate_overview_cache()
    calls = {"n": 0}
    real_list = db.list_accounts

    def counting_list():
        calls["n"] += 1
        return real_list()

    monkeypatch.setattr(db, "list_accounts", counting_list)
    server._accounts_overview_payload()
    server._accounts_overview_payload()  # TTL 内第二次: 不重查
    assert calls["n"] == 1
    server._invalidate_overview_cache()
    server._accounts_overview_payload()  # 失效后: 重查
    assert calls["n"] == 2


def test_overview_payload_reflects_account_change_after_invalidate(tmp_report_db, _no_side_effect):
    server._invalidate_overview_cache()
    before = len(server._accounts_overview_payload()["accounts"])
    db.add_account("tok-x", "ws-x", switch=False, dedupe_key="ws-x")
    server._invalidate_overview_cache()  # 模拟 switch/delete 等入口的失效调用
    after = len(server._accounts_overview_payload()["accounts"])
    assert after == before + 1
