"""主题偏好持久化契约测试 (20260909 界面优化计划 §3.4/§5).

覆盖: theme light/dark/非法/null; 读损坏值回退; 保存不覆盖未知键与同步配置;
关闭重开数据库恢复; 首页只注入主题枚举且 Content-Length 正确、无敏感值;
主窗口创建参数匹配已存主题.
"""
from __future__ import annotations

import json

import pytest

from app import db, main, server


# ---------------------------------------------------------------------------
# 1. db 存储契约 (tmp_codex_db: conftest 提供的独立临时数据库 fixture)
# ---------------------------------------------------------------------------


def test_theme_default_is_none(tmp_codex_db):
    assert db.get_settings()["theme"] is None


def test_save_theme_light_dark_roundtrip(tmp_codex_db):
    db.save_settings({"theme": "dark"})
    assert db.get_settings()["theme"] == "dark"
    db.save_settings({"theme": "light"})
    assert db.get_settings()["theme"] == "light"
    # 关闭重开数据库仍恢复
    db.close_db()
    assert db.get_settings()["theme"] == "light"


def test_save_theme_invalid_and_null_ignored(tmp_codex_db):
    db.save_settings({"theme": "dark"})
    db.save_settings({"theme": "neon"})        # 非法枚举: 保留当前值
    assert db.get_settings()["theme"] == "dark"
    db.save_settings({"theme": None})          # null PUT: 忽略
    assert db.get_settings()["theme"] == "dark"
    db.save_settings({"theme": 1})             # 非字符串: 忽略
    assert db.get_settings()["theme"] == "dark"


def test_corrupt_theme_value_read_as_none(tmp_codex_db):
    conn = db.get_db()
    raw = db._raw_payload(conn)
    raw["theme"] = "neon"                      # 模拟历史损坏值直写
    db._write_payload(conn, raw)
    conn.commit()
    assert db.get_settings()["theme"] is None


def test_save_theme_preserves_unknown_keys_and_sync_config(tmp_codex_db):
    db.save_settings({"sync_interval_sec": 900})
    db.save_key_names({"k1": "生产 Key"})       # 非白名单键
    db.save_settings({"theme": "dark"})
    raw = db._raw_payload(db.get_db())
    assert raw.get("key_names") == {"k1": "生产 Key"}, "theme 保存覆盖了未知键"
    assert db.get_settings()["sync_interval_sec"] == 900, "theme 保存覆盖了同步配置"
