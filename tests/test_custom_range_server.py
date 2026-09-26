"""自定义范围: server 解析 helper 与端点透传测试 (设计文档 §5)."""
from __future__ import annotations

import pytest

from app import server


def _q(range_, start=None, end=None):
    q = {"range": [range_]}
    if start is not None:
        q["start"] = [start]
    if end is not None:
        q["end"] = [end]
    return q


def test_custom_range_from_query_matrix():
    # 合法: start + end / start + 空 end / T 分隔 / 缺秒
    assert server._custom_range_from_query(_q("custom", "2026-09-20 08:00:00", "2026-09-20 18:00:00")) \
        == ("2026-09-20 08:00:00", "2026-09-20 18:00:00")
    assert server._custom_range_from_query(_q("custom", "2026-09-20 08:00:00", "")) \
        == ("2026-09-20 08:00:00", "")
    assert server._custom_range_from_query(_q("custom", "2026-09-20T08:00:05")) \
        == ("2026-09-20T08:00:05", "")
    assert server._custom_range_from_query(_q("custom", "2026-09-20 08:00")) \
        == ("2026-09-20 08:00", "")
    # 非法: 缺 start / start 不可解析 / end<start / 非 custom range 一律 (None, None)
    for bad in (
        _q("custom"),
        _q("custom", start=None, end="2026-09-20 00:00:00"),
        _q("custom", "garbage"),
        _q("custom", "2026-09-20 00:00:01", "2026-09-20 00:00:00"),
        _q("7d", "2026-09-20 00:00:00", "2026-09-21 00:00:00"),
    ):
        assert server._custom_range_from_query(bad) == (None, None)
