"""server.py BAI 同步调度测试: 分页/增量策略 (G3) / 配额分流 / source 分发."""
from __future__ import annotations

import json

import pytest

from app import bai_api, db, server


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """独立临时库 + 重置 server 跨线程状态 (配额缓存/同步状态/防重入)."""
    monkeypatch.setattr(db, "data_dir", lambda: str(tmp_path))
    db._DB = None
    server._quota_cache.clear()
    server._quota_refreshing.clear()
    server._sync_state.update(
        running=False, mode="", page=0, inserted=0, phase="idle", message="", account=""
    )
    yield tmp_path
    db.close_db()


@pytest.fixture()
def no_window(tmp_db):
    """关闭同步范围裁剪, 避免测试记录被 window_days 删掉."""
    db.save_settings({"window_days": None})
    return tmp_db


def _bai_account(name="BAI", dedupe_key="usr-1") -> int:
    """建一个 BAI 账号并设为活跃, 返回 account_id."""
    jar = json.dumps([{"name": "__Secure-authjs.session-token", "value": "tok"}])
    aid = db.add_account(jar, source="bai", dedupe_key=dedupe_key, switch=True)
    db.rename_account(aid, name)
    return aid


def _page(items, has_more=False, next_cursor=None, page=1, page_size=100):
    return {
        "data": items, "has_more": has_more, "next_cursor": next_cursor,
        "page": page, "pageSize": page_size,
    }


def _bai_item(usg_id, created="2026-09-01T08:00:00Z"):
    return {
        "id": usg_id, "created_at": created, "model": "glm-5.3-flash",
        "input_tokens": 10, "output_tokens": 5, "cache_tokens": {},
    }


# ---------------------------------------------------------------------------
# G3 分页/增量策略
# ---------------------------------------------------------------------------

def test_incremental_all_old_stops_without_second_page(no_window, monkeypatch):
    """首页全旧数据 -> 新增 0 条且不翻第 2 页 (增量命中即停)."""
    aid = _bai_account()
    db.insert_usage_records([bai_api.parse_usage_record(_bai_item("old_1"))], account_id=aid)

    calls = []

    def fake_fetch(cookie, cursor=None, page_size=100):
        calls.append(cursor)
        # 首页返回已存在的旧记录, 且服务端表示 has_more (数据更多)
        return _page([_bai_item("old_1")], has_more=True, next_cursor="cur2")

    monkeypatch.setattr(bai_api, "fetch_usage_records", fake_fetch)
    result = server._sync_bai_account(aid, "BAI", "incremental", None)

    assert result["ok"] is True
    assert result["inserted"] == 0      # 全部是旧数据
    assert len(calls) == 1              # 未翻第 2 页
    assert result["pages"] == 1


def test_incremental_mixed_old_and_new_stops_after_page1(no_window, monkeypatch):
    """首页含新+旧, 页内有任一旧记录 -> 该页照常 upsert 后停止翻页 (G3 命中即停)."""
    aid = _bai_account()
    db.insert_usage_records([bai_api.parse_usage_record(_bai_item("old_1"))], account_id=aid)

    calls = []

    def fake_fetch(cookie, cursor=None, page_size=100):
        calls.append(cursor)
        return _page(
            [_bai_item("old_1"), _bai_item("new_1")],
            has_more=True, next_cursor="cur2",
        )

    monkeypatch.setattr(bai_api, "fetch_usage_records", fake_fetch)
    result = server._sync_bai_account(aid, "BAI", "incremental", None)

    assert result["ok"] is True
    assert result["inserted"] == 1      # new_1 入库, old_1 幂等未重复
    assert len(calls) == 1              # 页内含旧记录 -> 命中即停, 不翻第 2 页
    assert result["pages"] == 1


def test_full_pages_until_has_more_false(no_window, monkeypatch):
    """全量模式 -> 翻页直到 has_more=false (不受页内含旧记录影响)."""
    aid = _bai_account()
    db.insert_usage_records([bai_api.parse_usage_record(_bai_item("old_1"))], account_id=aid)

    pages = iter(
        [
            _page([_bai_item("old_1")], has_more=True, next_cursor="c1"),     # 页1: 全旧, 仍继续
            _page([_bai_item("new_2")], has_more=True, next_cursor="c2"),     # 页2: 新
            _page([_bai_item("new_3")], has_more=False, next_cursor=None),    # 页3: 最后
        ]
    )
    cursors = []
    monkeypatch.setattr(
        bai_api, "fetch_usage_records",
        lambda cookie, cursor=None, page_size=100: (cursors.append(cursor) or next(pages)),
    )
    result = server._sync_bai_account(aid, "BAI", "full", None)

    assert result["ok"] is True
    assert result["inserted"] == 2          # new_2, new_3 入库
    assert cursors == [None, "c1", "c2"]    # 从第 1 页翻到 has_more=false
    assert result["pages"] == 3


# ---------------------------------------------------------------------------
# 配额分流
# ---------------------------------------------------------------------------

def test_quota_bai_returns_points_window(no_window, monkeypatch):
    """BAI 账号配额 -> 单格 unit='points' 结构, points_balance 取实际值."""
    aid = _bai_account()
    monkeypatch.setattr(
        bai_api, "fetch_usage_points",
        lambda cookie: {"points_balance": "300000", "points_expiring": "250000"},
    )
    monkeypatch.setattr(
        bai_api, "build_cookie_header", lambda tok: tok,
    )
    quota = server._fetch_quota_with_cache(aid, "cookie-json", "")
    assert quota["success"] is True
    w = quota["windows"][0]
    assert w["label"] == "Points"
    assert w["unit"] == "points"
    assert w["used"] == 0 and w["remaining"] == 100 and w["total"] == 100
    assert w["reset_in_sec"] is None
    assert w["points_balance"] == "300000"
    assert w["points_expiring"] == "250000"
    # 已写入缓存槽, TTL 内命中
    assert server._quota_cache[aid]["data"] is quota


def test_quota_opencode_uses_fetch_quota(tmp_db, monkeypatch):
    """opencode 账号配额 -> 走原 fetch_quota, 不被 BAI 分支接管."""
    aid = db.add_account("op-token", "ws-a", switch=True, source="opencode")

    class _FakeResult:  # 模拟 opencode QuotaResult.to_dict()
        def to_dict(self):
            return {"success": True, "windows": [{"label": "Calls", "unit": "req"}]}

    calls = []
    monkeypatch.setattr(server, "fetch_quota", lambda tok, hint: (calls.append((tok, hint)) or _FakeResult()))

    def _no_bai(cookie):
        raise AssertionError("BAI 不应被调用")

    monkeypatch.setattr(bai_api, "fetch_usage_points", _no_bai)

    quota = server._fetch_quota_with_cache(aid, "op-token", "ws-a")
    assert quota["success"] is True
    assert calls == [("op-token", "ws-a")]


def test_quota_bai_failure_structure(no_window, monkeypatch):
    """BAI 配额拉取失败 -> {success: false, error}, 与 opencode 失败结构一致."""
    aid = _bai_account()

    def _fail(cookie):
        raise bai_api.BAIAuthError("认证失败")

    monkeypatch.setattr(bai_api, "fetch_usage_points", _fail)
    quota = server._fetch_quota_with_cache(aid, "cookie-json", "")
    assert quota["success"] is False
    assert "认证失败" in quota["error"]


# ---------------------------------------------------------------------------
# sync_usage 分发: BAI 账号不触发 opencode 专属步骤
# ---------------------------------------------------------------------------

def test_sync_dispatches_bai_without_resolve_workspace(no_window, monkeypatch):
    """source='bai' 的活跃账号 -> 走 _sync_bai_account, 不调用 resolve_workspace_id."""
    bai_aid = _bai_account()   # 设为活跃
    resolve_calls = []
    monkeypatch.setattr(server, "resolve_workspace_id", lambda ws, tok: resolve_calls.append(ws))
    monkeypatch.setattr(
        bai_api, "fetch_usage_records",
        lambda cookie, cursor=None, page_size=100: _page([], has_more=False),
    )
    result = server.sync_usage("full")

    assert result["ok"] is True
    assert resolve_calls == []          # BAI 分支不解析工作区
    assert db.get_sync_state(bai_aid)["total_records"] == 0